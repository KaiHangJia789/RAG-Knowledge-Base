"""注册输入校验：邮箱格式与密码强度"""
import re

from app.config import settings
from app.exceptions.handlers import AppException

# 新账号的 username 直接使用邮箱，而 users.username 是 VARCHAR(64)，所以邮箱上限 64 字符
MAX_EMAIL_LENGTH = 64
# bcrypt 只处理前 72 字节，且 bcrypt>=5 对更长的输入直接抛 ValueError（会变成 500）。
# 必须按 UTF-8 字节计算：一个中文字符占 3 字节。
MAX_PASSWORD_BYTES = 72
_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


class AccountValidationError(AppException):
    def __init__(self, reason: str) -> None:
        super().__init__(message="输入不符合要求", code=400, detail=reason)


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def is_valid_email(email: str) -> bool:
    return len(email) <= MAX_EMAIL_LENGTH and bool(_EMAIL_RE.match(email))


def validate_email(email: str) -> None:
    if not is_valid_email(email):
        raise AccountValidationError("邮箱格式不正确（最长 64 个字符）")


def validate_password(password: str) -> None:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise AccountValidationError(f"密码至少 {settings.PASSWORD_MIN_LENGTH} 位")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AccountValidationError(
            f"密码过长：最多 {MAX_PASSWORD_BYTES} 个字节（英文约 72 位，中文约 24 个字）"
        )
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AccountValidationError("密码需同时包含字母和数字")
