"""技术支持场景：行为契约，网络与数据库边界用替身。"""
import asyncio
import json

import pytest
from pydantic import ValidationError

from app.llm.client import LLMResponse, LLMUsage
from app.models.qa import QARequest
from app.rag.models import RetrievalConfig, RagAnswer
from app.rag.pipeline import RagPipeline
from tests.test_rag_pipeline import FakeIndexService, make_hit


def config():
    return RetrievalConfig(prompt_name="support_answer_v1")


def reply(status="answered", answer="检查 backend 日志确认连接错误[1]。", questions=None):
    return json.dumps({"status": status, "answer": answer,
                       "clarifying_questions": questions or []}, ensure_ascii=False)


class SequenceLLM:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = []

    async def generate(self, system, user_message, **kwargs):
        self.calls.append({"system": system, "user": user_message, **kwargs})
        item = self.texts.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, model="fake",
                           usage=LLMUsage(prompt_tokens=11, completion_tokens=7))


def index(*hits):
    return FakeIndexService(list(hits) or [make_hit(1, "检查 backend 日志", .9)])


async def test_support_followup_retrieves_rewritten_query_but_answers_original():
    history = [{"role": "user", "content": "Docker 部署后接口返回 502"},
               {"role": "assistant", "content": "请确认 backend 是否启动"}]
    llm = SequenceLLM('{"query":"Docker 部署接口 502 的 backend 日志如何查看"}', reply())
    idx = index()
    result = await RagPipeline(idx, llm).answer("如何看它的日志？", config(),
                                                history=history, viewer_user_id="alice")
    assert idx.search_calls[0]["query"] == "Docker 部署接口 502 的 backend 日志如何查看"
    assert idx.search_calls[0]["viewer_user_id"] == "alice"
    assert "如何看它的日志？" in llm.calls[-1]["user"]
    assert result.question == "如何看它的日志？"
    assert result.query_rewritten is True
    assert result.prompt_tokens == 22
    assert result.completion_tokens == 14
    assert result.answer_status == "answered"
    assert [c.index for c in result.citations] == [1]


async def test_support_first_turn_skips_rewrite():
    llm = SequenceLLM(reply())
    result = await RagPipeline(index(), llm).answer("如何查日志", config())
    assert len(llm.calls) == 1
    assert result.query_rewritten is False
    assert result.retrieval_query == "如何查日志"


@pytest.mark.parametrize("bad", ['{}', 'not json', '{"query":""}',
                                '{"query":"为什么报错"}', TimeoutError()])
async def test_bad_rewrite_falls_back_without_losing_error_version_or_config(bad):
    q = "v1.2 的 DB_TIMEOUT 503 与 POSTGRES_HOST 怎么处理？"
    llm = SequenceLLM(bad, reply())
    idx = index()
    result = await RagPipeline(idx, llm).answer(q, config(), history=[
        {"role": "user", "content": "我正在排障"}])
    assert idx.search_calls[0]["query"] == q
    assert result.rewrite_failed is True
    assert result.query_rewritten is False


async def test_clarification_is_not_a_refusal_or_lexical_false_positive():
    llm = SequenceLLM(reply("needs_clarification", "尚未提供部署环境。", ["采用 Docker 还是本机部署？"]))
    result = await RagPipeline(index(), llm).answer("运行不了", config())
    assert result.answer_status == "needs_clarification"
    assert result.refused is False
    assert result.refusal_reason is None
    assert result.clarifying_questions == ["采用 Docker 还是本机部署？"]


@pytest.mark.parametrize("status", ["partial", "conflicting_evidence"])
async def test_partial_and_conflicting_answers_remain_cited_not_refused(status):
    llm = SequenceLLM(reply(status, "已知步骤见[1]，尚未提供进一步信息。"))
    result = await RagPipeline(index(), llm).answer("如何处理", config())
    assert result.answer_status == status
    assert not result.refused
    assert len(result.citations) == 1


@pytest.mark.parametrize("bad", ['not json', '{}', reply("invented"),
                                reply(answer="重启试试"), reply(answer="答案[9]"),
                                reply("needs_clarification", questions=[]),
                                reply("answered", questions=["不应同时回答与追问"]),
                                reply("needs_clarification", questions=["a", "b", "c"])])
async def test_malformed_or_unsupported_output_fails_closed(bad):
    result = await RagPipeline(index(), SequenceLLM(bad)).answer("问题", config())
    assert result.answer_status == "insufficient_evidence"
    assert result.refused is True
    assert result.citations == []
    assert result.answer != bad


async def test_support_cannot_cite_a_hit_omitted_by_context_budget():
    idx = index(make_hit(1, "内容", .9), make_hit(2, "x" * 6500, .8))
    result = await RagPipeline(idx, SequenceLLM(reply(answer="答案[2]"))).answer("问题", config())
    assert result.refused is True
    assert result.citations == []


async def test_support_no_hits_does_not_generate_an_answer():
    llm = SequenceLLM()
    result = await RagPipeline(FakeIndexService([]), llm).answer("问题", config())
    assert result.answer_status == "insufficient_evidence"
    assert result.refused
    assert not llm.calls


@pytest.mark.parametrize("name", ["baseline", "code_gen", "query_rewrite", "unknown"])
def test_public_api_rejects_experiment_prompts(name):
    with pytest.raises(ValidationError):
        QARequest(question="问题", prompt_name=name)


def test_public_api_defaults_to_support():
    assert QARequest(question="问题").prompt_name == "support_answer_v3"


async def test_clarification_survives_session_roundtrip_and_continues_history():
    from tests.test_sessions import FakeSessionRepo, FakeSessionDB, USER_ID
    from app.services.session_service import SessionService
    service = SessionService(db=FakeSessionDB(), repo=FakeSessionRepo())
    sid = (await service.create_session(None, USER_ID)).id
    answer = RagAnswer(question="运行不了", answer="请补充环境。",
                       answer_status="needs_clarification",
                       clarifying_questions=["采用 Docker 还是本机部署？"])
    await service.append_turn(sid, "运行不了", answer, USER_ID)
    detail = await service.get_session(sid, USER_ID)
    assert detail.messages[-1].answer_status == "needs_clarification"
    assert detail.messages[-1].clarifying_questions == ["采用 Docker 还是本机部署？"]
    history = await service.load_history(sid, USER_ID)
    assert "采用 Docker 还是本机部署？" in history[-1]["content"]


async def test_actual_rewrite_timeout_cancels_work_and_falls_back(monkeypatch):
    from app.rag import support
    cancelled = asyncio.Event()

    class SlowLLM:
        async def generate(self, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    monkeypatch.setattr(support, "REWRITE_TIMEOUT_SECONDS", 0.01)
    result = await support.rewrite_query(SlowLLM(), "HTTP 503", [{"role": "user", "content": "Docker"}])
    assert result.failed and result.query == "HTTP 503"
    assert cancelled.is_set()


async def test_cancelled_rewrite_propagates_request_cancellation():
    from app.rag.support import rewrite_query
    started = asyncio.Event()

    class SlowLLM:
        async def generate(self, **kwargs):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(rewrite_query(SlowLLM(), "问题", [{"role": "user", "content": "Docker"}]))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_rewritten_no_hits_still_reports_rewrite_cost_and_document_filter():
    llm = SequenceLLM('{"query":"Docker 503 排障"}')
    idx = FakeIndexService([])
    cfg = config()
    cfg.document_id = "specific-document"
    result = await RagPipeline(idx, llm).answer("503 如何排障", cfg,
        history=[{"role": "user", "content": "Docker"}], viewer_user_id="alice")
    assert result.refused and result.llm_called
    assert result.prompt_tokens == 11 and result.completion_tokens == 7
    assert len(llm.calls) == 1
    assert idx.search_calls[0]["document_id"] == "specific-document"
    assert idx.search_calls[0]["viewer_user_id"] == "alice"


async def test_empty_context_does_not_generate_unsupported_answer():
    llm = SequenceLLM(reply())
    result = await RagPipeline(index(make_hit(1, "x" * 6500, .9)), llm).answer("问题", config())
    assert result.refused and result.answer_status == "insufficient_evidence"
    assert not llm.calls


@pytest.fixture
async def support_api():
    from httpx import AsyncClient, ASGITransport
    from app.dependencies.auth import get_rag_pipeline, get_session_service
    from app.dependencies.login import CurrentUser, require_user
    from app.main import app
    from app.services.session_service import SessionService
    from tests.test_sessions import FakeSessionDB, FakeSessionRepo, USER_ID
    service = SessionService(db=FakeSessionDB(), repo=FakeSessionRepo())
    pipeline = RagPipeline(index(), SequenceLLM(reply("needs_clarification", "请补充环境。", ["Docker 还是本机部署？"])))
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_session_service] = lambda: service
    app.dependency_overrides[get_rag_pipeline] = lambda: pipeline
    app.dependency_overrides[require_user] = lambda: CurrentUser(user_id=USER_ID, username="alice")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, pipeline
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


async def test_http_prompt_whitelist_and_clarification_persistence(support_api):
    client, pipeline = support_api
    invalid = await client.post("/api/v1/qa/ask", json={"question": "问题", "prompt_name": "code_gen"})
    assert invalid.status_code == 422
    assert not pipeline.llm.calls
    sid = (await client.post("/api/v1/sessions", json={})).json()["data"]["id"]
    response = await client.post("/api/v1/qa/ask", json={"question": "运行不了", "session_id": sid})
    assert response.status_code == 200
    assert response.json()["message"] == "待补充信息"
    assert response.json()["data"]["answer_status"] == "needs_clarification"
    saved = (await client.get(f"/api/v1/sessions/{sid}")).json()["data"]["messages"][-1]
    assert saved["answer_status"] == "needs_clarification"
    assert saved["clarifying_questions"] == ["Docker 还是本机部署？"]


@pytest.mark.parametrize(("question", "altered"), [
    ("server.port=8080 如何配置？", "服务端口如何配置"),
    ("出现 E-1001 怎么办？", "出现错误怎么办"),
    ("/etc/nginx/nginx.conf 如何修改？", "nginx 如何修改配置"),
    ("1.2.3-beta 如何部署？", "1.2.3 如何部署"),
    (r"C:\apps\rag\config.yml 如何配置？", "config.yml 如何配置"),
])
async def test_rewrite_preserves_paths_dotted_settings_and_full_versions(question, altered):
    from app.rag.support import rewrite_query
    result = await rewrite_query(SequenceLLM(json.dumps({"query": altered})), question,
                                 [{"role": "user", "content": "我在部署服务"}])
    assert result.failed
    assert result.query == question


async def test_rewrite_accepts_preserved_diagnostic_identifiers():
    from app.rag.support import rewrite_query
    query = "Docker 1.2.3-beta /etc/nginx/nginx.conf E-1001 server.port=8080 怎么检查？"
    result = await rewrite_query(SequenceLLM(json.dumps({"query": query})),
        "1.2.3-beta /etc/nginx/nginx.conf E-1001 server.port=8080 怎么检查？",
        [{"role": "user", "content": "Docker 部署"}])
    assert result.query == query and not result.failed


async def test_invalid_output_is_not_a_valid_negative_eval_answer():
    from app.evaluation.support import load_support_dataset, score_support_result
    from pathlib import Path
    case = next(c for c in load_support_dataset(Path("data/eval/support_eval_draft.json")).items if c.id == "s008")
    result = await RagPipeline(index(), SequenceLLM("not json")).answer(case.input.question, config())
    assert result.refused and result.answer_status == "insufficient_evidence"
    assert score_support_result(case, result)["structural_pass"] is False
    assert result.output_validation_failed is True


async def test_genuine_insufficient_answer_retains_corresponding_source():
    result = await RagPipeline(index(), SequenceLLM(reply("insufficient_evidence", "资料仅有部署说明[1]，没有定价。"))).answer("价格", config())
    assert result.refused
    assert [c.index for c in result.citations] == [1]
    assert result.output_validation_failed is False


@pytest.mark.parametrize(("original", "changed"), [
    ("1.2.3", "1.2.30"), ("1.2.3-beta", "1.2.3-beta2"),
    ("server.port=8080", "server.port=80800"), ("E-1001", "E-10010"),
    ("E-1001", "E-1001x"),
])
async def test_rewrite_does_not_accept_longer_identifier_with_matching_prefix(original, changed):
    from app.rag.support import rewrite_query
    question = f"{original} 如何排查？"
    result = await rewrite_query(SequenceLLM(json.dumps({"query": f"Docker {changed} 如何排查？"})),
                                 question, [{"role": "user", "content": "Docker"}])
    assert result.failed and result.query == question


@pytest.mark.parametrize("status", ["answered", "partial", "conflicting_evidence", "insufficient_evidence"])
async def test_omitted_empty_questions_are_normalized_without_false_refusal(status):
    raw = json.dumps({"status": status, "answer": "本机 HTTP 设置 AUTH_COOKIE_SECURE=False[1]。"})
    result = await RagPipeline(index(), SequenceLLM(raw)).answer("本机登录后401", config())
    assert result.answer_status == status
    assert result.clarifying_questions == []
    assert result.output_normalized is True
    assert result.output_validation_failed is False
    assert result.refused is (status == "insufficient_evidence")


@pytest.mark.parametrize("payload", [
    {"status": "needs_clarification", "answer": "请补充环境。"},
    {"status": "answered", "answer": "答案[1]", "clarifying_questions": None},
    {"status": "answered", "answer": "答案[1]", "clarifying_questions": ""},
    {"status": "answered", "answer": "答案[1]", "clarifying_questions": [123]},
    {"status": "answered", "answer": "答案[1]", "unexpected": "sensitive-marker"},
    {"answer": "答案[1]"}, {"status": "answered"},
])
async def test_normalization_never_repairs_other_schema_errors(payload):
    result = await RagPipeline(index(), SequenceLLM(json.dumps(payload))).answer("问题", config())
    assert result.output_validation_failed and result.refused
    assert not result.output_normalized
    assert result.output_validation_errors
    assert "sensitive-marker" not in str(result.model_dump())


async def test_valid_output_does_not_report_normalization():
    result = await RagPipeline(index(), SequenceLLM(reply())).answer("问题", config())
    assert result.output_normalized is False
    assert result.output_validation_errors == []


async def test_validation_diagnostics_do_not_include_model_input_or_exception(caplog):
    raw = '{sensitive-marker-not-json'
    result = await RagPipeline(index(), SequenceLLM(raw)).answer("问题", config())
    assert result.output_validation_errors == ["invalid_json"]
    assert raw not in caplog.text
    assert raw not in str(result.model_dump())


@pytest.mark.parametrize("version", ["support_answer_v1", "support_answer_v2", "support_answer_v3"])
async def test_support_versions_use_their_own_prompt_and_json_contract(version):
    from app.llm.support_prompts import SUPPORT_SYSTEMS
    llm = SequenceLLM(reply())
    result = await RagPipeline(index(), llm).answer("如何检查", RetrievalConfig(prompt_name=version))
    assert llm.calls[0]["system"] == SUPPORT_SYSTEMS[version]
    assert llm.calls[0]["json_mode"] is True
    assert result.answer_status == "answered"
    assert QARequest(question="问题", prompt_name=version).prompt_name == version


@pytest.mark.parametrize("status", ["needs_clarification", "insufficient_evidence"])
async def test_invalid_citations_fail_closed_for_nonfactual_states(status):
    raw = reply(status, "untrusted-marker[9]", ["什么环境？"] if status == "needs_clarification" else [])
    result = await RagPipeline(index(), SequenceLLM(raw)).answer("问题", config())
    assert result.output_validation_failed
    assert "invalid_citation" in result.output_validation_errors
    assert result.refused and result.answer_status == "insufficient_evidence"
    assert "untrusted-marker" not in result.answer
    assert result.citations == [] and result.clarifying_questions == []
