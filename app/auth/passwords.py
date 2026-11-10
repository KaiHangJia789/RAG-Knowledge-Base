"""密码哈希（bcrypt）。与 users.password_hash 列的格式（$2b$...）兼容"""
import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # 哈希格式不合法（例如被写成明文）：视为校验失败，而不是 500
        return False
