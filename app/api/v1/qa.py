"""
问答接口
POST /api/v1/qa/ask            — 检索增强问答（带引用来源）
GET  /api/v1/qa/chunks/{id}    — 引用定位：取 chunk 及前后文
GET  /api/v1/qa/stats          — 索引概况
"""
import logging

from fastapi import APIRouter, Query

from app.dependencies.auth import DbDep, DocumentServiceDep, RagPipelineDep, SessionServiceDep
from app.dependencies.login import CurrentUserDep
from app.exceptions.handlers import ChunkNotFoundError, IndexNotReadyError
from app.models.qa import ChunkContext, QARequest, QAStats
from app.models.response import APIResponse
from app.rag.models import RetrievalConfig

logger = logging.getLogger("rag_api.qa")

router = APIRouter(prefix="/qa", tags=["问答"])


@router.post(
    "/ask",
    summary="检索增强问答",
    description="""
基于已索引的文档回答问题，返回答案与引用来源。

**流程**: 支持模式可先结合历史改写查询 → 权限范围内检索 → 阈值过滤 → 装配上下文 → 生成与状态、引用校验

**拒答**（`refused=true`）: 索引未构建、检索无命中、资料不足或支持输出校验失败。
索引未就绪不调用模型；无检索命中不调用回答生成模型，但可能已经调用查询改写。
**澄清**: `answer_status=needs_clarification`，返回 1～2 个澄清问题，不视为拒答。

**引用**: `citations[].index` 对应答案中的 `[n]` 标记，
`chunk_id` 可用于 `GET /api/v1/qa/chunks/{chunk_id}` 定位原文。

**会话**: 传入 `session_id` 时，问题与回答（含完整引用）会追加到该会话，
并把该会话最近几轮的问答作为多轮上下文交给模型（被拒答的轮次不计入）。
技术支持模式会结合历史改写检索问题；失败时使用原问题。会话不存在时直接返回 404，不调用 LLM。
    """,
    response_model=APIResponse[dict],
)
async def ask_question(
    body: QARequest,
    pipeline: RagPipelineDep = None,
    session_service: SessionServiceDep = None,
    user: CurrentUserDep = None,
):
    # 会话内追问：取本会话最近几轮作为多轮历史。先取历史（同时校验会话存在），
    # 避免白跑一次 LLM 后才发现会话不存在。历史只在服务端读取，不信任前端传入
    history: list[dict] = []
    if body.session_id:
        history = await session_service.load_history(body.session_id, user.user_id)

    config = RetrievalConfig(
        strategy=body.strategy,
        retrieve_k=body.retrieve_k,
        min_score=body.min_score,
        final_k=body.final_k,
        prompt_name=body.prompt_name,
        document_id=body.document_id,
        temperature=body.temperature,
    )

    result = await pipeline.answer(
        body.question, config, history=history or None, viewer_user_id=user.user_id
    )

    if body.session_id:
        await session_service.append_turn(body.session_id, body.question, result, user.user_id)

    return APIResponse(
        code=200,
        message="待补充信息" if result.answer_status == "needs_clarification" else ("已回答" if not result.refused else "资料不足"),
        data=result.model_dump(mode="json"),
    )


@router.get(
    "/chunks/{chunk_id}",
    summary="获取 chunk 及上下文",
    description="""
按 chunk_id 取回该文本块及其前后相邻块 —— 这是「引用来源可定位」的落点。

返回结果中 `is_target=true` 的那条即被引用的原文块，
前端应滚动定位到它并高亮。
    """,
    response_model=APIResponse[ChunkContext],
)
async def get_chunk_context(
    chunk_id: str,
    before: int = Query(default=1, ge=0, le=10, description="向前多取几块"),
    after: int = Query(default=1, ge=0, le=10, description="向后多取几块"),
    db: DbDep = None,
    pipeline: RagPipelineDep = None,
    doc_service: DocumentServiceDep = None,
    user: CurrentUserDep = None,
):
    from app.db.repositories.chunk_repo import ChunkRepository

    repo = ChunkRepository()

    # 先按主键取目标块（拿 document_id 与 chunk_index）
    async with db.pool.acquire() as conn:
        target = await repo.fetch_one_by_id(conn, chunk_id)

    # 归属校验：不可见的文档与不存在的 chunk 返回同样的 404，不泄露 chunk 是否存在
    if target is not None and not await doc_service.is_visible(
        str(dict(target)["document_id"]), user.user_id
    ):
        target = None

    if target is None:
        # 给一条能定位问题的提示：区分"索引里有但库里没有"与"完全不存在"
        record = (
            pipeline.index_service.get_by_chunk_id(chunk_id)
            if pipeline.index_service
            else None
        )
        hint = None
        if record is not None:
            hint = (
                f"该块存在于向量索引（文档 '{record.filename}' 第 {record.chunk_index} 块），"
                f"但数据库中查不到，索引与数据库不一致，请重建索引"
            )
        raise ChunkNotFoundError(chunk_id, hint=hint)

    row = dict(target)

    async with db.pool.acquire() as conn:
        rows = await repo.fetch_neighbors(
            conn, str(row["document_id"]), int(row["chunk_index"]),
            before=before, after=after,
        )

    context = ChunkContext(
        document_id=str(row["document_id"]),
        filename=row.get("filename") or "",
        chunk_strategy=row.get("chunk_strategy", "splitter"),
        items=[
            {
                "chunk_id": str(r["id"]),
                "chunk_index": r["chunk_index"],
                "text": r["chunk_text"],
                "page_number": r["page_number"],
                "is_target": str(r["id"]) == chunk_id,
            }
            for r in rows
        ],
    )
    return APIResponse(code=200, message="查询成功", data=context)


@router.get(
    "/stats",
    summary="索引概况",
    description="返回当前向量索引的策略、向量数、来源文档数等信息",
    response_model=APIResponse[QAStats],
)
async def get_stats(pipeline: RagPipelineDep = None):
    svc = pipeline.index_service
    if svc is None:
        raise IndexNotReadyError()

    stats = svc.stats()
    return APIResponse(
        code=200,
        message=f"索引 {stats['vectors']} 条向量",
        data=QAStats(**stats),
    )
