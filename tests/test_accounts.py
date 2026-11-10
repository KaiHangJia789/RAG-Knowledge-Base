"""
注册与邮箱验证测试

1. 服务层：注册、验证、重发、登录校验（内存仓储 + 假邮件发送）
2. DirectMail：参数完整性、签名格式、错误响应处理（假 HTTP 打开器，不访问网络）
3. HTTP：注册的统一响应、限流、验证接口、未验证邮箱不能登录

真实 PostgreSQL 上的 SQL（唯一约束、原子消费令牌）需在服务器上做一次端到端检查。
"""
import io
import re
import urllib.error
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.email_tokens import hash_token
from app.auth.passwords import hash_password, verify_password
from app.auth.rate_limit import SlidingWindowLimiter
from app.auth.validation import AccountValidationError
from app.config import settings
from app.db.repositories.account_repo import DuplicateAccountError
from app.mail.sender import DirectMailSender, MailMessage, MailSendError
from app.services.account_service import (
    AccountService,
    AuthenticatedUser,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)

PASSWORD = "good-pass-123"
PW_HASH = hash_password(PASSWORD)
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


# ═══════════════════════════════════════════════════════════════
# 测试替身
# ═══════════════════════════════════════════════════════════════

class FakeRepo:
    """与 AccountRepository 同名同语义的内存实现（conn 参数忽略）"""

    def __init__(self, users=None):
        self.users: dict[str, dict] = {}
        self.tokens: list[dict] = []
        for u in users or []:
            self.users[str(u["id"])] = dict(u)

    async def find_by_email(self, conn, email):
        return next((dict(u) for u in self.users.values() if u["email"] == email), None)

    async def find_by_identifier(self, conn, identifier):
        return next(
            (dict(u) for u in self.users.values() if identifier in (u["username"], u["email"])),
            None,
        )

    async def create_user(self, conn, *, username, email, password_hash):
        if any(u["email"] == email or u["username"] == username for u in self.users.values()):
            raise DuplicateAccountError(email)
        uid = str(uuid.uuid4())
        row = {"id": uid, "username": username, "email": email,
               "password_hash": password_hash, "email_verified_at": None}
        self.users[uid] = row
        return dict(row)

    async def mark_verified(self, conn, user_id, at):
        u = self.users[str(user_id)]
        if u["email_verified_at"] is None:
            u["email_verified_at"] = at

    async def create_token(self, conn, user_id, purpose, token_hash, expires_at):
        self.tokens.append({"user_id": str(user_id), "purpose": purpose,
                            "token_hash": token_hash, "expires_at": expires_at, "used_at": None})

    async def invalidate_tokens(self, conn, user_id, purpose, at):
        for t in self.tokens:
            if t["user_id"] == str(user_id) and t["purpose"] == purpose and t["used_at"] is None:
                t["used_at"] = at

    async def consume_token(self, conn, token_hash, purpose, at):
        for t in self.tokens:
            if (t["token_hash"] == token_hash and t["purpose"] == purpose
                    and t["used_at"] is None and t["expires_at"] > at):
                t["used_at"] = at
                return {"user_id": t["user_id"]}
        return None


class FakeMailer:
    def __init__(self):
        self.sent: list[MailMessage] = []
        self.fail = False

    async def send(self, message):
        if self.fail:
            raise MailSendError("模拟发送失败")
        self.sent.append(message)


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
    clock: dict = field(default_factory=lambda: {"now": T0})

    def advance(self, **kwargs):
        self.clock["now"] += timedelta(**kwargs)

    def last_token(self) -> str:
        """从最近一封验证邮件的链接中取出明文令牌"""
        match = re.search(r"token=([\w\-]+)", self.mailer.sent[-1].html)
        assert match, "邮件中没有验证链接"
        return match.group(1)


def seeded_user(user_id, username, email, password_hash, *, verified=True):
    return {"id": user_id, "username": username, "email": email,
            "password_hash": password_hash,
            "email_verified_at": T0 if verified else None}


def build_service(users=None, *, mailer=None) -> Harness:
    repo = FakeRepo(users)
    mailer = mailer or FakeMailer()
    harness = Harness(service=None, repo=repo, mailer=mailer)
    harness.service = AccountService(
        db=FakeDb(), repo=repo, mailer=mailer, clock=lambda: harness.clock["now"]
    )
    return harness


@pytest.fixture(autouse=True)
def _account_settings(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://suming.work")
    monkeypatch.setattr(settings, "EMAIL_VERIFY_TTL_HOURS", 24)
    monkeypatch.setattr(settings, "PASSWORD_MIN_LENGTH", 10)


@pytest.fixture
def h():
    return build_service()


# ═══════════════════════════════════════════════════════════════
# 1. 注册
# ═══════════════════════════════════════════════════════════════

class TestRegister:

    async def test_creates_unverified_user_and_sends_mail(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        user = next(iter(h.repo.users.values()))
        assert user["email"] == "alice@example.com"
        assert user["email_verified_at"] is None
        assert len(h.mailer.sent) == 1
        assert h.mailer.sent[0].to == "alice@example.com"

    async def test_password_is_stored_as_bcrypt_hash(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        user = next(iter(h.repo.users.values()))
        assert user["password_hash"] != "abcdef1234"
        assert verify_password("abcdef1234", user["password_hash"])

    async def test_stored_token_is_hash_not_plaintext(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        raw = h.last_token()
        stored = h.repo.tokens[0]["token_hash"]
        assert stored == hash_token(raw)
        assert raw not in stored

    async def test_mail_link_uses_public_base_url(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        assert "https://suming.work/verify?token=" in h.mailer.sent[0].html

    async def test_email_is_normalized(self, h):
        await h.service.register("  Alice@Example.COM ", "abcdef1234")
        assert next(iter(h.repo.users.values()))["email"] == "alice@example.com"

    async def test_existing_verified_email_sends_nothing(self):
        h = build_service([seeded_user(str(uuid.uuid4()), "bob@example.com", "bob@example.com", PW_HASH)])
        await h.service.register("bob@example.com", "abcdef1234")
        assert h.mailer.sent == []
        assert len(h.repo.users) == 1

    async def test_existing_unverified_email_resends_and_invalidates_old_token(self):
        h = build_service([seeded_user(str(uuid.uuid4()), "c@example.com", "c@example.com", PW_HASH, verified=False)])
        await h.service.register("c@example.com", "abcdef1234")
        first = h.last_token()
        await h.service.register("c@example.com", "abcdef1234")
        second = h.last_token()
        assert first != second
        assert len(h.mailer.sent) == 2
        with pytest.raises(InvalidTokenError):
            await h.service.verify_email(first)   # 旧令牌已作废

    async def test_mail_failure_does_not_undo_registration(self):
        mailer = FakeMailer()
        mailer.fail = True
        h = build_service(mailer=mailer)
        await h.service.register("alice@example.com", "abcdef1234")
        assert len(h.repo.users) == 1
        assert h.mailer.sent == []

    async def test_duplicate_race_is_swallowed(self, h, monkeypatch):
        async def boom(conn, **kw):
            raise DuplicateAccountError("race")
        monkeypatch.setattr(h.repo, "create_user", boom)
        await h.service.register("race@example.com", "abcdef1234")   # 不抛异常
        assert h.mailer.sent == []

    @pytest.mark.parametrize("bad_email", ["no-at-sign", "a@b", "x" * 60 + "@example.com"])
    async def test_invalid_email_rejected(self, h, bad_email):
        with pytest.raises(AccountValidationError):
            await h.service.register(bad_email, "abcdef1234")

    @pytest.mark.parametrize("bad_password", ["short1", "abcdefghijk", "1234567890123"])
    async def test_weak_password_rejected(self, h, bad_password):
        with pytest.raises(AccountValidationError):
            await h.service.register("alice@example.com", bad_password)


# ═══════════════════════════════════════════════════════════════
# 2. 验证
# ═══════════════════════════════════════════════════════════════

class TestVerify:

    async def test_valid_token_marks_verified_and_allows_login(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        await h.service.verify_email(h.last_token())
        user = await h.service.authenticate("alice@example.com", "abcdef1234")
        assert user.username == "alice@example.com"

    async def test_token_is_single_use(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        raw = h.last_token()
        await h.service.verify_email(raw)
        with pytest.raises(InvalidTokenError):
            await h.service.verify_email(raw)

    async def test_expired_token_is_rejected(self, h):
        await h.service.register("alice@example.com", "abcdef1234")
        raw = h.last_token()
        h.advance(hours=25)
        with pytest.raises(InvalidTokenError):
            await h.service.verify_email(raw)

    async def test_unknown_token_is_rejected(self, h):
        with pytest.raises(InvalidTokenError):
            await h.service.verify_email("not-a-real-token-value")


# ═══════════════════════════════════════════════════════════════
# 3. 重发
# ═══════════════════════════════════════════════════════════════

class TestResend:

    async def test_unknown_email_sends_nothing_and_does_not_raise(self, h):
        await h.service.resend_verification("nobody@example.com")
        assert h.mailer.sent == []

    async def test_verified_email_sends_nothing(self):
        h = build_service([seeded_user(str(uuid.uuid4()), "d@example.com", "d@example.com", PW_HASH)])
        await h.service.resend_verification("d@example.com")
        assert h.mailer.sent == []

    async def test_unverified_email_gets_a_new_working_link(self):
        h = build_service([seeded_user(str(uuid.uuid4()), "e@example.com", "e@example.com", PW_HASH, verified=False)])
        await h.service.resend_verification("e@example.com")
        await h.service.verify_email(h.last_token())
        assert (await h.service.authenticate("e@example.com", PASSWORD)).username == "e@example.com"


# ═══════════════════════════════════════════════════════════════
# 4. 登录校验
# ═══════════════════════════════════════════════════════════════

class TestAuthenticate:

    async def test_login_by_email_and_by_username(self):
        uid = str(uuid.uuid4())
        h = build_service([seeded_user(uid, "demo_user", "demo@example.com", PW_HASH)])
        by_email = await h.service.authenticate("demo@example.com", PASSWORD)
        by_name = await h.service.authenticate("demo_user", PASSWORD)
        assert by_email.user_id == by_name.user_id == uid

    async def test_wrong_password_and_unknown_user_raise_same_error(self):
        h = build_service([seeded_user(str(uuid.uuid4()), "f@example.com", "f@example.com", PW_HASH)])
        with pytest.raises(InvalidCredentialsError):
            await h.service.authenticate("f@example.com", "wrong-password-1")
        with pytest.raises(InvalidCredentialsError):
            await h.service.authenticate("ghost@example.com", "wrong-password-1")

    async def test_unverified_email_blocked_even_with_correct_password(self):
        h = build_service([seeded_user(str(uuid.uuid4()), "g@example.com", "g@example.com", PW_HASH, verified=False)])
        with pytest.raises(EmailNotVerifiedError):
            await h.service.authenticate("g@example.com", PASSWORD)


# ═══════════════════════════════════════════════════════════════
# 5. DirectMail
# ═══════════════════════════════════════════════════════════════

class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _sender(opener):
    return DirectMailSender(
        access_key_id="AK-TEST", access_key_secret="SECRET-TEST",
        account_name="noreply@mail.example.com", endpoint="https://dm.aliyuncs.com",
        from_alias="RAG 知识库", opener=opener,
    )


class TestDirectMail:

    def test_rfc3986_encoding(self):
        from app.mail.sender import _pct
        assert _pct("a b*~+") == "a%20b%2A~%2B"

    def test_params_contain_required_fields(self):
        params = _sender(None).build_params(MailMessage("to@example.com", "主题", "<p>x</p>"))
        for key in ("Action", "AccountName", "ToAddress", "Subject", "HtmlBody",
                    "AccessKeyId", "SignatureMethod", "SignatureVersion", "Timestamp",
                    "SignatureNonce", "Version", "Format"):
            assert key in params
        assert params["Action"] == "SingleSendMail"
        assert params["AddressType"] == "1"
        assert "Signature" not in params

    def test_signature_is_base64_hmac_sha1_over_sorted_canonical_string(self):
        import base64, hashlib, hmac
        from app.mail.sender import _pct
        sender = _sender(None)
        params = sender.build_params(MailMessage("to@example.com", "s", "h"),
                                     nonce="n1", timestamp="2026-11-01T12:00:00Z")
        canonical = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items()))
        to_sign = f"POST&%2F&{_pct(canonical)}"
        expected = base64.b64encode(
            hmac.new(b"SECRET-TEST&", to_sign.encode(), hashlib.sha1).digest()
        ).decode()
        assert sender.sign(params) == expected

    async def test_success_response_is_accepted(self):
        seen = {}

        def opener(req, timeout):
            seen["body"] = req.data.decode()
            return _FakeResponse(b'{"RequestId":"abc"}')

        await _sender(opener).send(MailMessage("to@example.com", "s", "h"))
        assert "Action=SingleSendMail" in seen["body"]
        assert "Signature=" in seen["body"]
        assert "SECRET-TEST" not in seen["body"]   # 密钥只用于签名，不出现在请求体

    async def test_api_error_is_raised_as_mail_send_error(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(
                req.full_url, 400, "Bad Request", {},
                io.BytesIO('{"Code":"InvalidAccountName","Message":"发信地址未验证"}'.encode()),
            )

        with pytest.raises(MailSendError, match="InvalidAccountName"):
            await _sender(opener).send(MailMessage("to@example.com", "s", "h"))

    async def test_missing_credentials_raise_before_network(self):
        sender = DirectMailSender(access_key_id="", access_key_secret="", account_name="",
                                  endpoint="https://dm.aliyuncs.com", from_alias="x",
                                  opener=lambda *a, **k: pytest.fail("不应发起网络请求"))
        with pytest.raises(MailSendError):
            await sender.send(MailMessage("to@example.com", "s", "h"))


# ═══════════════════════════════════════════════════════════════
# 6. HTTP
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
async def http(h):
    from app.dependencies.auth import get_account_service
    from app.main import app

    app.dependency_overrides[get_account_service] = lambda: h.service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_account_service, None)


def _ip(headers=None):
    """每个用例使用独立 IP，避免进程内限流计数互相影响"""
    return {"X-Real-IP": f"198.51.100.{uuid.uuid4().int % 250}", **(headers or {})}


class TestRegisterHttp:

    async def test_register_response_is_generic(self, http, h):
        resp = await http.post("/api/v1/auth/register", json={"email": "h1@example.com", "password": "abcdef1234"}, headers=_ip())
        assert resp.status_code == 200
        assert "若该邮箱可用" in resp.json()["message"]
        assert len(h.mailer.sent) == 1

    async def test_existing_email_gets_identical_response(self, http):
        body = {"email": "h2@example.com", "password": "abcdef1234"}
        first = await http.post("/api/v1/auth/register", json=body, headers=_ip())
        second = await http.post("/api/v1/auth/register", json=body, headers=_ip())
        assert first.status_code == second.status_code == 200
        assert first.json()["message"] == second.json()["message"]

    async def test_weak_password_returns_400(self, http):
        resp = await http.post("/api/v1/auth/register", json={"email": "h3@example.com", "password": "short"}, headers=_ip())
        assert resp.status_code == 400

    async def test_rate_limit_returns_429(self, http, monkeypatch):
        monkeypatch.setattr(settings, "REGISTER_MAX_PER_IP", 2)
        ip = {"X-Real-IP": f"203.0.113.{uuid.uuid4().int % 250}"}
        codes = []
        for i in range(3):
            resp = await http.post("/api/v1/auth/register",
                                   json={"email": f"rl{i}@example.com", "password": "abcdef1234"}, headers=ip)
            codes.append(resp.status_code)
        assert codes == [200, 200, 429]


class TestVerifyAndLoginHttp:

    async def test_verify_endpoint_then_login_succeeds(self, http, h):
        await http.post("/api/v1/auth/register", json={"email": "v1@example.com", "password": "abcdef1234"}, headers=_ip())
        token = h.last_token()
        assert (await http.post("/api/v1/auth/verify", json={"token": token})).status_code == 200
        login = await http.post("/api/v1/auth/login", json={"username": "v1@example.com", "password": "abcdef1234"}, headers=_ip())
        assert login.status_code == 200
        assert "rag_session" in login.headers["set-cookie"]

    async def test_reused_token_returns_400(self, http, h):
        await http.post("/api/v1/auth/register", json={"email": "v2@example.com", "password": "abcdef1234"}, headers=_ip())
        token = h.last_token()
        await http.post("/api/v1/auth/verify", json={"token": token})
        assert (await http.post("/api/v1/auth/verify", json={"token": token})).status_code == 400

    async def test_unverified_login_returns_403_with_guidance(self, http):
        await http.post("/api/v1/auth/register", json={"email": "v3@example.com", "password": "abcdef1234"}, headers=_ip())
        resp = await http.post("/api/v1/auth/login", json={"username": "v3@example.com", "password": "abcdef1234"}, headers=_ip())
        assert resp.status_code == 403
        assert "尚未验证" in resp.json()["message"]

    async def test_resend_is_generic_for_unknown_email(self, http):
        resp = await http.post("/api/v1/auth/resend-verification", json={"email": "nobody@example.com"}, headers=_ip())
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# 7. 回归：注册 500 的几个来源
# ═══════════════════════════════════════════════════════════════

class TestPasswordByteLimit:
    """bcrypt>=5 对超过 72 字节的密码抛 ValueError，曾导致注册返回 500"""

    async def test_long_chinese_password_is_rejected_as_400_not_500(self, h):
        # 30 个汉字 = 90 字节，字符数未超过旧上限却超过 bcrypt 上限
        with pytest.raises(AccountValidationError) as exc:
            await h.service.register("zh@example.com", "密码" * 15 + "a1")
        assert exc.value.code == 400
        assert "72 个字节" in exc.value.detail

    async def test_exactly_72_bytes_is_accepted(self, h):
        password = "a1" + "b" * 70
        assert len(password.encode()) == 72
        await h.service.register("edge@example.com", password)
        assert verify_password(password, next(iter(h.repo.users.values()))["password_hash"])


class TestSchemaOutdated:
    """未执行迁移 007 时，应返回可操作的 503，而不是通用 500"""

    async def test_missing_column_becomes_actionable_503(self, h, monkeypatch):
        import asyncpg

        async def missing(conn, email):
            raise asyncpg.UndefinedColumnError('column "email_verified_at" does not exist')

        monkeypatch.setattr(h.repo, "find_by_email", missing)
        from app.services.account_service import SchemaOutdatedError
        with pytest.raises(SchemaOutdatedError) as exc:
            await h.service.register("s@example.com", "abcdef1234")
        assert exc.value.code == 503
        assert "007_email_verification.sql" in exc.value.detail


class TestMailFailureNeverBreaksRegistration:

    async def test_unexpected_mailer_exception_still_returns_normally(self, h, monkeypatch):
        async def explode(message):
            raise RuntimeError("socket 超时")
        monkeypatch.setattr(h.mailer, "send", explode)

        await h.service.register("m@example.com", "abcdef1234")   # 不抛异常
        assert len(h.repo.users) == 1                               # 账号已创建

    async def test_socket_timeout_during_read_becomes_mail_send_error(self):
        import socket

        class TimingOutResponse:
            def read(self):
                raise socket.timeout("read timed out")
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False

        sender = _sender(lambda req, timeout: TimingOutResponse())
        with pytest.raises(MailSendError, match="请求失败"):
            await sender.send(MailMessage("to@example.com", "s", "h"))
