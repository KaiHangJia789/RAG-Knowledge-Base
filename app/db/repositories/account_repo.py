"""
AccountRepository — 账号、邮件令牌与验证码的数据访问（users + email_tokens + email_codes）。

conn 由 Service 通过事务上下文注入。
"""
import asyncpg


class DuplicateAccountError(Exception):
    """用户名或邮箱已存在（唯一约束冲突）"""


_USER_COLUMNS = "id, username, email, password_hash, email_verified_at"


class AccountRepository:

    async def find_by_id(self, conn: asyncpg.Connection, user_id):
        return await conn.fetchrow(f"SELECT {_USER_COLUMNS} FROM users WHERE id = $1", user_id)

    async def find_by_email(self, conn: asyncpg.Connection, email: str):
        return await conn.fetchrow(f"SELECT {_USER_COLUMNS} FROM users WHERE email = $1", email)

    async def find_by_identifier(self, conn: asyncpg.Connection, identifier: str):
        """登录标识：用户名或邮箱"""
        return await conn.fetchrow(
            f"SELECT {_USER_COLUMNS} FROM users WHERE username = $1 OR email = $1 LIMIT 1",
            identifier,
        )

    async def create_user(
        self, conn: asyncpg.Connection, *, username: str, email: str, password_hash: str
    ):
        try:
            return await conn.fetchrow(
                f"INSERT INTO users (username, email, password_hash) VALUES ($1, $2, $3) "
                f"RETURNING {_USER_COLUMNS}",
                username, email, password_hash,
            )
        except asyncpg.UniqueViolationError as e:
            raise DuplicateAccountError(str(e)) from e

    async def update_password(self, conn: asyncpg.Connection, user_id, password_hash: str, at) -> None:
        await conn.execute(
            "UPDATE users SET password_hash = $2, updated_at = $3 WHERE id = $1",
            user_id, password_hash, at,
        )

    async def delete_user(self, conn: asyncpg.Connection, user_id) -> None:
        """级联删除：documents → chunks，sessions，email_tokens，email_codes"""
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)

    async def owns_shared_documents(self, conn: asyncpg.Connection, user_id) -> bool:
        """共享语料（所有用户可见）归属于某账号时，该账号不能注销，否则会被级联删除"""
        return bool(await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM documents WHERE user_id = $1 AND is_shared)",
            user_id,
        ))

    async def list_documents_of(self, conn: asyncpg.Connection, user_id):
        """注销前读出文档的存储路径与 ID，用于事务提交后清理索引与磁盘文件"""
        return await conn.fetch(
            "SELECT id, storage_path FROM documents WHERE user_id = $1",
            user_id,
        )

    async def mark_verified(self, conn: asyncpg.Connection, user_id, at) -> None:
        await conn.execute(
            "UPDATE users SET email_verified_at = $2, updated_at = $2 "
            "WHERE id = $1 AND email_verified_at IS NULL",
            user_id, at,
        )

    async def create_token(
        self, conn: asyncpg.Connection, user_id, purpose: str, token_hash: str, expires_at
    ) -> None:
        await conn.execute(
            "INSERT INTO email_tokens (user_id, purpose, token_hash, expires_at) "
            "VALUES ($1, $2, $3, $4)",
            user_id, purpose, token_hash, expires_at,
        )

    async def invalidate_tokens(self, conn: asyncpg.Connection, user_id, purpose: str, at) -> None:
        """重发验证邮件时，作废该用户之前未使用的令牌"""
        await conn.execute(
            "UPDATE email_tokens SET used_at = $3 "
            "WHERE user_id = $1 AND purpose = $2 AND used_at IS NULL",
            user_id, purpose, at,
        )

    async def consume_token(self, conn: asyncpg.Connection, token_hash: str, purpose: str, at):
        """原子地标记令牌已使用；返回所属用户，令牌无效（不存在/已用/过期）时返回 None"""
        return await conn.fetchrow(
            "UPDATE email_tokens SET used_at = $3 "
            "WHERE token_hash = $1 AND purpose = $2 AND used_at IS NULL AND expires_at > $3 "
            "RETURNING user_id",
            token_hash, purpose, at,
        )

    # ── 验证码（找回密码、注销账号）──

    async def create_code(
        self, conn: asyncpg.Connection, user_id, purpose: str, code_hash: str, expires_at
    ) -> None:
        await conn.execute(
            "INSERT INTO email_codes (user_id, purpose, code_hash, expires_at) "
            "VALUES ($1, $2, $3, $4)",
            user_id, purpose, code_hash, expires_at,
        )

    async def invalidate_codes(self, conn: asyncpg.Connection, user_id, purpose: str, at) -> None:
        """重新发送验证码时，作废之前未使用的验证码"""
        await conn.execute(
            "UPDATE email_codes SET used_at = $3 "
            "WHERE user_id = $1 AND purpose = $2 AND used_at IS NULL",
            user_id, purpose, at,
        )

    async def lock_active_code(self, conn: asyncpg.Connection, user_id, purpose: str, at):
        """取出当前有效的验证码并加行锁，防止并发请求同时尝试而绕过错误次数上限"""
        return await conn.fetchrow(
            "SELECT id, code_hash, attempts FROM email_codes "
            "WHERE user_id = $1 AND purpose = $2 AND used_at IS NULL AND expires_at > $3 "
            "ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
            user_id, purpose, at,
        )

    async def bump_code_attempts(self, conn: asyncpg.Connection, code_id) -> None:
        await conn.execute(
            "UPDATE email_codes SET attempts = attempts + 1 WHERE id = $1",
            code_id,
        )

    async def mark_code_used(self, conn: asyncpg.Connection, code_id, at) -> None:
        await conn.execute(
            "UPDATE email_codes SET used_at = $2 WHERE id = $1",
            code_id, at,
        )
