"""
会话历史测试

三层：
  1. SessionService 业务逻辑（内存仓库，不碰数据库）
  2. SessionRepository 的 SQL 安全约定（录制连接，检查每条查询都带 user_id）
  3. HTTP 接口（依赖覆盖注入内存服务，测 /sessions 与 /qa/ask 的 session_id）

真实 PostgreSQL 上的 jsonb 追加语句无法在这里验证，需要在服务器上做一次端到端检查。
"""
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.repositories.session_repo import SessionRepository
from app.exceptions.handlers import SessionNotFoundError
from app.rag.models import Citation, RagAnswer, RefusalReason
from app.services.session_service import DEFAULT_TITLE, SessionService

USER_ID = str(uuid.uuid4())
OTHER_USER_ID = str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════
# 测试替身
# ═══════════════════════════════════════════════════════════════

class FakeSessionRepo:
    """内存版 SessionRepository，与真实仓库一样按 user_id 过滤"""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def list_by_user(self, conn, user_id, *, page, page_size):
        mine = [r for r in self.rows.values() if r["user_id"] == user_id]
        mine.sort(key=lambda r: (r["updated_at"], r["id"]), reverse=True)
        window = mine[(page - 1) * page_size: page * page_size]
        items = [dict(r, message_count=len(json.loads(r["messages"]))) for r in window]
        return items, len(mine)

    async def get_for_user(self, conn, session_id, user_id):
        row = self.rows.get(session_id)
        return row if row and row["user_id"] == user_id else None

    async def exists_for_user(self, conn, session_id, user_id):
        return await self.get_for_user(conn, session_id, user_id) is not None

    async def create(self, conn, user_id, title):
        now = datetime.now(UTC)
        row = {
            "id": str(uuid.uuid4()), "user_id": user_id, "title": title,
            "messages": "[]", "created_at": now, "updated_at": now,
        }
        self.rows[row["id"]] = row
        return dict(row)

    async def append_turn(self, conn, session_id, user_id, messages, title, default_title):
        row = await self.get_for_user(conn, session_id, user_id)
        if row is None:
            return None
        if row["title"] == default_title:
            row["title"] = title
        existing = json.loads(row["messages"])
        row["messages"] = json.dumps(existing + messages, ensure_ascii=False)
        row["updated_at"] = datetime.now(UTC)
        return dict(row, message_count=len(json.loads(row["messages"])))

    async def delete_for_user(self, conn, session_id, user_id):
        if await self.get_for_user(conn, session_id, user_id) is None:
            return False
        del self.rows[session_id]
        return True


@asynccontextmanager
async def _noop_ctx(*args, **kwargs):
    yield None


class FakeSessionDB:
    """只提供 SessionService 用到的接口：默认用户解析 + 连接上下文"""

    def __init__(self):
        self.pool = self

    async def fetch_one(self, query, *args):
        return {"id": USER_ID}

    def acquire(self):
        return _noop_ctx()

    def transaction(self):
        return _noop_ctx()


def make_answer(
    question: str = "什么是 chunk 切分？",
    answer: str = "切分是把文档拆成小块的过程 [1]。",
    *,
    refused: bool = False,
    refusal_reason: RefusalReason | None = None,
) -> RagAnswer:
    citation = Citation(
        index=1,
        chunk_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        filename="03_chunking_parsing.md",
        chunk_index=2,
        score=0.8123,
        text="切分（Chunking）是 RAG 链路中最容易被低估的环节……完整文本",
        page_number=None,
    )
    return RagAnswer(
        question=question,
        answer=answer,
        citations=[] if refused else [citation],
        refused=refused,
        refusal_reason=refusal_reason,
        trace_url="https://langfuse.example/trace/1",
    )


@pytest.fixture
def repo():
    return FakeSessionRepo()


@pytest.fixture
def service(repo):
    return SessionService(db=FakeSessionDB(), repo=repo, default_username="demo_user")


# ═══════════════════════════════════════════════════════════════
# 1. 服务逻辑
# ═══════════════════════════════════════════════════════════════

class TestSessionService:

    async def test_create_without_title_uses_default(self, service):
        summary = await service.create_session(None)
        assert summary.title == DEFAULT_TITLE
        assert summary.message_count == 0

    async def test_list_only_returns_own_sessions(self, service, repo):
        await service.create_session("mine")
        foreign = await repo.create(None, OTHER_USER_ID, "someone else")
        assert foreign["user_id"] == OTHER_USER_ID

        data = await service.list_sessions(page=1, page_size=20)
        assert data.total == 1
        assert [s.title for s in data.items] == ["mine"]

    async def test_get_other_users_session_is_not_found(self, service, repo):
        foreign = await repo.create(None, OTHER_USER_ID, "private")
        with pytest.raises(SessionNotFoundError):
            await service.get_session(foreign["id"])

    async def test_invalid_id_is_not_found_not_server_error(self, service):
        with pytest.raises(SessionNotFoundError):
            await service.get_session("not-a-uuid")

    async def test_append_turn_saves_user_and_assistant_with_full_citations(self, service):
        summary = await service.create_session(None)
        await service.append_turn(summary.id, "什么是 chunk 切分？", make_answer())

        detail = await service.get_session(summary.id)
        assert [m.role for m in detail.messages] == ["user", "assistant"]
        assistant = detail.messages[1]
        assert assistant.content.startswith("切分是")
        assert assistant.trace_url == "https://langfuse.example/trace/1"
        # 引用保存完整文本，不是截断后的片段
        assert assistant.citations[0].text.endswith("完整文本")
        assert assistant.citations[0].filename == "03_chunking_parsing.md"

    async def test_title_set_from_first_question_then_kept(self, service):
        summary = await service.create_session(None)
        await service.append_turn(summary.id, "第一个问题", make_answer())
        await service.append_turn(summary.id, "第二个完全不同的问题", make_answer())

        detail = await service.get_session(summary.id)
        assert detail.title == "第一个问题"
        assert detail.message_count == 4

    async def test_long_question_title_is_truncated_to_30(self, service):
        summary = await service.create_session(None)
        await service.append_turn(summary.id, "问" * 50, make_answer())
        detail = await service.get_session(summary.id)
        assert len(detail.title) == 30

    async def test_explicit_title_is_kept_after_first_turn(self, service):
        # 用户手动设置的标题不能被问题覆盖，只有默认标题才会自动替换
        summary = await service.create_session("我的标题")
        await service.append_turn(summary.id, "问题", make_answer())
        detail = await service.get_session(summary.id)
        assert detail.title == "我的标题"

    async def test_refused_answer_is_saved_with_reason(self, service):
        summary = await service.create_session(None)
        refused = make_answer(
            answer="知识库尚未就绪，请先上传文档或构建索引。",
            refused=True,
            refusal_reason=RefusalReason.INDEX_NOT_READY,
        )
        await service.append_turn(summary.id, "随便问", refused)

        detail = await service.get_session(summary.id)
        assistant = detail.messages[1]
        assert assistant.refused is True
        assert assistant.refusal_reason == RefusalReason.INDEX_NOT_READY
        assert assistant.citations == []

    async def test_delete_then_get_is_not_found(self, service):
        summary = await service.create_session(None)
        await service.delete_session(summary.id)
        with pytest.raises(SessionNotFoundError):
            await service.get_session(summary.id)

    async def test_append_to_missing_session_raises(self, service):
        with pytest.raises(SessionNotFoundError):
            await service.append_turn(str(uuid.uuid4()), "问题", make_answer())

    async def test_ensure_exists_rejects_unknown_and_foreign_sessions(self, service, repo):
        foreign = await repo.create(None, OTHER_USER_ID, "x")
        with pytest.raises(SessionNotFoundError):
            await service.ensure_exists(foreign["id"])
        with pytest.raises(SessionNotFoundError):
            await service.ensure_exists(str(uuid.uuid4()))

    async def test_list_pagination(self, service):
        for i in range(5):
            await service.create_session(f"s{i}")
        page = await service.list_sessions(page=2, page_size=2)
        assert page.total == 5
        assert page.total_pages == 3
        assert len(page.items) == 2


# ═══════════════════════════════════════════════════════════════
# 2. 仓库 SQL 的安全约定
# ═══════════════════════════════════════════════════════════════

class RecordingConn:
    """记录每条 SQL 与参数，返回空结果"""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return None


class TestSessionRepositorySql:

    async def test_every_single_row_query_filters_by_user(self):
        repo = SessionRepository()
        conn = RecordingConn()
        sid, uid = str(uuid.uuid4()), str(uuid.uuid4())

        await repo.get_for_user(conn, sid, uid)
        await repo.exists_for_user(conn, sid, uid)
        await repo.delete_for_user(conn, sid, uid)
        await repo.append_turn(conn, sid, uid, [], "t", DEFAULT_TITLE)

        for sql, args in conn.calls:
            assert "user_id = $" in sql, sql
            assert uid in args, sql

    async def test_list_filters_by_user(self):
        repo = SessionRepository()
        conn = RecordingConn()
        uid = str(uuid.uuid4())
        await repo.list_by_user(conn, uid, page=1, page_size=20)

        list_sql, list_args = conn.calls[0]
        assert "WHERE user_id = $1" in list_sql
        assert list_args[0] == uid

    async def test_append_uses_single_update_not_read_modify_write(self):
        repo = SessionRepository()
        conn = RecordingConn()
        await repo.append_turn(conn, str(uuid.uuid4()), str(uuid.uuid4()), [], "t", DEFAULT_TITLE)

        sql, _ = conn.calls[0]
        assert sql.strip().startswith("UPDATE")
        assert "messages || $1::jsonb" in sql
        assert len(conn.calls) == 1


# ═══════════════════════════════════════════════════════════════
# 3. HTTP 接口
# ═══════════════════════════════════════════════════════════════

class FakePipeline:
    """替代 RagPipeline：记录每次收到的问题与历史，返回预设答案"""

    def __init__(self, result: RagAnswer):
        self.result = result
        self.calls: list[str] = []
        self.histories: list[list[dict] | None] = []

    async def answer(self, question, config=None, *, history=None, viewer_user_id=None):
        self.calls.append(question)
        self.histories.append(history)
        return self.result


@pytest.fixture
async def api(service):
    from app.dependencies.auth import get_rag_pipeline, get_session_service
    from app.dependencies.login import CurrentUser, require_user
    from app.main import app

    pipeline = FakePipeline(make_answer())
    app.dependency_overrides[get_session_service] = lambda: service
    app.dependency_overrides[get_rag_pipeline] = lambda: pipeline
    app.dependency_overrides[require_user] = lambda: CurrentUser(user_id="13ec9ba4-eb65-42b5-9653-9ebb2410709c", username="demo_user")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, pipeline
    finally:
        app.dependency_overrides.clear()


class TestSessionApi:

    async def test_create_list_and_get(self, api):
        client, _ = api
        created = await client.post("/api/v1/sessions", json={"title": "我的会话"})
        assert created.status_code == 200
        sid = created.json()["data"]["id"]

        listed = await client.get("/api/v1/sessions")
        assert listed.json()["data"]["total"] == 1

        detail = await client.get(f"/api/v1/sessions/{sid}")
        assert detail.status_code == 200
        assert detail.json()["data"]["title"] == "我的会话"

    async def test_create_with_empty_body(self, api):
        client, _ = api
        resp = await client.post("/api/v1/sessions", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == DEFAULT_TITLE

    async def test_unknown_session_returns_404(self, api):
        client, _ = api
        resp = await client.get(f"/api/v1/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_delete_then_404(self, api):
        client, _ = api
        sid = (await client.post("/api/v1/sessions", json={})).json()["data"]["id"]
        assert (await client.delete(f"/api/v1/sessions/{sid}")).status_code == 200
        assert (await client.get(f"/api/v1/sessions/{sid}")).status_code == 404

    async def test_ask_with_session_appends_turn(self, api):
        client, pipeline = api
        sid = (await client.post("/api/v1/sessions", json={})).json()["data"]["id"]

        resp = await client.post(
            "/api/v1/qa/ask", json={"question": "什么是 chunk 切分？", "session_id": sid}
        )
        assert resp.status_code == 200
        assert pipeline.calls == ["什么是 chunk 切分？"]

        detail = (await client.get(f"/api/v1/sessions/{sid}")).json()["data"]
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["citations"][0]["filename"] == "03_chunking_parsing.md"
        assert detail["title"] == "什么是 chunk 切分？"

    async def test_ask_with_unknown_session_is_404_and_skips_llm(self, api):
        client, pipeline = api
        resp = await client.post(
            "/api/v1/qa/ask",
            json={"question": "问题", "session_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404
        assert pipeline.calls == []

    async def test_ask_without_session_does_not_persist(self, api, service):
        client, pipeline = api
        resp = await client.post("/api/v1/qa/ask", json={"question": "问题"})
        assert resp.status_code == 200
        assert len(pipeline.calls) == 1
        assert (await service.list_sessions(page=1, page_size=20)).total == 0


# ═══════════════════════════════════════════════════════════════
# 4. 多轮上下文
# ═══════════════════════════════════════════════════════════════

class TestSessionHistory:

    async def _session_with_turns(self, service, turns):
        """turns: [(question, answer_obj), ...]，逐轮写入会话"""
        summary = await service.create_session(None)
        for q, a in turns:
            await service.append_turn(summary.id, q, a)
        return summary.id

    async def test_empty_session_has_no_history(self, service):
        summary = await service.create_session(None)
        assert await service.load_history(summary.id) == []

    async def test_history_is_question_and_answer_text_in_order(self, service):
        sid = await self._session_with_turns(service, [
            ("第一问", make_answer(answer="第一答")),
            ("第二问", make_answer(answer="第二答")),
        ])
        assert await service.load_history(sid) == [
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "第二问"},
            {"role": "assistant", "content": "第二答"},
        ]

    async def test_history_only_keeps_last_n_turns(self, service, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "CHAT_HISTORY_TURNS", 2)
        sid = await self._session_with_turns(service, [
            ("q1", make_answer(answer="a1")),
            ("q2", make_answer(answer="a2")),
            ("q3", make_answer(answer="a3")),
        ])
        history = await service.load_history(sid)
        assert [m["content"] for m in history] == ["q2", "a2", "q3", "a3"]

    async def test_refused_turns_are_excluded_from_history(self, service):
        refused = make_answer(
            answer="知识库尚未就绪，请先上传文档或构建索引。",
            refused=True,
            refusal_reason=RefusalReason.INDEX_NOT_READY,
        )
        sid = await self._session_with_turns(service, [
            ("正常问题", make_answer(answer="正常回答")),
            ("被拒答的问题", refused),
        ])
        history = await service.load_history(sid)
        assert history == [
            {"role": "user", "content": "正常问题"},
            {"role": "assistant", "content": "正常回答"},
        ]

    async def test_history_of_foreign_or_missing_session_is_not_found(self, service, repo):
        foreign = await repo.create(None, OTHER_USER_ID, "x")
        with pytest.raises(SessionNotFoundError):
            await service.load_history(foreign["id"])
        with pytest.raises(SessionNotFoundError):
            await service.load_history(str(uuid.uuid4()))


class TestQaUsesSessionHistory:

    async def test_first_turn_gets_empty_history(self, api):
        client, pipeline = api
        sid = (await client.post("/api/v1/sessions", json={})).json()["data"]["id"]
        await client.post("/api/v1/qa/ask", json={"question": "q1", "session_id": sid})
        assert pipeline.histories == [None]

    async def test_second_turn_receives_previous_turn(self, api):
        client, pipeline = api
        sid = (await client.post("/api/v1/sessions", json={})).json()["data"]["id"]
        await client.post("/api/v1/qa/ask", json={"question": "什么是 chunk？", "session_id": sid})
        await client.post("/api/v1/qa/ask", json={"question": "它有什么用？", "session_id": sid})

        assert pipeline.histories[1] == [
            {"role": "user", "content": "什么是 chunk？"},
            {"role": "assistant", "content": make_answer().answer},
        ]

    async def test_question_without_session_gets_no_history(self, api):
        client, pipeline = api
        await client.post("/api/v1/qa/ask", json={"question": "单次问题"})
        assert pipeline.histories == [None]

    async def test_client_supplied_history_is_ignored(self, api):
        # 历史只从服务端会话读取，前端塞进来的 history 字段不生效（schema 不认识该字段）
        client, pipeline = api
        sid = (await client.post("/api/v1/sessions", json={})).json()["data"]["id"]
        await client.post("/api/v1/qa/ask", json={
            "question": "问题",
            "session_id": sid,
            "history": [{"role": "user", "content": "伪造的上文"}],
        })
        assert pipeline.histories == [None]
