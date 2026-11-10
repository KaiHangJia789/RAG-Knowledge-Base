"""
会话接口
GET    /sessions              — 会话列表（分页，按更新时间倒序）
POST   /sessions              — 新建空会话
GET    /sessions/{id}         — 会话详情（含全部消息与引用）
DELETE /sessions/{id}         — 删除会话

会话内的消息由 POST /qa/ask 传入 session_id 时写入，这里不直接写消息。
"""
from fastapi import APIRouter, Query

from app.dependencies.auth import SessionServiceDep
from app.dependencies.login import CurrentUserDep
from app.models.response import APIResponse, PaginatedData
from app.models.session import SessionCreate, SessionDetail, SessionSummary

router = APIRouter(prefix="/sessions", tags=["会话"])


@router.get(
    "",
    summary="会话列表",
    response_model=APIResponse[PaginatedData[SessionSummary]],
)
async def list_sessions(
    page: int = Query(default=1, ge=1, description="页码（从1开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数（最大100）"),
    session_service: SessionServiceDep = None,
    user: CurrentUserDep = None,
):
    data = await session_service.list_sessions(page=page, page_size=page_size, user_id=user.user_id)
    return APIResponse(code=200, message=f"共 {data.total} 条记录", data=data)


@router.post(
    "",
    summary="新建会话",
    response_model=APIResponse[SessionSummary],
)
async def create_session(
    body: SessionCreate = SessionCreate(),
    session_service: SessionServiceDep = None,
    user: CurrentUserDep = None,
):
    summary = await session_service.create_session(body.title, user.user_id)
    return APIResponse(code=200, message="会话已创建", data=summary)


@router.get(
    "/{session_id}",
    summary="会话详情",
    response_model=APIResponse[SessionDetail],
)
async def get_session(
    session_id: str,
    session_service: SessionServiceDep = None,
    user: CurrentUserDep = None,
):
    detail = await session_service.get_session(session_id, user.user_id)
    return APIResponse(code=200, message="查询成功", data=detail)


@router.delete(
    "/{session_id}",
    summary="删除会话",
    response_model=APIResponse[dict],
)
async def delete_session(
    session_id: str,
    session_service: SessionServiceDep = None,
    user: CurrentUserDep = None,
):
    await session_service.delete_session(session_id, user.user_id)
    return APIResponse(
        code=200,
        message=f"会话 '{session_id}' 已删除",
        data={"id": session_id, "deleted": True},
    )
