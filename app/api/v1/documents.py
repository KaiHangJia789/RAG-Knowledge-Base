"""
文档管理接口
提供文档的查询、详情、元信息和删除功能
"""
from fastapi import APIRouter, Query

from app.config import settings
from app.db.repositories.chunk_repo import ChunkRepository
from app.dependencies.login import CurrentUserDep
from app.dependencies.auth import DbDep, DocumentServiceDep
from app.exceptions.handlers import DocumentNotFoundError
from app.models.document import DocumentContent, DocumentInfo, DocumentResponse
from app.models.requests import DocumentSearchParams
from app.models.response import APIResponse, PaginatedData

router = APIRouter(prefix="/documents", tags=["文档管理"])


@router.get(
    "",
    summary="文档列表",
    description="分页查询文档列表，支持关键词搜索、状态过滤、类型过滤和多字段排序",
    response_model=APIResponse[PaginatedData[DocumentResponse]],
)
async def list_documents(
    keyword: str | None = Query(default=None, description="按文件名模糊搜索"),
    status: str | None = Query(default=None, description="按状态过滤: uploaded/parsing/chunking/ready/failed"),
    file_type: str | None = Query(default=None, description="按文件类型过滤: .pdf/.txt/.md 等"),
    sort_by: str = Query(default="created_at", description="排序字段"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$", description="排序方向"),
    page: int = Query(default=1, ge=1, description="页码（从1开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数（最大100）"),
    doc_service: DocumentServiceDep = None,
    user: CurrentUserDep = None,
):
    """
    获取文档列表。

    支持功能：
    - 🔍 **关键词搜索**: 按文件名模糊匹配
    - 🏷️ **状态过滤**: 按处理状态筛选（uploaded/parsing/chunking/ready/failed）
    - 📁 **类型过滤**: 按文件扩展名筛选
    - 📊 **排序**: 支持 created_at/filename/file_size 等字段排序
    - 📄 **分页**: 返回 total/page/page_size/total_pages 完整分页信息
    """
    params = DocumentSearchParams(
        keyword=keyword,
        status=status,
        file_type=file_type,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    result = await doc_service.search_documents(params, user_id=user.user_id)
    return APIResponse(
        code=200,
        message=f"共 {result.total} 条记录",
        data=result,
    )


@router.get(
    "/{doc_id}",
    summary="获取文档详情",
    description="根据文档ID获取完整文档信息",
    response_model=APIResponse[DocumentResponse],
)
async def get_document(
    doc_id: str,
    doc_service: DocumentServiceDep = None,
    user: CurrentUserDep = None,
):
    """
    获取文档完整详情。

    - **doc_id**: 上传文档时返回的唯一标识符
    - 返回文档的元数据（文件名、类型、大小、状态、创建时间等）
    - 文档不存在时返回 404
    """
    doc = await doc_service.get_document(doc_id, user.user_id)
    if doc is None:
        raise DocumentNotFoundError(doc_id)
    return APIResponse(
        code=200,
        message="查询成功",
        data=doc,
    )


@router.get(
    "/{doc_id}/content",
    summary="获取文档可读正文",
    description="按分块顺序返回当前策略的已解析正文；暂无正文时返回空列表",
    response_model=APIResponse[DocumentContent],
)
async def get_document_content(
    doc_id: str,
    db: DbDep = None,
    doc_service: DocumentServiceDep = None,
    user: CurrentUserDep = None,
):
    doc = await doc_service.get_document(doc_id, user.user_id)
    if doc is None:
        raise DocumentNotFoundError(doc_id)

    repo = ChunkRepository()
    async with db.pool.acquire() as conn:
        rows = await repo.fetch_by_document(conn, doc_id, settings.CHUNK_STRATEGY)

    content = DocumentContent(
        document_id=doc_id,
        filename=doc.filename,
        items=[
            {
                "chunk_id": str(row["id"]),
                "chunk_index": row["chunk_index"],
                "text": row["chunk_text"],
                "page_number": row["page_number"],
                "is_target": False,
            }
            for row in rows
        ],
    )
    return APIResponse(code=200, message="查询成功", data=content)


@router.get(
    "/{doc_id}/info",
    summary="获取文档元信息",
    description="获取文档元信息（轻量版，不含内部存储路径）",
    response_model=APIResponse[DocumentInfo],
)
async def get_document_info(
    doc_id: str,
    doc_service: DocumentServiceDep = None,
    user: CurrentUserDep = None,
):
    """
    获取文档元信息（轻量版）。

    与 GET /{doc_id} 的区别：
    - 不返回 storage_path 等内部字段
    - 适合列表页或预览场景

    - **doc_id**: 上传文档时返回的唯一标识符
    """
    info = await doc_service.get_document_info(doc_id, user.user_id)
    if info is None:
        raise DocumentNotFoundError(doc_id)
    return APIResponse(
        code=200,
        message="查询成功",
        data=info,
    )


@router.delete(
    "/{doc_id}",
    summary="删除文档",
    description="删除文档记录及对应的物理文件",
    response_model=APIResponse[dict],
)
async def delete_document(
    doc_id: str,
    doc_service: DocumentServiceDep = None,
    user: CurrentUserDep = None,
):
    """
    删除文档。

    - 删除数据库中的文档记录
    - 同时删除服务器上的物理文件
    - 文档不存在时返回 404

    - **doc_id**: 要删除的文档唯一标识符
    """
    success = await doc_service.delete_document(doc_id, user.user_id)
    if not success:
        raise DocumentNotFoundError(doc_id)
    return APIResponse(
        code=200,
        message=f"文档 '{doc_id}' 已删除",
        data={"id": doc_id, "deleted": True},
    )
