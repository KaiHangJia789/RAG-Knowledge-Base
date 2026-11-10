"""
账号服务：注册、邮箱验证、重发验证邮件、登录校验、找回密码、注销账号。

安全约定：
- 注册、重发验证、找回密码对外的响应与「邮箱是否已存在」无关（不做账号枚举）；
- 登录时「用户不存在」与「密码错误」走同一异常，并且都会执行一次 bcrypt 校验（不做计时枚举）；
- 验证令牌一次性、24 小时有效，数据库只存摘要；
- 验证码（找回密码、注销账号）6 位、10 分钟有效、单个验证码最多错 5 次，数据库只存 HMAC 摘要；
- 邮件发送在数据库事务提交之后进行。注册/找回时发送失败不回滚，用户可以重新发送；
- 注销账号：先校验验证码，事务内删除用户（级联删除其文档与会话），提交后再清理向量索引与物理文件。
"""
import functools
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import asyncpg

from app.auth.email_codes import code_digest, new_code
from app.auth.email_tokens import hash_token, new_token
from app.auth.passwords import hash_password, verify_password
from app.auth.validation import is_valid_email, normalize_email, validate_email, validate_password
from app.config import settings
from app.db.repositories.account_repo import AccountRepository, DuplicateAccountError
from app.exceptions.handlers import AppException
from app.mail.sender import LogMailSender, MailSendError, MailSender
from app.mail.templates import code_mail, verification_mail

logger = logging.getLogger("rag_api.account")


class InvalidCredentialsError(AppException):
    def __init__(self) -> None:
        super().__init__(message="用户名或密码错误", code=401, detail="用户名或密码错误")


class EmailNotVerifiedError(AppException):
    def __init__(self) -> None:
        super().__init__(
            message="邮箱尚未验证",
            code=403,
            detail="请查收验证邮件并点击链接；如未收到，可在登录页重新发送",
        )


class InvalidTokenError(AppException):
    def __init__(self) -> None:
        super().__init__(message="验证链接无效或已过期", code=400, detail="请重新获取验证邮件")


class InvalidCodeError(AppException):
    """验证码错误、已过期、已使用，或错误次数已达上限（三者对外不作区分）"""

    def __init__(self) -> None:
        super().__init__(
            message="验证码无效或已过期",
            code=400,
            detail="验证码无效或已过期，请重新获取",
        )


class AccountNotFoundError(AppException):
    """已登录的 cookie 对应的账号已不存在（例如刚被注销）"""

    def __init__(self) -> None:
        super().__init__(message="账号不存在", code=401, detail="请重新登录")


class SharedCorpusAccountError(AppException):
    """账号持有共享语料，注销会把所有用户可见的文档一并删除"""

    def __init__(self) -> None:
        super().__init__(
            message="该账号持有共享语料（所有用户可见），不能注销",
            code=409,
            detail="该账号持有共享语料（所有用户可见），不能注销",
        )


class CodeDeliveryError(AppException):
    def __init__(self) -> None:
        super().__init__(message="验证码发送失败", code=503, detail="验证码邮件发送失败，请稍后重试")


class SchemaOutdatedError(AppException):
    """数据库缺少注册功能所需的表或列（未执行迁移 007 / 008）"""

    def __init__(self) -> None:
        super().__init__(
            message="服务未就绪",
            code=503,
            detail=(
                "数据库结构未更新：缺少 users.email_verified_at、email_tokens 或 email_codes。"
                "请依次执行迁移 app/db/migrations/007_email_verification.sql 与 "
                "008_email_codes.sql 后重试"
            ),
        )


def _schema_guard(fn):
    """把「列/表不存在」转换为可操作的 503，其余异常原样抛出"""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError) as e:
            logger.error("账号功能所需的数据库结构缺失: %s", e)
            raise SchemaOutdatedError() from e

    return wrapper


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    username: str


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """查无此用户时用它做一次校验，使耗时与密码错误一致"""
    return hash_password("dummy-password-for-timing-only1")


class AccountService:

    def __init__(
        self,
        db,
        repo: AccountRepository | None = None,
        mailer: MailSender | None = None,
        *,
        clock=None,
        index=None,
        storage=None,
        doc_cache=None,
    ):
        self.db = db
        self.repo = repo or AccountRepository()
        self.mailer = mailer or LogMailSender()
        self._clock = clock or (lambda: datetime.now(UTC))
        # 注销账号时需要清理的外部状态：向量索引、物理文件、文档缓存
        self.index = index
        self.storage = storage
        self.doc_cache = doc_cache

    def _now(self) -> datetime:
        return self._clock()

    async def _issue_verification(self, conn, user_id) -> str:
        """作废旧的验证令牌并签发新的，返回明文令牌（只用于邮件）"""
        now = self._now()
        await self.repo.invalidate_tokens(conn, user_id, "verify", now)
        raw, digest = new_token()
        await self.repo.create_token(
            conn, user_id, "verify", digest,
            now + timedelta(hours=settings.EMAIL_VERIFY_TTL_HOURS),
        )
        return raw

    async def _deliver_verification(self, email: str, raw_token: str) -> None:
        """
        在数据库事务提交之后发送。这里吞掉所有异常：账号已经创建，
        邮件失败不应让注册接口返回 500。用户可以在登录页重新发送。
        """
        link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/verify?token={raw_token}"
        try:
            await self.mailer.send(verification_mail(email, link))
        except MailSendError as e:
            logger.error("验证邮件发送失败: %s", e)
        except Exception:
            logger.exception("验证邮件发送出现未预期的错误")

    # ═══════════════════════════════════════════════════════════
    # 注册
    # ═══════════════════════════════════════════════════════════

    @_schema_guard
    async def register(self, email: str, password: str) -> None:
        email = normalize_email(email)
        validate_email(email)
        validate_password(password)

        raw: str | None = None
        try:
            async with self.db.transaction() as conn:
                existing = await self.repo.find_by_email(conn, email)
                if existing is None:
                    user = await self.repo.create_user(
                        conn, username=email, email=email, password_hash=hash_password(password)
                    )
                    raw = await self._issue_verification(conn, user["id"])
                elif existing["email_verified_at"] is None:
                    # 未验证的旧账号：重新发送验证邮件（沿用原密码，本次输入的密码不覆盖）
                    raw = await self._issue_verification(conn, existing["id"])
                else:
                    logger.info("注册请求的邮箱已存在且已验证，未发送邮件")
        except DuplicateAccountError:
            # 并发注册同一邮箱：另一请求已创建账号，对外保持相同的响应
            logger.info("并发注册同一邮箱，另一请求已创建账号")
            return

        if raw is not None:
            await self._deliver_verification(email, raw)

    # ═══════════════════════════════════════════════════════════
    # 验证与重发
    # ═══════════════════════════════════════════════════════════

    @_schema_guard
    async def verify_email(self, raw_token: str) -> None:
        digest = hash_token(raw_token)
        now = self._now()
        async with self.db.transaction() as conn:
            row = await self.repo.consume_token(conn, digest, "verify", now)
            if row is None:
                raise InvalidTokenError()
            await self.repo.mark_verified(conn, row["user_id"], now)

    @_schema_guard
    async def resend_verification(self, email: str) -> None:
        """对外不区分邮箱是否存在、是否已验证：只有未验证的账号才会收到新邮件"""
        email = normalize_email(email)
        if not is_valid_email(email):
            return

        raw: str | None = None
        async with self.db.transaction() as conn:
            user = await self.repo.find_by_email(conn, email)
            if user is not None and user["email_verified_at"] is None:
                raw = await self._issue_verification(conn, user["id"])
        if raw is not None:
            await self._deliver_verification(email, raw)

    # ═══════════════════════════════════════════════════════════
    # 验证码（找回密码、注销账号共用）
    # ═══════════════════════════════════════════════════════════

    async def _issue_code(self, conn, user_id, purpose: str) -> str:
        """作废该用途下旧的验证码并签发新的，返回明文验证码（只用于邮件）"""
        now = self._now()
        await self.repo.invalidate_codes(conn, user_id, purpose, now)
        code = new_code()
        await self.repo.create_code(
            conn, user_id, purpose, code_digest(purpose, user_id, code),
            now + timedelta(minutes=settings.EMAIL_CODE_TTL_MINUTES),
        )
        return code

    async def _consume_code(self, conn, user_id, purpose: str, code: str) -> bool:
        """
        在事务内校验验证码。每次尝试都会计数并随事务提交，
        因此调用方不能在事务内抛异常（否则计数会回滚，错误次数无上限）。
        """
        now = self._now()
        row = await self.repo.lock_active_code(conn, user_id, purpose, now)
        if row is None or row["attempts"] >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            return False
        await self.repo.bump_code_attempts(conn, row["id"])
        if not hmac.compare_digest(row["code_hash"], code_digest(purpose, user_id, code)):
            return False
        await self.repo.mark_code_used(conn, row["id"], now)
        return True

    async def _deliver_code(self, email: str, purpose: str, code: str, *, strict: bool) -> None:
        """
        strict=True（已登录用户的注销）：发送失败要告诉用户，否则他会一直等邮件。
        strict=False（找回密码）：对外响应与账号是否存在无关，失败只记日志。
        """
        try:
            await self.mailer.send(code_mail(email, purpose=purpose, code=code))
        except Exception as e:
            logger.error("验证码邮件发送失败（%s）: %s", purpose, e)
            if strict:
                raise CodeDeliveryError() from e

    # ═══════════════════════════════════════════════════════════
    # 找回密码
    # ═══════════════════════════════════════════════════════════

    @_schema_guard
    async def request_password_reset(self, email: str) -> None:
        """对外不区分邮箱是否存在：只有已注册的邮箱才会收到验证码"""
        email = normalize_email(email)
        if not is_valid_email(email):
            return

        code: str | None = None
        async with self.db.transaction() as conn:
            user = await self.repo.find_by_email(conn, email)
            if user is not None:
                code = await self._issue_code(conn, user["id"], "reset")
        if code is not None:
            await self._deliver_code(email, "reset", code, strict=False)

    @_schema_guard
    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        email = normalize_email(email)
        validate_password(new_password)

        ok = False
        now = self._now()
        async with self.db.transaction() as conn:
            user = await self.repo.find_by_email(conn, email)
            if user is not None:
                ok = await self._consume_code(conn, user["id"], "reset", code)
                if ok:
                    await self.repo.update_password(
                        conn, user["id"], hash_password(new_password), now
                    )
                    # 能收到邮件并输入验证码，即证明了邮箱归属，顺带完成验证
                    await self.repo.mark_verified(conn, user["id"], now)
        if not ok:
            raise InvalidCodeError()

    # ═══════════════════════════════════════════════════════════
    # 注销账号（需已登录，并用发往本人邮箱的验证码确认）
    # ═══════════════════════════════════════════════════════════

    async def _ensure_deletable(self, conn, user_id) -> None:
        if await self.repo.owns_shared_documents(conn, user_id):
            raise SharedCorpusAccountError()

    @_schema_guard
    async def request_account_deletion(self, user_id: str) -> None:
        async with self.db.transaction() as conn:
            user = await self.repo.find_by_id(conn, user_id)
            if user is None:
                raise AccountNotFoundError()
            await self._ensure_deletable(conn, user_id)
            code = await self._issue_code(conn, user_id, "delete")
        await self._deliver_code(user["email"], "delete", code, strict=True)

    @_schema_guard
    async def delete_account(self, user_id: str, code: str) -> None:
        ok = False
        purged: list = []
        async with self.db.transaction() as conn:
            user = await self.repo.find_by_id(conn, user_id)
            if user is None:
                raise AccountNotFoundError()
            await self._ensure_deletable(conn, user_id)
            ok = await self._consume_code(conn, user_id, "delete", code)
            if ok:
                purged = await self.repo.list_documents_of(conn, user_id)
                await self.repo.delete_user(conn, user_id)
        if not ok:
            raise InvalidCodeError()

        # 事务已提交，用户与文档记录已删除。下面清理的是事务之外的状态；
        # 单项失败只记日志，不影响注销结果（残留需要人工处理）
        await self._purge_external_state(purged)

    async def _purge_external_state(self, docs) -> None:
        for doc in docs:
            doc_id = str(doc["id"])
            if self.index is not None:
                try:
                    self.index.remove_document(doc_id)
                except Exception:
                    logger.exception("注销账号时移除向量失败: %s", doc_id)
            if self.storage is not None:
                try:
                    self.storage.delete(doc["storage_path"])
                except OSError as e:
                    logger.warning("注销账号时物理文件删除失败: %s — %s", doc["storage_path"], e)
            if self.doc_cache is not None:
                try:
                    await self.doc_cache.invalidate(doc_id)
                except Exception:
                    logger.warning("注销账号时缓存失效失败: %s", doc_id)

    # ═══════════════════════════════════════════════════════════
    # 登录校验
    # ═══════════════════════════════════════════════════════════

    @_schema_guard
    async def authenticate(self, identifier: str, password: str) -> AuthenticatedUser:
        ident = normalize_email(identifier)
        async with self.db.pool.acquire() as conn:
            row = await self.repo.find_by_identifier(conn, ident)

        stored = row["password_hash"] if row is not None else _dummy_hash()
        password_ok = verify_password(password, stored)
        if row is None or not password_ok:
            raise InvalidCredentialsError()
        if row["email_verified_at"] is None:
            raise EmailNotVerifiedError()
        return AuthenticatedUser(user_id=str(row["id"]), username=row["username"])
