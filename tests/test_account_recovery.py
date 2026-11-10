"""
找回密码与注销账号测试（邮箱验证码流程）

1. 服务层：验证码签发、校验、错误次数上限、过期、单次使用、用途隔离（内存仓储）
2. 注销账号：级联删除、共享语料保护、事务提交后的索引/文件/缓存清理
3. HTTP：对外响应与账号是否存在无关（防枚举）、未登录拒绝、注销后清除 cookie

真实 PostgreSQL 上的 SQL（FOR UPDATE 行锁、级联删除）需在服务器上做一次端到端检查。
"""
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import tokens
from app.auth.passwords import hash_password, verify_password
from app.auth.rate_limit import account_rate_limiter
from app.auth.validation import AccountValidationError
from app.config import settings
from app.exceptions.handlers import AppException
from app.mail.sender import MailMessage, MailSendError
from app.services.session_service import SessionService
from app.services.account_service import (
    AccountNotFoundError,
    AccountService,
    CodeDeliveryError,
    InvalidCodeError,
    SharedCorpusAccountError,
)

OLD_PASSWORD = "old-pass-123"
NEW_PASSWORD = "new-pass-456"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
CODE_RE = re.compile(r'letter-spacing:4px">(\d{6})</p>')


# ═══════════════════════════════════════════════════════════════
# 测试替身
# ═══════════════════════════════════════════════════════════════

class FakeRepo:
    """与 AccountRepository 同名同语义的内存实现（conn 参数忽略）"""

    def __init__(self, users=(), documents=()):
        self.users: dict[str, dict] = {str(u["id"]): dict(u) for u in users}
        self.documents: list[dict] = [dict(d) for d in documents]
        self.codes: list[dict] = []

    async def find_by_id(self, conn, user_id):
        u = self.users.get(str(user_id))
        return dict(u) if u else None

    async def find_by_email(self, conn, email):
        return next((dict(u) for u in self.users.values() if u["email"] == email), None)

    async def update_password(self, conn, user_id, password_hash, at):
        self.users[str(user_id)]["password_hash"] = password_hash

    async def mark_verified(self, conn, user_id, at):
        u = self.users[str(user_id)]
        if u["email_verified_at"] is None:
            u["email_verified_at"] = at

    async def delete_user(self, conn, user_id):
        uid = str(user_id)
        self.users.pop(uid, None)
        # 模拟 ON DELETE CASCADE
        self.documents = [d for d in self.documents if d["user_id"] != uid]
        self.codes = [c for c in self.codes if c["user_id"] != uid]

    async def owns_shared_documents(self, conn, user_id):
        return any(d["is_shared"] and d["user_id"] == str(user_id) for d in self.documents)

    async def list_documents_of(self, conn, user_id):
        return [dict(d) for d in self.documents if d["user_id"] == str(user_id)]

    async def create_code(self, conn, user_id, purpose, code_hash, expires_at):
        self.codes.append({
            "id": str(uuid.uuid4()), "user_id": str(user_id), "purpose": purpose,
            "code_hash": code_hash, "attempts": 0, "expires_at": expires_at, "used_at": None,
        })

    async def invalidate_codes(self, conn, user_id, purpose, at):
        for c in self.codes:
            if c["user_id"] == str(user_id) and c["purpose"] == purpose and c["used_at"] is None:
                c["used_at"] = at

    async def lock_active_code(self, conn, user_id, purpose, at):
        active = [
            c for c in self.codes
            if c["user_id"] == str(user_id) and c["purpose"] == purpose
            and c["used_at"] is None and c["expires_at"] > at
        ]
        return dict(active[-1]) if active else None

    async def bump_code_attempts(self, conn, code_id):
        next(c for c in self.codes if c["id"] == code_id)["attempts"] += 1

    async def mark_code_used(self, conn, code_id, at):
        next(c for c in self.codes if c["id"] == code_id)["used_at"] = at


class FakeMailer:
    def __init__(self):
        self.sent: list[MailMessage] = []
        self.fail = False

    async def send(self, message):
        if self.fail:
            raise MailSendError("模拟发送失败")
        self.sent.append(message)


class FakeIndex:
    def __init__(self):
        self.removed: list[str] = []

    def remove_document(self, document_id):
        self.removed.append(document_id)
        return 1


class FakeStorage:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, storage_path):
        self.deleted.append(storage_path)


class FakeCache:
    def __init__(self):
        self.invalidated: list[str] = []

    async def invalidate(self, doc_id):
        self.invalidated.append(doc_id)


@asynccontextmanager
async def _noop():
    yield None


class FakeDb:
    def __init__(self):
        self.pool = self

    def acquire(self):
        return _noop()

    def transaction(self):
        return _noop()


@dataclass
class Harness:
    service: AccountService
    repo: FakeRepo
    mailer: FakeMailer
    index: FakeIndex
    storage: FakeStorage
    cache: FakeCache
    clock: dict = field(default_factory=lambda: {"now": T0})

    def advance(self, **kwargs):
        self.clock["now"] += timedelta(**kwargs)

    def last_code(self) -> str:
        match = CODE_RE.search(self.mailer.sent[-1].html)
        assert match, "邮件中没有验证码"
        return match.group(1)


def build(users=(), documents=()) -> Harness:
    repo = FakeRepo(users, documents)
    mailer = FakeMailer()
    index, storage, cache = FakeIndex(), FakeStorage(), FakeCache()
    harness = Harness(service=None, repo=repo, mailer=mailer, index=index, storage=storage, cache=cache)
    harness.service = AccountService(
        db=FakeDb(), repo=repo, mailer=mailer, clock=lambda: harness.clock["now"],
        index=index, storage=storage, doc_cache=cache,
    )
    return harness


def account(email, *, verified=True, user_id=None):
    return {
        "id": user_id or str(uuid.uuid4()), "username": email, "email": email,
        "password_hash": hash_password(OLD_PASSWORD),
        "email_verified_at": T0 if verified else None,
    }


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    account_rate_limiter._hits.clear()
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://suming.work")
    monkeypatch.setattr(settings, "PASSWORD_MIN_LENGTH", 10)
    yield
    account_rate_limiter._hits.clear()


# ═══════════════════════════════════════════════════════════════
# 1. 找回密码（服务层）
# ═══════════════════════════════════════════════════════════════

class TestPasswordReset:

    async def test_code_is_mailed_to_registered_email(self):
        alice = account("alice@example.com")
        h = build([alice])

        await h.service.request_password_reset("alice@example.com")

        assert len(h.mailer.sent) == 1
        assert h.mailer.sent[0].to == "alice@example.com"
        assert re.fullmatch(r"\d{6}", h.last_code())

    async def test_unknown_email_is_silent(self):
        h = build()
        await h.service.request_password_reset("nobody@example.com")
        assert h.mailer.sent == []

    async def test_malformed_email_is_silent(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("not-an-email")
        assert h.mailer.sent == []

    async def test_stored_code_is_not_plaintext(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("alice@example.com")
        code = h.last_code()
        assert h.repo.codes[0]["code_hash"] != code
        assert len(h.repo.codes[0]["code_hash"]) == 64

    async def test_correct_code_sets_new_password(self):
        alice = account("alice@example.com")
        h = build([alice])
        await h.service.request_password_reset("alice@example.com")

        await h.service.reset_password("alice@example.com", h.last_code(), NEW_PASSWORD)

        stored = h.repo.users[alice["id"]]["password_hash"]
        assert verify_password(NEW_PASSWORD, stored)
        assert not verify_password(OLD_PASSWORD, stored)

    async def test_code_is_single_use(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("alice@example.com")
        code = h.last_code()
        await h.service.reset_password("alice@example.com", code, NEW_PASSWORD)

        with pytest.raises(InvalidCodeError):
            await h.service.reset_password("alice@example.com", code, "another-pass-789")

    async def test_wrong_codes_exhaust_attempts_then_correct_code_is_rejected(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("alice@example.com")
        real = h.last_code()
        wrong = "000000" if real != "000000" else "111111"

        for _ in range(settings.EMAIL_CODE_MAX_ATTEMPTS):
            with pytest.raises(InvalidCodeError):
                await h.service.reset_password("alice@example.com", wrong, NEW_PASSWORD)

        # 错误次数用尽后，即使输入正确的验证码也不能再用
        with pytest.raises(InvalidCodeError):
            await h.service.reset_password("alice@example.com", real, NEW_PASSWORD)
        assert h.repo.codes[0]["attempts"] == settings.EMAIL_CODE_MAX_ATTEMPTS

    async def test_expired_code_is_rejected(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("alice@example.com")
        code = h.last_code()

        h.advance(minutes=settings.EMAIL_CODE_TTL_MINUTES + 1)

        with pytest.raises(InvalidCodeError):
            await h.service.reset_password("alice@example.com", code, NEW_PASSWORD)

    async def test_new_code_invalidates_previous_one(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("alice@example.com")
        first = h.last_code()
        await h.service.request_password_reset("alice@example.com")
        second = h.last_code()
        if first == second:
            pytest.skip("两次随机验证码碰巧相同，无法区分")

        with pytest.raises(InvalidCodeError):
            await h.service.reset_password("alice@example.com", first, NEW_PASSWORD)
        await h.service.reset_password("alice@example.com", second, NEW_PASSWORD)

    async def test_reset_also_marks_email_verified(self):
        alice = account("alice@example.com", verified=False)
        h = build([alice])
        await h.service.request_password_reset("alice@example.com")

        await h.service.reset_password("alice@example.com", h.last_code(), NEW_PASSWORD)

        assert h.repo.users[alice["id"]]["email_verified_at"] is not None

    async def test_weak_password_rejected_before_code_is_consumed(self):
        h = build([account("alice@example.com")])
        await h.service.request_password_reset("alice@example.com")

        with pytest.raises(AccountValidationError):
            await h.service.reset_password("alice@example.com", h.last_code(), "short")

        # 密码不合规是请求参数错误，不应消耗验证码的尝试次数
        assert h.repo.codes[0]["attempts"] == 0

    async def test_delete_code_cannot_be_used_for_reset(self):
        h = build([account("alice@example.com")])
        alice_id = next(iter(h.repo.users))
        await h.service.request_account_deletion(alice_id)
        delete_code = h.last_code()

        with pytest.raises(InvalidCodeError):
            await h.service.reset_password("alice@example.com", delete_code, NEW_PASSWORD)

    async def test_mail_failure_does_not_reveal_account(self):
        h = build([account("alice@example.com")])
        h.mailer.fail = True
        # 与未注册邮箱的响应相同：不抛异常
        await h.service.request_password_reset("alice@example.com")
        await h.service.request_password_reset("nobody@example.com")


# ═══════════════════════════════════════════════════════════════
# 2. 注销账号（服务层）
# ═══════════════════════════════════════════════════════════════

class TestAccountDeletion:

    async def test_code_is_sent_to_own_email(self):
        alice = account("alice@example.com")
        h = build([alice])

        await h.service.request_account_deletion(alice["id"])

        assert h.mailer.sent[-1].to == "alice@example.com"
        assert "注销账号" in h.mailer.sent[-1].subject

    async def test_mail_failure_is_reported_to_logged_in_user(self):
        alice = account("alice@example.com")
        h = build([alice])
        h.mailer.fail = True

        with pytest.raises(CodeDeliveryError):
            await h.service.request_account_deletion(alice["id"])

    async def test_wrong_code_keeps_account(self):
        alice = account("alice@example.com")
        h = build([alice])
        await h.service.request_account_deletion(alice["id"])
        wrong = "000000" if h.last_code() != "000000" else "111111"

        with pytest.raises(InvalidCodeError):
            await h.service.delete_account(alice["id"], wrong)

        assert alice["id"] in h.repo.users

    async def test_delete_removes_own_documents_and_external_state_only(self):
        alice = account("alice@example.com")
        bob = account("bob@example.com")
        docs = [
            {"id": "doc-a1", "user_id": alice["id"], "storage_path": "uploads/a1.pdf", "is_shared": False},
            {"id": "doc-a2", "user_id": alice["id"], "storage_path": "uploads/a2.md", "is_shared": False},
            {"id": "doc-b1", "user_id": bob["id"], "storage_path": "uploads/b1.txt", "is_shared": False},
        ]
        h = build([alice, bob], docs)
        await h.service.request_account_deletion(alice["id"])

        await h.service.delete_account(alice["id"], h.last_code())

        assert alice["id"] not in h.repo.users
        assert bob["id"] in h.repo.users
        assert [d["id"] for d in h.repo.documents] == ["doc-b1"]
        assert h.index.removed == ["doc-a1", "doc-a2"]
        assert h.storage.deleted == ["uploads/a1.pdf", "uploads/a2.md"]
        assert h.cache.invalidated == ["doc-a1", "doc-a2"]

    async def test_deleted_account_gets_not_found_on_next_request(self):
        alice = account("alice@example.com")
        h = build([alice])
        await h.service.request_account_deletion(alice["id"])
        code = h.last_code()
        await h.service.delete_account(alice["id"], code)

        # 账号已删除后，旧 cookie 仍能通过签名校验，但业务请求应明确报「账号不存在」，而不是 500
        with pytest.raises(AccountNotFoundError):
            await h.service.request_account_deletion(alice["id"])

    async def test_owner_of_shared_corpus_cannot_request_deletion(self):
        demo = account("demo_user")
        corpus = {"id": "corpus-1", "user_id": demo["id"], "storage_path": "data/c.md", "is_shared": True}
        h = build([demo], [corpus])

        with pytest.raises(SharedCorpusAccountError):
            await h.service.request_account_deletion(demo["id"])
        assert h.mailer.sent == []

    async def test_owner_of_shared_corpus_cannot_delete_even_with_valid_code(self):
        demo = account("demo_user")
        corpus = {"id": "corpus-1", "user_id": demo["id"], "storage_path": "data/c.md", "is_shared": True}
        h = build([demo], [corpus])
        # 验证码在共享语料出现之前签发（模拟并发场景）
        h.repo.documents = []
        await h.service.request_account_deletion(demo["id"])
        code = h.last_code()
        h.repo.documents = [corpus]

        with pytest.raises(SharedCorpusAccountError):
            await h.service.delete_account(demo["id"], code)
        assert demo["id"] in h.repo.users
        assert h.repo.documents == [corpus]
        assert h.index.removed == []


# ═══════════════════════════════════════════════════════════════
# 3. HTTP 接口
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
async def client():
    from app.dependencies.auth import get_account_service
    from app.main import app

    alice = account("alice@example.com")
    h = build([alice], [
        {"id": "doc-a1", "user_id": alice["id"], "storage_path": "uploads/a1.pdf", "is_shared": False},
    ])
    app.dependency_overrides[get_account_service] = lambda: h.service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.harness = h
            c.alice_id = alice["id"]
            yield c
    finally:
        app.dependency_overrides.pop(get_account_service, None)


def _login_cookie(client):
    return tokens.issue(client.alice_id, "alice@example.com")


class TestRecoveryHttp:

    async def test_forgot_response_is_identical_for_known_and_unknown_email(self, client):
        known = await client.post("/api/v1/auth/password/forgot", json={"email": "alice@example.com"})
        unknown = await client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})

        assert known.status_code == unknown.status_code == 200
        assert known.json()["message"] == unknown.json()["message"]
        assert known.json()["data"] == unknown.json()["data"] == {}

    async def test_forgot_is_rate_limited_per_email(self, client):
        for _ in range(settings.RESEND_MAX_PER_EMAIL):
            ok = await client.post("/api/v1/auth/password/forgot", json={"email": "alice@example.com"})
            assert ok.status_code == 200
        blocked = await client.post("/api/v1/auth/password/forgot", json={"email": "alice@example.com"})
        assert blocked.status_code == 429

    async def test_reset_with_non_six_digit_code_is_rejected_by_schema(self, client):
        resp = await client.post("/api/v1/auth/password/reset", json={
            "email": "alice@example.com", "code": "12345", "new_password": NEW_PASSWORD,
        })
        assert resp.status_code == 422

    async def test_reset_with_wrong_code_is_400(self, client):
        await client.post("/api/v1/auth/password/forgot", json={"email": "alice@example.com"})
        real = client.harness.last_code()
        wrong = "000000" if real != "000000" else "111111"

        resp = await client.post("/api/v1/auth/password/reset", json={
            "email": "alice@example.com", "code": wrong, "new_password": NEW_PASSWORD,
        })
        assert resp.status_code == 400

    async def test_reset_with_correct_code_succeeds(self, client):
        await client.post("/api/v1/auth/password/forgot", json={"email": "alice@example.com"})
        code = client.harness.last_code()

        resp = await client.post("/api/v1/auth/password/reset", json={
            "email": "alice@example.com", "code": code, "new_password": NEW_PASSWORD,
        })
        assert resp.status_code == 200

    async def test_delete_code_requires_login(self, client):
        resp = await client.post("/api/v1/auth/account/delete-code")
        assert resp.status_code == 401

    async def test_delete_requires_login(self, client):
        resp = await client.post("/api/v1/auth/account/delete", json={"code": "123456"})
        assert resp.status_code == 401

    async def test_logged_in_user_can_delete_account_and_cookie_is_cleared(self, client):
        client.cookies.set(settings.AUTH_COOKIE_NAME, _login_cookie(client))

        sent = await client.post("/api/v1/auth/account/delete-code")
        assert sent.status_code == 200
        code = client.harness.last_code()

        resp = await client.post("/api/v1/auth/account/delete", json={"code": code})
        assert resp.status_code == 200
        assert client.alice_id not in client.harness.repo.users
        assert settings.AUTH_COOKIE_NAME in resp.headers.get("set-cookie", "")


# ═══════════════════════════════════════════════════════════════
# 4. 注销后的旧 cookie
# ═══════════════════════════════════════════════════════════════

class TestStaleCookieAfterDeletion:

    async def test_creating_session_for_deleted_account_is_401_not_500(self):
        class DeletedAccountSessionRepo:
            async def create(self, conn, user_id, title):
                # 账号已删除，sessions.user_id 外键不再成立
                raise asyncpg.ForeignKeyViolationError("sessions_user_id_fkey")

        class Db:
            def transaction(self):
                return _noop()

        service = SessionService(db=Db(), repo=DeletedAccountSessionRepo(), default_username="demo_user")
        with pytest.raises(AppException) as exc:
            await service.create_session(None, user_id=str(uuid.uuid4()))
        assert exc.value.code == 401
