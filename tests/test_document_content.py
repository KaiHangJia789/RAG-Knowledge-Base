"""Readable document content uses stored chunks and document visibility."""
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.config import settings


@pytest.fixture
def content_document(fake_db):
    now = datetime.now(UTC)
    doc = {
        "id": str(uuid4()),
        "user_id": fake_db.user_id("demo_user"),
        "filename": "技术说明.pdf",
        "file_type": ".pdf",
        "file_size": 1024,
        "storage_path": "uploads/private/internal.pdf",
        "status": "ready",
        "is_shared": False,
        "created_at": now,
        "updated_at": now,
    }
    fake_db.store[doc["id"]] = doc
    return doc


@pytest.fixture
def chunk_queries(fake_db, monkeypatch):
    """Extend the DB double at its SQL boundary; keep the repository real.

    The shared FakeConnection ignores document/strategy filters and ordering.
    Enforce those SQL clauses here so unrelated chunks cannot pass unnoticed.
    """
    connection_type = type(fake_db.pool.acquire().conn)
    original_fetch = connection_type.fetch
    queries = []

    async def fetch(conn, query, *args):
        if conn._table_of(query) != "chunks":
            return await original_fetch(conn, query, *args)
        queries.append((query, args))
        sql = " ".join(query.split())
        assert "WHERE document_id = $1 AND chunk_strategy = $2" in sql
        assert "ORDER BY chunk_index" in sql
        document_id, strategy = args
        rows = [
            row for row in fake_db.table("chunks").values()
            if str(row["document_id"]) == document_id
            and row["chunk_strategy"] == strategy
        ]
        return sorted(rows, key=lambda row: row["chunk_index"])

    monkeypatch.setattr(connection_type, "fetch", fetch)
    return queries


async def test_content_returns_ordered_active_chunks_without_paths(
    async_client, fake_db, content_document, chunk_queries, monkeypatch,
):
    monkeypatch.setattr(settings, "CHUNK_STRATEGY", "preview-strategy")
    doc_id = content_document["id"]
    for chunk_id, document_id, strategy, index, text, page in [
        ("00000000-0000-0000-0000-000000000002", doc_id, "preview-strategy", 2, "第二页正文\n保留换行", 2),
        ("00000000-0000-0000-0000-000000000003", str(uuid4()), "preview-strategy", 0, "其他文档", 1),
        ("00000000-0000-0000-0000-000000000004", doc_id, "other-strategy", 0, "其他策略", 1),
        ("00000000-0000-0000-0000-000000000001", doc_id, "preview-strategy", 0, "第一页正文", None),
    ]:
        fake_db.table("chunks")[chunk_id] = {
            "id": UUID(chunk_id), "document_id": UUID(document_id),
            "chunk_strategy": strategy, "chunk_index": index,
            "chunk_text": text, "page_number": page,
            "storage_path": "uploads/private/chunk-internal.pdf",
        }

    response = await async_client.get(f"/api/v1/documents/{doc_id}/content")

    assert response.status_code == 200, response.text
    assert response.json()["code"] == 200
    assert response.json()["data"] == {
        "document_id": doc_id,
        "filename": "技术说明.pdf",
        "items": [
            {"chunk_id": "00000000-0000-0000-0000-000000000001", "chunk_index": 0,
             "text": "第一页正文", "page_number": None, "is_target": False},
            {"chunk_id": "00000000-0000-0000-0000-000000000002", "chunk_index": 2,
             "text": "第二页正文\n保留换行", "page_number": 2, "is_target": False},
        ],
    }
    assert len(chunk_queries) == 1
    assert chunk_queries[0][1] == (doc_id, "preview-strategy")


async def test_content_allows_shared_foreign_document(
    async_client, fake_db, content_document, chunk_queries,
):
    content_document.update(user_id=fake_db.user_id("test_user"), is_shared=True)
    chunk_id = str(uuid4())
    fake_db.table("chunks")[chunk_id] = {
        "id": chunk_id, "document_id": content_document["id"],
        "chunk_strategy": settings.CHUNK_STRATEGY, "chunk_index": 0,
        "chunk_text": "公共文档正文", "page_number": 1,
    }

    response = await async_client.get(
        f"/api/v1/documents/{content_document['id']}/content"
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["items"][0]["text"] == "公共文档正文"


async def test_content_rejects_private_foreign_document_before_chunk_query(
    async_client, fake_db, content_document, chunk_queries,
):
    doc_id = content_document["id"]
    assert (await async_client.get(f"/api/v1/documents/{doc_id}")).status_code == 200
    content_document["user_id"] = fake_db.user_id("test_user")

    response = await async_client.get(f"/api/v1/documents/{doc_id}/content")

    assert response.status_code == 404
    assert response.json()["code"] == 404
    assert chunk_queries == []


@pytest.mark.parametrize("doc_id", ["00000000-0000-0000-0000-000000000099", "invalid-id"])
async def test_content_missing_document_returns_404_without_chunk_query(
    async_client, chunk_queries, doc_id,
):
    response = await async_client.get(f"/api/v1/documents/{doc_id}/content")

    assert response.status_code == 404
    assert response.json()["code"] == 404
    assert chunk_queries == []


@pytest.mark.parametrize("status", ["ready", "uploaded", "parsing", "failed"])
async def test_content_without_parsed_chunks_returns_empty_items(
    async_client, content_document, chunk_queries, status,
):
    content_document["status"] = status

    response = await async_client.get(
        f"/api/v1/documents/{content_document['id']}/content"
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "document_id": content_document["id"],
        "filename": "技术说明.pdf",
        "items": [],
    }


async def test_content_requires_login(async_client, content_document, chunk_queries):
    from app.dependencies.login import require_user
    from app.main import app

    override = app.dependency_overrides.pop(require_user)
    try:
        response = await async_client.get(
            f"/api/v1/documents/{content_document['id']}/content"
        )
    finally:
        app.dependency_overrides[require_user] = override

    assert response.status_code == 401
    assert chunk_queries == []
