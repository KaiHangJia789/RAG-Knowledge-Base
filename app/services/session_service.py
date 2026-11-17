"""
会话服务 — 多轮问答历史

每轮问答写入两条消息：用户问题 + 助手回答（含完整引用）。
引用保存完整 chunk 文本，文档被删除或索引重建后，历史仍能展示原文。

HTTP 请求传入登录用户，仓库层始终按 user_id 过滤。内部脚本可使用默认演示用户。
"""
import asyncio
import json
import logging
import math
import uuid
from datetime import UTC, datetime

import asyncpg

from app.config import settings
from app.db.connection import Database
from app.db.repositories.session_repo import SessionRepository
from app.exceptions.handlers import AppException, SessionNotFoundError, UserNotFoundError
from app.models.response import PaginatedData
from app.models.session import SessionDetail, SessionMessage, SessionSummary
from app.rag.models import RagAnswer

logger = logging.getLogger("rag_api.session")

DEFAULT_TITLE = "未命名会话"
TITLE_MAX_LEN = 30


class SessionService:

    def __init__(
        self,
        db: Database,
        repo: SessionRepository | None = None,
        default_username: str | None = None,
    ) -> None:
        self.db = db
        self.repo = repo or SessionRepository()
        self._default_username = default_username or settings.DEFAULT_USERNAME
        # 与 DocumentService 相同的默认用户解析（带缓存、双检锁）
        self._default_user_id: str | None = None
        self._user_id_lock = asyncio.Lock()

    # ═══════════════════════════════════════════════════════════
    # 用户解析与参数校验
    # ═══════════════════════════════════════════════════════════

    async def _resolve_user_id(self) -> str:
        if self._default_user_id is not None:
            return self._default_user_id

        async with self._user_id_lock:
            if self._default_user_id is not None:
                return self._default_user_id

            row = await self.db.fetch_one(
                "SELECT id FROM users WHERE username = $1", self._default_username
            )
            if row is None:
                raise UserNotFoundError(self._default_username)

            self._default_user_id = str(row["id"])
            return self._default_user_id

    async def _user_id_or_default(self, user_id: str | None) -> str:
        """显式传入（请求上下文中的登录用户）则用传入值；仅内部脚本与测试省略时用默认用户"""
        return user_id if user_id is not None else await self._resolve_user_id()

    @staticmethod
    def _check_id(session_id: str) -> None:
        """非法 UUID 直接按「未找到」处理，不把它送进 SQL（否则 asyncpg 报类型错，变成 500）"""
        try:
            uuid.UUID(session_id)
        except (ValueError, TypeError, AttributeError):
            raise SessionNotFoundError(str(session_id))

    # ═══════════════════════════════════════════════════════════
    # 读取
    # ═══════════════════════════════════════════════════════════

    async def list_sessions(
        self, *, page: int, page_size: int, user_id: str | None = None
    ) -> PaginatedData[SessionSummary]:
        user_id = await self._user_id_or_default(user_id)
        async with self.db.pool.acquire() as conn:
            rows, total = await self.repo.list_by_user(
                conn, user_id, page=page, page_size=page_size
            )
        return PaginatedData[SessionSummary](
            items=[self._to_summary(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    async def get_session(self, session_id: str, user_id: str | None = None) -> SessionDetail:
        self._check_id(session_id)
        user_id = await self._user_id_or_default(user_id)
        async with self.db.pool.acquire() as conn:
            row = await self.repo.get_for_user(conn, session_id, user_id)
        if row is None:
            raise SessionNotFoundError(session_id)

        messages = [SessionMessage(**m) for m in self._load_messages(row)]
        return SessionDetail(**self._to_summary(row).model_dump(), messages=messages)

    async def ensure_exists(self, session_id: str, user_id: str | None = None) -> None:
        """问答前校验会话存在，避免白跑一次 LLM 后才发现会话不存在"""
        self._check_id(session_id)
        user_id = await self._user_id_or_default(user_id)
        async with self.db.pool.acquire() as conn:
            exists = await self.repo.exists_for_user(conn, session_id, user_id)
        if not exists:
            raise SessionNotFoundError(session_id)

    async def load_history(self, session_id: str, user_id: str | None = None) -> list[dict]:
        """
        取本会话最近几轮的对话，作为 LLM 的多轮历史（OpenAI 格式 {role, content}）。

        - 按「最近 N 轮」截取（N = settings.CHAT_HISTORY_TURNS），再丢弃其中被拒答的轮次。
          被拒答的回答（如「知识库尚未就绪」）不应被模型当作上文延续。
        - 只传问题和回答的文本，不传引用原文：历史的作用是承接语境，
          本轮的原文依据仍由本轮检索提供。
        - 不存在或越权返回 404，与 ensure_exists 一致。
        """
        self._check_id(session_id)
        user_id = await self._user_id_or_default(user_id)
        async with self.db.pool.acquire() as conn:
            row = await self.repo.get_for_user(conn, session_id, user_id)
        if row is None:
            raise SessionNotFoundError(session_id)

        messages = self._load_messages(row)
        # 消息按 (user, assistant) 成对追加（见 append_turn），两两配对即为轮次
        turns = list(zip(messages[0::2], messages[1::2]))[-settings.CHAT_HISTORY_TURNS:]
        history: list[dict] = []
        for user_msg, asst_msg in turns:
            if user_msg["role"] != "user" or asst_msg["role"] != "assistant":
                continue
            if asst_msg.get("refused"):
                continue
            history.append({"role": "user", "content": user_msg["content"]})
            content = asst_msg["content"]
            questions = asst_msg.get("clarifying_questions") or []
            if questions:
                content += "\n" + "\n".join(questions)
            history.append({"role": "assistant", "content": content})
        return history

    # ═══════════════════════════════════════════════════════════
    # 写入
    # ═══════════════════════════════════════════════════════════

    async def create_session(self, title: str | None, user_id: str | None = None) -> SessionSummary:
        user_id = await self._user_id_or_default(user_id)
        try:
            async with self.db.transaction() as conn:
                row = await self.repo.create(conn, user_id, title or DEFAULT_TITLE)
        except asyncpg.ForeignKeyViolationError as e:
            # 登录令牌仍有效但账号已被注销：要求重新登录，而不是落到外键约束报 500
            raise AppException(message="账号不存在", code=401, detail="请重新登录") from e
        return self._to_summary(row)

    async def append_turn(
        self, session_id: str, question: str, answer: RagAnswer, user_id: str | None = None
    ) -> None:
        """
        记录一轮问答：用户问题 + 助手回答（含引用、拒答标记、Trace 链接）。

        注意：ensure_exists 与本方法之间会话若被删除，这里会抛 404，
        但回答已经生成，调用方应知晓这一点。
        """
        self._check_id(session_id)
        user_id = await self._user_id_or_default(user_id)

        now = datetime.now(UTC)
        messages = [
            SessionMessage(role="user", content=question, timestamp=now).model_dump(mode="json"),
            SessionMessage(
                role="assistant",
                content=answer.answer,
                timestamp=now,
                citations=answer.citations,
                refused=answer.refused,
                refusal_reason=answer.refusal_reason,
                trace_url=answer.trace_url,
                answer_status=answer.answer_status,
                clarifying_questions=answer.clarifying_questions,
            ).model_dump(mode="json"),
        ]
        title = question.strip()[:TITLE_MAX_LEN] or DEFAULT_TITLE

        async with self.db.transaction() as conn:
            row = await self.repo.append_turn(
                conn, session_id, user_id, messages, title, DEFAULT_TITLE
            )
        if row is None:
            raise SessionNotFoundError(session_id)

    async def delete_session(self, session_id: str, user_id: str | None = None) -> None:
        self._check_id(session_id)
        user_id = await self._user_id_or_default(user_id)
        async with self.db.transaction() as conn:
            deleted = await self.repo.delete_for_user(conn, session_id, user_id)
        if not deleted:
            raise SessionNotFoundError(session_id)

    # ═══════════════════════════════════════════════════════════
    # 行 → 模型
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _load_messages(row) -> list[dict]:
        """asyncpg 返回 jsonb 为字符串；测试替身可能直接给列表，两种都要支持"""
        raw = row["messages"]
        return json.loads(raw) if isinstance(raw, str) else list(raw)

    @classmethod
    def _to_summary(cls, row) -> SessionSummary:
        # 列表查询带 message_count 列；RETURNING * 的行没有这一列，只能从 messages 计算
        count = row.get("message_count")
        if count is None:
            count = len(cls._load_messages(row))
        return SessionSummary(
            id=str(row["id"]),
            title=row["title"],
            message_count=count,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
