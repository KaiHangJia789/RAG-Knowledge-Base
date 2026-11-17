"""
RagPipeline — 检索增强生成的完整闭环（命令式编排）

流程:
    检索 → 阈值拒答（不发 LLM）→ 装配带编号上下文 → LLM 生成
         → 解析 [n] 引用 → 校验编号有效性 → 返回 RagAnswer

**架构说明（Week11 重构）**：
  具体步骤已抽到 `app/rag/steps.py`，本类只负责**按顺序编排**它们。
  与之对应的是 `app/agent/graphs.py` —— 用 LangGraph 把同一批步骤
  编排成状态机（带条件分支与循环）。两者共用 steps.py，所以
  「普通 RAG vs LangGraph」的差异纯粹来自编排方式，而非实现细节。

设计要点:
  - 检索全低于阈值时跳过回答生成；支持模式可能已经调用历史查询改写。
  - **依赖全部构造注入**（沿用 experiments.py:47 的 `or` 范式），
    测试可替换任意一环而不碰网络。
"""
import logging
import time

from pydantic import ValidationError

from app.llm.client import LLMClient
from app.llm.observability import current_trace_id, trace_url
from app.rag import steps
from app.llm.support_prompts import SUPPORT_SYSTEMS
from app.rag.support import INSUFFICIENT_MESSAGE, parse_support_answer, rewrite_query
from app.rag.models import RagAnswer, RefusalReason, RetrievalConfig
from app.services.index_service import IndexService

logger = logging.getLogger("rag_api.rag")


class RagPipeline:
    """RAG 问答流水线（顺序执行 steps.py 里的原子步骤）"""

    def __init__(
        self,
        index_service: IndexService | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.index_service = index_service
        self.llm = llm or LLMClient()

    async def answer(
        self,
        question: str,
        config: RetrievalConfig | None = None,
        *,
        history: list[dict] | None = None,
        viewer_user_id: str | None = None,
    ) -> RagAnswer:
        """
        回答问题。

        Args:
            question: 用户问题
            config: 检索/生成参数（None = 用默认）
            history: 多轮历史（OpenAI 格式），用于追问场景
        """
        cfg = config or RetrievalConfig()
        start = time.monotonic()

        base = RagAnswer(question=question, answer="", config=cfg)
        support_mode = cfg.prompt_name in SUPPORT_SYSTEMS
        if support_mode:
            base.answer_status = "insufficient_evidence"
            base.retrieval_query = question

        # ── 步骤 1：索引就绪检查 ──
        if not steps.is_index_ready(self.index_service):
            base.answer = "知识库尚未就绪，请先上传文档或构建索引。"
            base.refused = True
            base.refusal_reason = RefusalReason.INDEX_NOT_READY
            base.latency_ms = (time.monotonic() - start) * 1000
            return base

        # ── 步骤 2：支持场景的多轮独立查询，再执行同一权限检索 ──
        if support_mode:
            rewrite = await rewrite_query(self.llm, question, history)
            base.retrieval_query = rewrite.query
            base.query_rewritten = rewrite.query != question
            base.rewrite_failed = rewrite.failed
            base.llm_called = rewrite.attempted
            if rewrite.usage:
                base.prompt_tokens += rewrite.usage.prompt_tokens
                base.completion_tokens += rewrite.usage.completion_tokens
        hits = await steps.retrieve(
            self.index_service, base.retrieval_query or question, cfg, viewer_user_id=viewer_user_id
        )
        base.retrieved_count = len(hits)
        base.max_score = round(hits[0].score, 4) if hits else None
        # 检索命中的文档名（按相似度降序去重）—— 评估检索质量用，与答案引用无关
        base.retrieved_docs = list(dict.fromkeys(h.filename for h in hits))

        # ── 步骤 3：无命中时跳过回答生成 ──
        if not hits:
            base.answer = "根据已有资料无法回答该问题。"
            base.refused = True
            base.refusal_reason = RefusalReason.BELOW_THRESHOLD
            base.latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "拒答（检索无命中）: q=%r, min_score=%s", question[:40], cfg.min_score
            )
            return base

        # ── 步骤 4：装配上下文 + 生成 ──
        # 保留实际装配的前缀，引用不能指向因 6000 字预算未发送的片段。
        context_hits = []
        context = ""
        for hit in hits:
            candidate = steps.assemble_context([*context_hits, hit])
            if candidate == context:
                break
            context_hits.append(hit)
            context = candidate

        if support_mode and not context_hits:
            base.answer = INSUFFICIENT_MESSAGE
            base.refused = True
            base.refusal_reason = RefusalReason.BELOW_THRESHOLD
            base.latency_ms = (time.monotonic() - start) * 1000
            return base

        if support_mode:
            resp = await self.llm.generate(
                system=SUPPORT_SYSTEMS[cfg.prompt_name],
                user_message=f"<evidence>\n{context}\n</evidence>\n<question>{question}</question>",
                history=history, thinking_enabled=False, temperature=cfg.temperature,
                json_mode=True,
            )
        else:
            resp = await steps.generate_answer(
                self.llm, question, context, config=cfg, history=history
            )
        base.llm_called = True
        base.prompt_tokens += resp.usage.prompt_tokens
        base.completion_tokens += resp.usage.completion_tokens

        # ── 步骤 5：结构校验与引用映射 ──
        answer_text = resp.text or ""
        if support_mode:
            try:
                parsed = parse_support_answer(answer_text)
                base.output_normalized = "clarifying_questions" not in parsed.model_fields_set
                base.answer_status = parsed.status
                base.clarifying_questions = parsed.clarifying_questions
                answer_text = parsed.answer
            except ValidationError as exc:
                # 不记录 input、loc 或 msg，防止模型输出的秘密进入日志/响应。
                kinds = {error["type"] for error in exc.errors(include_input=False, include_context=False)}
                base.output_validation_errors = ["invalid_json" if "json_invalid" in kinds else "schema_violation"]
                base.output_validation_failed = True
                base.answer_status = "insufficient_evidence"
                answer_text = INSUFFICIENT_MESSAGE

        result = steps.attach_citations(answer_text, context_hits)
        base.answer = result.text
        base.citations = result.citations
        base.citation_validity = result.validity
        base.invalid_citations = result.invalid

        # ── 步骤 6：支持模式按状态判定；旧路径继续使用词法拒答 ──
        if support_mode:
            base.output_validation_failed |= bool(result.invalid)
            if result.invalid:
                base.output_validation_errors.append("invalid_citation")
            factual = base.answer_status in ("answered", "partial", "conflicting_evidence")
            if result.invalid or (factual and not result.citations):
                if factual and not result.citations:
                    base.output_validation_errors.append("missing_citation")
                base.output_validation_failed = True
                base.citations = []
                base.answer_status = "insufficient_evidence"
                base.answer = INSUFFICIENT_MESSAGE
                base.clarifying_questions = []
            if base.answer_status == "insufficient_evidence":
                base.refused = True
                base.refusal_reason = RefusalReason.LLM_REFUSED
        elif result.is_refusal:
            base.refused = True
            base.refusal_reason = RefusalReason.LLM_REFUSED

        # ── 步骤 7：追踪信息 ──
        tid = current_trace_id()
        if tid:
            base.trace_id = tid
            base.trace_url = trace_url(tid)

        base.latency_ms = (time.monotonic() - start) * 1000
        logger.info(
            "问答完成: q=%r, hits=%d, cited=%d, refused=%s, %.0fms",
            question[:40], len(hits), len(base.citations), base.refused, base.latency_ms,
        )
        return base
