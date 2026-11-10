"""
账号接口
POST /auth/register                — 注册（邮箱 + 密码），发送验证邮件
POST /auth/verify                  — 用邮件中的令牌完成邮箱验证（一次性）
POST /auth/resend-verification     — 重新发送验证邮件（对外不区分邮箱是否存在）
POST /auth/login                   — 登录（邮箱或用户名 + 密码），需已验证邮箱；成功后下发 httpOnly cookie
POST /auth/logout                  — 清除 cookie
GET  /auth/me                      — 当前登录用户（未登录返回 401）
POST /auth/password/forgot         — 找回密码：向注册邮箱发送 6 位验证码（对外不区分邮箱是否存在）
POST /auth/password/reset          — 找回密码：验证码 + 新密码
POST /auth/account/delete-code     — 注销账号：向本人邮箱发送验证码（需登录）
POST /auth/account/delete          — 注销账号：验证码确认，删除账号及其文档与会话（需登录）
"""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.auth import tokens
from app.auth.login_limiter import login_limiter
from app.auth.rate_limit import account_rate_limiter
from app.auth.validation import normalize_email
from app.config import settings
from app.dependencies.auth import AccountServiceDep
from app.dependencies.login import CurrentUserDep
from app.exceptions.handlers import AppException
from app.models.response import APIResponse
from app.services.account_service import InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["账号"])

REGISTER_MESSAGE = (
    "若该邮箱可用，我们已发送验证邮件。请在 24 小时内点击邮件中的链接完成验证；"
    "如未收到，可在登录页重新发送。"
)
FORGOT_MESSAGE = "若该邮箱已注册，我们已发送验证码。验证码 10 分钟内有效，请查收邮件。"

CODE_PATTERN = r"^\d{6}$"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, description="邮箱或用户名")
    password: str = Field(..., min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=256)


class VerifyRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=256)


class ResendRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., pattern=CODE_PATTERN, description="邮件中的 6 位数字验证码")
    new_password: str = Field(..., min_length=1, max_length=256)


class DeleteAccountRequest(BaseModel):
    code: str = Field(..., pattern=CODE_PATTERN, description="发往本人邮箱的 6 位数字验证码")


def client_ip(request: Request) -> str:
    """后端只监听 127.0.0.1，唯一入口是 nginx，它会设置 X-Real-IP。"""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _too_many(message: str) -> AppException:
    return AppException(message=message, code=429, detail=message)


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


@router.post("/register", summary="注册", response_model=APIResponse[dict])
async def register(body: RegisterRequest, request: Request, accounts: AccountServiceDep = None):
    ip = client_ip(request)
    if not account_rate_limiter.allow(
        f"register:ip:{ip}", settings.REGISTER_MAX_PER_IP, settings.REGISTER_WINDOW_SECONDS
    ):
        raise _too_many("注册请求过于频繁，请稍后再试")

    await accounts.register(body.email, body.password)
    # 无论邮箱是否已存在，响应都相同，避免枚举账号
    return APIResponse(code=200, message=REGISTER_MESSAGE, data={})


@router.post("/verify", summary="验证邮箱", response_model=APIResponse[dict])
async def verify(body: VerifyRequest, accounts: AccountServiceDep = None):
    await accounts.verify_email(body.token)
    return APIResponse(code=200, message="邮箱验证成功，请登录", data={})


@router.post("/resend-verification", summary="重发验证邮件", response_model=APIResponse[dict])
async def resend_verification(body: ResendRequest, request: Request, accounts: AccountServiceDep = None):
    email = normalize_email(body.email)
    ip = client_ip(request)
    if not account_rate_limiter.allow(
        f"resend:ip:{ip}", settings.REGISTER_MAX_PER_IP, settings.RESEND_WINDOW_SECONDS
    ):
        raise _too_many("请求过于频繁，请稍后再试")
    if not account_rate_limiter.allow(
        f"resend:email:{email}", settings.RESEND_MAX_PER_EMAIL, settings.RESEND_WINDOW_SECONDS
    ):
        raise _too_many("该邮箱重发次数已达上限，请稍后再试")

    await accounts.resend_verification(email)
    return APIResponse(
        code=200,
        message="若该邮箱尚未验证，我们已重新发送验证邮件，请查收。",
        data={},
    )


@router.post("/login", summary="登录", response_model=APIResponse[dict])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    accounts: AccountServiceDep = None,
):
    key = client_ip(request)
    if login_limiter.is_blocked(key):
        raise AppException(
            message="登录失败次数过多，请稍后再试",
            code=429,
            detail=f"{settings.AUTH_LOGIN_WINDOW_SECONDS // 60} 分钟内最多允许 {settings.AUTH_LOGIN_MAX_FAILURES} 次失败",
        )

    try:
        user = await accounts.authenticate(body.username, body.password)
    except InvalidCredentialsError:
        login_limiter.record_failure(key)
        raise

    login_limiter.reset(key)
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=tokens.issue(user.user_id, user.username),
        max_age=settings.AUTH_TOKEN_TTL_HOURS * 3600,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return APIResponse(code=200, message="登录成功", data={"username": user.username})


@router.post("/logout", summary="退出登录", response_model=APIResponse[dict])
async def logout(response: Response):
    _clear_session_cookie(response)
    return APIResponse(code=200, message="已退出登录", data={})


@router.get("/me", summary="当前登录用户", response_model=APIResponse[dict])
async def me(user: CurrentUserDep):
    return APIResponse(code=200, message="ok", data={"username": user.username, "user_id": user.user_id})


# ═══════════════════════════════════════════════════════════════
# 找回密码
# ═══════════════════════════════════════════════════════════════

@router.post("/password/forgot", summary="找回密码：发送验证码", response_model=APIResponse[dict])
async def forgot_password(body: ForgotPasswordRequest, request: Request, accounts: AccountServiceDep = None):
    email = normalize_email(body.email)
    ip = client_ip(request)
    # 限流按请求的邮箱字符串计数，不依赖账号是否存在，因此不会泄露注册情况
    if not account_rate_limiter.allow(
        f"forgot:ip:{ip}", settings.REGISTER_MAX_PER_IP, settings.RESEND_WINDOW_SECONDS
    ):
        raise _too_many("请求过于频繁，请稍后再试")
    if not account_rate_limiter.allow(
        f"forgot:email:{email}", settings.RESEND_MAX_PER_EMAIL, settings.RESEND_WINDOW_SECONDS
    ):
        raise _too_many("该邮箱验证码发送次数已达上限，请稍后再试")

    await accounts.request_password_reset(email)
    return APIResponse(code=200, message=FORGOT_MESSAGE, data={})


@router.post("/password/reset", summary="找回密码：设置新密码", response_model=APIResponse[dict])
async def reset_password(body: ResetPasswordRequest, request: Request, accounts: AccountServiceDep = None):
    ip = client_ip(request)
    # 每个验证码最多 5 次尝试，这里再限制单 IP 的提交次数，减缓多邮箱轮换的撞库
    if not account_rate_limiter.allow(
        f"reset:ip:{ip}", settings.REGISTER_MAX_PER_IP, settings.REGISTER_WINDOW_SECONDS
    ):
        raise _too_many("尝试次数过多，请稍后再试")

    await accounts.reset_password(body.email, body.code, body.new_password)
    return APIResponse(code=200, message="密码已重置，请使用新密码登录", data={})


# ═══════════════════════════════════════════════════════════════
# 注销账号（需登录）
# ═══════════════════════════════════════════════════════════════

@router.post("/account/delete-code", summary="注销账号：发送验证码", response_model=APIResponse[dict])
async def request_delete_code(user: CurrentUserDep, accounts: AccountServiceDep = None):
    if not account_rate_limiter.allow(
        f"delete-code:user:{user.user_id}", settings.RESEND_MAX_PER_EMAIL, settings.RESEND_WINDOW_SECONDS
    ):
        raise _too_many("验证码发送次数已达上限，请稍后再试")

    await accounts.request_account_deletion(user.user_id)
    return APIResponse(code=200, message="验证码已发送到你的邮箱，10 分钟内有效", data={})


@router.post("/account/delete", summary="注销账号", response_model=APIResponse[dict])
async def delete_account(
    body: DeleteAccountRequest,
    response: Response,
    user: CurrentUserDep,
    accounts: AccountServiceDep = None,
):
    await accounts.delete_account(user.user_id, body.code)
    _clear_session_cookie(response)
    return APIResponse(code=200, message="账号已注销", data={})
