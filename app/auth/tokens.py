"""
登录令牌：HMAC-SHA256 签名的 cookie 值，只用标准库。

格式：base64url(payload) + "." + hex(hmac)
payload = "<user_id>|<过期时间戳>|<username>"

安全要点：
- 签名比较用 hmac.compare_digest，防止计时攻击；
- 过期时间与用户标识都在签名内，篡改任一字段都会导致签名失效；
- user_id 放进令牌，业务请求无需再查库即可确定归属；
- 未配置 AUTH_SECRET_KEY 时使用进程内随机密钥（重启即失效，仅作安全兜底）。
"""
import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger("rag_api.auth")

_fallback_secret: str | None = None


def _secret() -> bytes:
    global _fallback_secret
    if settings.AUTH_SECRET_KEY:
        return settings.AUTH_SECRET_KEY.encode()
    if _fallback_secret is None:
        _fallback_secret = secrets.token_urlsafe(32)
        logger.warning("未设置 AUTH_SECRET_KEY，已生成临时密钥：重启后需要重新登录")
    return _fallback_secret.encode()


def _sign(payload: bytes) -> str:
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def keyed_hash(message: str) -> str:
    """用服务端密钥做 HMAC，供数据库存储短验证码的摘要（离线无法枚举）"""
    return _sign(message.encode())


@dataclass(frozen=True)
class Session:
    user_id: str
    username: str
    expires_at: int


def issue(user_id: str, username: str, *, now: float | None = None) -> str:
    """签发令牌。过期时间 = now + AUTH_TOKEN_TTL_HOURS"""
    issued = int(now if now is not None else time.time())
    expires_at = issued + settings.AUTH_TOKEN_TTL_HOURS * 3600
    payload = f"{user_id}|{expires_at}|{username}".encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_sign(payload)}"


def verify(token: str | None, *, now: float | None = None) -> Session | None:
    """校验令牌；无效、被篡改或已过期均返回 None，不抛异常"""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(_sign(payload), sig):
        return None
    try:
        user_id, exp_raw, username = payload.decode().split("|", 2)
        expires_at = int(exp_raw)
    except (UnicodeDecodeError, ValueError):
        return None
    current = now if now is not None else time.time()
    if current >= expires_at:
        return None
    return Session(user_id=user_id, username=username, expires_at=expires_at)
