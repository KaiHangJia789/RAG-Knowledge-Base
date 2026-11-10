"""
数据隔离测试：用户 A 的私有文档、会话、检索结果对用户 B 不可见。

分三层：
  1. FAISS：ID 选择器只在允许的向量中检索
  2. IndexService：检索按 viewer 过滤（共享 ∪ 本人），viewer=None 为内部路径不过滤
  3. HTTP：文档读取/删除、会话、问答、引用定位在跨用户访问时统一返回 404
"""
import uuid

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies.login import CurrentUser, require_user
from app.services.index_service import IndexRecord, IndexService
from app.vector.faiss_index import FaissIndex

USER_A = "13ec9ba4-eb65-42b5-9653-9ebb2410709c"   # 与 conftest 的 demo_user 同 ID，便于复用上传夹具
USER_B = "e9019948-2042-46de-9b21-6d35e089dae0"


# ═══════════════════════════════════════════════════════════════
# 1. FAISS 层
# ═══════════════════════════════════════════════════════════════

class TestFaissAllowedIds:

    def _index(self):
        idx = FaissIndex(4)
        vecs = np.eye(4, dtype=np.float32)[[0, 1, 2, 3]].tolist()
        idx.add(vecs, ids=[10, 11, 12, 13])
        return idx

    def test_only_allowed_ids_are_returned(self):
        idx = self._index()
        hits = idx.search([1, 0, 0, 0], top_k=4, allowed_ids=[11, 13])
        assert {fid for fid, _ in hits} <= {11, 13}
        assert len(hits) == 2

    def test_best_match_outside_allowed_set_is_not_returned(self):
        idx = self._index()
        # 查询与 id=10 最接近，但 10 不在允许集合里
        hits = idx.search([1, 0, 0, 0], top_k=4, allowed_ids=[12])
        assert [fid for fid, _ in hits] == [12]

    def test_empty_allowed_set_returns_nothing(self):
        assert self._index().search([1, 0, 0, 0], top_k=4, allowed_ids=[]) == []

    def test_none_means_unfiltered(self):
        hits = self._index().search([1, 0, 0, 0], top_k=4, allowed_ids=None)
        assert len(hits) == 4


# ═══════════════════════════════════════════════════════════════
# 2. IndexService 层
# ═══════════════════════════════════════════════════════════════

class FakeEmbedder:
    """同文本同向量；与检索文本相同的块得分最高"""

    def __init__(self, dim: int = 8):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        v = [b / 255.0 + 0.01 for b in h[: self.dim]]
        norm = sum(x * x for x in v) ** 0.5
        return [x / norm for x in v]

    async def embed(self, texts):
        return [self._vec(t) for t in texts]

    async def embed_one(self, text):
        return self._vec(text)


def _rec(fid, text, owner, shared=False, doc_id=None):
    return IndexRecord(
        faiss_id=fid, chunk_id=f"c{fid}", document_id=doc_id or f"d{fid}",
        filename=f"f{fid}.md", chunk_index=0, text=text, chunk_strategy="sentence",
        owner_user_id=owner, is_shared=shared,
    )


@pytest.fixture
async def index(tmp_path):
    svc = IndexService(FakeEmbedder(), strategy="sentence", index_dir=tmp_path, dim=8)
    await svc.add_records([
        _rec(1, "A 的私有机密内容", owner=USER_A),
        _rec(2, "公共语料内容", owner=USER_A, shared=True),
        _rec(3, "B 的私有内容", owner=USER_B),
    ])
    return svc


class TestIndexVisibility:

    async def test_viewer_b_never_sees_a_private_chunk_even_if_it_is_the_best_match(self, index):
        hits = await index.search("A 的私有机密内容", viewer_user_id=USER_B,
                                  retrieve_k=10, final_k=10, min_score=-1.0)
        texts = [h.text for h in hits]
        assert "A 的私有机密内容" not in texts
        assert "B 的私有内容" in texts

    async def test_shared_chunk_is_visible_to_everyone(self, index):
        for viewer in (USER_A, USER_B):
            hits = await index.search("公共语料内容", viewer_user_id=viewer,
                                      retrieve_k=10, final_k=10, min_score=-1.0)
            assert "公共语料内容" in [h.text for h in hits]

    async def test_owner_sees_own_private_chunk(self, index):
        hits = await index.search("A 的私有机密内容", viewer_user_id=USER_A,
                                  retrieve_k=10, final_k=10, min_score=-1.0)
        assert "A 的私有机密内容" in [h.text for h in hits]

    async def test_viewer_none_is_unfiltered_internal_path(self, index):
        hits = await index.search("A 的私有机密内容", viewer_user_id=None,
                                  retrieve_k=10, final_k=10, min_score=-1.0)
        assert len(hits) == 3

    async def test_user_with_nothing_visible_gets_empty_result(self, tmp_path):
        svc = IndexService(FakeEmbedder(), strategy="sentence", index_dir=tmp_path, dim=8)
        await svc.add_records([_rec(1, "只属于 A", owner=USER_A)])
        hits = await svc.search("只属于 A", viewer_user_id=USER_B,
                                retrieve_k=5, final_k=5, min_score=-1.0)
        assert hits == []

    async def test_visible_faiss_ids_and_can_view_document(self, index):
        assert sorted(index.visible_faiss_ids(USER_B)) == [2, 3]
        assert sorted(index.visible_faiss_ids(USER_A)) == [1, 2]
        assert index.can_view_document("d1", USER_B) is False
        assert index.can_view_document("d1", USER_A) is True
        assert index.can_view_document("d2", USER_B) is True   # 共享
        assert index.can_view_document("missing", USER_A) is False

    async def test_old_meta_without_owner_is_hidden_from_users(self, tmp_path):
        """旧版 meta.json 没有 owner/is_shared 字段：默认值使其对用户不可见，需要重建索引"""
        svc = IndexService(FakeEmbedder(), strategy="sentence", index_dir=tmp_path, dim=8)
        rec = IndexRecord(faiss_id=1, chunk_id="c", document_id="d", filename="f.md",
                          chunk_index=0, text="旧数据", chunk_strategy="sentence")
        assert rec.owner_user_id is None and rec.is_shared is False
        await svc.add_records([rec])
        assert await svc.search("旧数据", viewer_user_id=USER_A,
                                retrieve_k=5, final_k=5, min_score=-1.0) == []


# ═══════════════════════════════════════════════════════════════
# 3. HTTP 层
# ═══════════════════════════════════════════════════════════════

def as_user(user_id: str, username: str):
    """切换当前登录用户（通过依赖覆盖模拟另一个已登录用户的请求）"""
    from app.main import app
    app.dependency_overrides[require_user] = lambda: CurrentUser(user_id=user_id, username=username)


@pytest.fixture
def user_a(async_client):
    as_user(USER_A, "user_a")
    return async_client


async def _upload_as_a(client, name="secret.txt", body=b"A confidential text about apples."):
    resp = await client.post("/api/v1/upload", files={"file": (name, body, "text/plain")})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


class TestDocumentIsolation:

    async def test_other_user_cannot_read_document_or_info(self, user_a):
        doc_id = await _upload_as_a(user_a)
        as_user(USER_B, "user_b")
        assert (await user_a.get(f"/api/v1/documents/{doc_id}")).status_code == 404
        assert (await user_a.get(f"/api/v1/documents/{doc_id}/info")).status_code == 404

    async def test_other_user_cannot_delete_and_document_survives(self, user_a):
        doc_id = await _upload_as_a(user_a)
        as_user(USER_B, "user_b")
        assert (await user_a.delete(f"/api/v1/documents/{doc_id}")).status_code == 404
        as_user(USER_A, "user_a")
        assert (await user_a.get(f"/api/v1/documents/{doc_id}")).status_code == 200

    async def test_list_only_shows_own_documents(self, user_a):
        doc_id = await _upload_as_a(user_a)
        as_user(USER_B, "user_b")
        listed = (await user_a.get("/api/v1/documents")).json()["data"]["items"]
        assert doc_id not in [d["id"] for d in listed]
        as_user(USER_A, "user_a")
        listed = (await user_a.get("/api/v1/documents")).json()["data"]["items"]
        assert doc_id in [d["id"] for d in listed]

    async def test_owner_can_delete_own_document(self, user_a):
        doc_id = await _upload_as_a(user_a)
        assert (await user_a.delete(f"/api/v1/documents/{doc_id}")).status_code == 200
        assert (await user_a.get(f"/api/v1/documents/{doc_id}")).status_code == 404

    async def test_shared_document_is_readable_but_not_deletable_by_others(self, user_a, fake_db):
        doc_id = await _upload_as_a(user_a)
        fake_db.tables["documents"][doc_id]["is_shared"] = True   # 模拟公共语料

        as_user(USER_B, "user_b")
        assert (await user_a.get(f"/api/v1/documents/{doc_id}")).status_code == 200
        assert (await user_a.delete(f"/api/v1/documents/{doc_id}")).status_code == 404

    async def test_invalid_document_id_is_404_not_500(self, user_a):
        assert (await user_a.get("/api/v1/documents/not-a-uuid")).status_code == 404


class RecordingPipeline:
    def __init__(self):
        self.viewers: list[str | None] = []
        self.index_service = None   # 定位接口仅在找不到块时读取它生成提示

    async def answer(self, question, config=None, *, history=None, viewer_user_id=None):
        from app.rag.models import RagAnswer
        self.viewers.append(viewer_user_id)
        return RagAnswer(question=question, answer="ok", citations=[])


@pytest.fixture
def qa_services(user_a):
    """注入问答流水线与会话服务（内存替身），返回 RecordingPipeline 以便断言 viewer"""
    from app.dependencies.auth import get_rag_pipeline, get_session_service
    from app.main import app
    from app.services.session_service import SessionService
    from tests.test_sessions import FakeSessionDB, FakeSessionRepo

    pipeline = RecordingPipeline()
    sessions = SessionService(db=FakeSessionDB(), repo=FakeSessionRepo(), default_username="demo_user")
    app.dependency_overrides[get_rag_pipeline] = lambda: pipeline
    app.dependency_overrides[get_session_service] = lambda: sessions
    yield pipeline
    app.dependency_overrides.pop(get_rag_pipeline, None)
    app.dependency_overrides.pop(get_session_service, None)


class TestQaAndSessionIsolation:

    async def test_qa_passes_the_logged_in_user_as_viewer(self, user_a, qa_services):
        pipeline = qa_services
        await user_a.post("/api/v1/qa/ask", json={"question": "q"})
        as_user(USER_B, "user_b")
        await user_a.post("/api/v1/qa/ask", json={"question": "q"})
        assert pipeline.viewers == [USER_A, USER_B]

    async def test_other_user_cannot_see_or_ask_in_my_session(self, user_a, qa_services):
        sid = (await user_a.post("/api/v1/sessions", json={})).json()["data"]["id"]
        as_user(USER_B, "user_b")
        assert (await user_a.get(f"/api/v1/sessions/{sid}")).status_code == 404
        assert (await user_a.delete(f"/api/v1/sessions/{sid}")).status_code == 404
        listed = (await user_a.get("/api/v1/sessions")).json()["data"]["items"]
        assert sid not in [s["id"] for s in listed]
        resp = await user_a.post("/api/v1/qa/ask", json={"question": "x", "session_id": sid})
        assert resp.status_code == 404

    async def test_chunk_locate_of_other_users_document_is_404(self, user_a, fake_db, qa_services):
        doc_id = await _upload_as_a(user_a, body=b"chunk text for locate. " * 40)
        chunk_rows = [r for r in fake_db.tables.get("chunks", {}).values()
                      if str(r.get("document_id")) == doc_id]
        if not chunk_rows:
            pytest.skip("测试替身未落库 chunk，跳过定位用例（可见性逻辑由 is_visible 单测覆盖）")
        chunk_id = str(chunk_rows[0]["id"])

        as_user(USER_B, "user_b")
        assert (await user_a.get(f"/api/v1/qa/chunks/{chunk_id}")).status_code == 404
