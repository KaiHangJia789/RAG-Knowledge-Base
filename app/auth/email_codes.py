"""
邮箱验证码（找回密码、注销账号）：6 位数字，明文只出现在邮件里。

数据库保存的是 HMAC 摘要而不是 SHA-256：验证码只有 10^6 种可能，
普通哈希一旦数据库泄露就能离线枚举，HMAC 需要服务端密钥才能验证。
"""
import secrets

from app.auth.tokens import keyed_hash

CODE_LENGTH = 6


def new_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def code_digest(purpose: str, user_id, code: str) -> str:
    # 把用途与用户一起放进摘要：同一个码在不同用途、不同用户之间不可互用
    return keyed_hash(f"{purpose}|{user_id}|{code}")
