"""
API v1 路由聚合
将各模块的路由统一注册到 v1 路由器下
"""
from fastapi import APIRouter

from fastapi import Depends

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.upload import router as upload_router
from app.api.v1.documents import router as documents_router
from app.api.v1.qa import router as qa_router
from app.api.v1.sessions import router as sessions_router
from app.dependencies.login import require_user

api_v1_router = APIRouter(prefix="/api/v1")

# 公开：健康检查、登录。其余业务路由必须带有效登录 cookie
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)

_protected = [Depends(require_user)]
api_v1_router.include_router(upload_router, dependencies=_protected)
api_v1_router.include_router(documents_router, dependencies=_protected)
api_v1_router.include_router(qa_router, dependencies=_protected)
api_v1_router.include_router(sessions_router, dependencies=_protected)
