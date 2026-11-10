"""
登录鉴权依赖。

挂在受保护的路由组上（见 app/api/v1/router.py）：没有有效登录 cookie 时直接 401。
前端的 proxy.ts 只做"有没有 cookie"的乐观跳转，真正的强制校验在这里。
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends

from app.auth import tokens
from app.config import settings
from app.exceptions.handlers import AppException


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    username: str


def require_user(
    session_token: Annotated[str | None, Cookie(alias=settings.AUTH_COOKIE_NAME)] = None,
) -> CurrentUser:
    session = tokens.verify(session_token)
    if session is None:
        raise AppException(message="未登录或登录已过期", code=401, detail="请先登录")
    return CurrentUser(user_id=session.user_id, username=session.username)


CurrentUserDep = Annotated[CurrentUser, Depends(require_user)]
