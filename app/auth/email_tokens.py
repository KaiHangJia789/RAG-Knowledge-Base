"""
邮件一次性令牌（验证邮箱、将来的找回密码）。

数据库只保存 SHA-256 摘要；明文令牌只出现在邮件里。
"""
import hashlib
import secrets


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """返回 (发给用户的明文令牌, 存入数据库的摘要)"""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)
