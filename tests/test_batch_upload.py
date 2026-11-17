"""Batch limits must reject before writes; individual failures preserve other uploads."""
import pytest

from app.config import settings


@pytest.fixture
def batch_limits(monkeypatch):
    monkeypatch.setitem(settings.__dict__, "MAX_UPLOAD_BATCH_FILES", 3)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setitem(settings.__dict__, "MAX_UPLOAD_BATCH_SIZE_MB", 1)


@pytest.mark.asyncio
async def test_limits_report_configured_values(async_client, batch_limits):
    response = await async_client.get("/api/v1/upload/limits")
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["max_files"], data["max_file_size_mb"], data["max_total_size_mb"]) == (3, 1, 1)
    assert ".md" in data["allowed_extensions"]


@pytest.mark.asyncio
async def test_too_many_files_leaves_no_documents(async_client, fake_db, batch_limits):
    response = await async_client.post("/api/v1/upload/batch", files=[
        ("files", (f"{i}.json", b"{}")) for i in range(4)
    ])
    assert response.status_code == 400
    assert "3" in response.json()["message"]
    assert not fake_db.store


@pytest.mark.asyncio
@pytest.mark.parametrize("sizes", [(1_048_577,), (600_000, 600_000)])
async def test_excess_bytes_reject_entire_batch(async_client, fake_db, batch_limits, sizes):
    response = await async_client.post("/api/v1/upload/batch", files=[
        ("files", (f"{i}.json", b"x" * size)) for i, size in enumerate(sizes)
    ])
    assert response.status_code == 400
    assert "MB" in response.json()["message"]
    assert not fake_db.store


@pytest.mark.asyncio
async def test_exact_total_limit_and_private_ownership(async_client, fake_db, batch_limits):
    response = await async_client.post("/api/v1/upload/batch", files=[
        ("files", ("first.json", b"x" * 524_288)),
        ("files", ("second.json", b"x" * 524_288)),
    ])
    assert response.status_code == 200
    results = response.json()["data"]["items"]
    assert [item["filename"] for item in results] == ["first.json", "second.json"]
    assert all(item["success"] for item in results)
    assert len(fake_db.store) == 2
    assert all(row["user_id"] == fake_db.user_id("demo_user") for row in fake_db.store.values())


@pytest.mark.asyncio
async def test_individual_type_error_does_not_stop_later_files(async_client, fake_db, batch_limits):
    response = await async_client.post("/api/v1/upload/batch", files=[
        ("files", ("first.json", b"{}")),
        ("files", ("bad.exe", b"bad")),
        ("files", ("last.json", b"{}")),
    ])
    assert response.status_code == 200
    results = response.json()["data"]["items"]
    assert [item["success"] for item in results] == [True, False, True]
    assert results[1]["document"] is None
    assert "不支持" in results[1]["message"]
    assert len(fake_db.store) == 2


@pytest.mark.asyncio
async def test_parse_failure_reports_saved_document_and_continues(async_client, batch_limits):
    response = await async_client.post("/api/v1/upload/batch", files=[
        ("files", ("bad.pdf", b"not a PDF")),
        ("files", ("last.json", b"{}")),
    ])
    assert response.status_code == 200
    results = response.json()["data"]["items"]
    assert results[0]["success"] is False
    assert results[0]["document"]["status"] == "failed"
    assert results[1]["success"] is True


@pytest.mark.asyncio
async def test_parse_failure_remains_failed_when_status_write_fails(async_client, monkeypatch, batch_limits):
    from app.dependencies import auth

    async def failed_write(*args):
        raise RuntimeError("database status update unavailable")

    monkeypatch.setattr(auth._doc_service, "update_status", failed_write)
    response = await async_client.post("/api/v1/upload/batch", files=[
        ("files", ("bad.pdf", b"not a PDF")),
        ("files", ("last.json", b"{}")),
    ])
    results = response.json()["data"]["items"]
    assert results[0]["success"] is False
    assert results[0]["document"]["status"] == "failed"
    assert "解析失败" in results[0]["message"]
    assert results[1]["success"] is True


@pytest.mark.asyncio
async def test_missing_files_are_rejected(async_client):
    response = await async_client.post("/api/v1/upload/batch")
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_batch_requires_login(async_client):
    from app.main import app
    from app.dependencies.login import require_user
    override = app.dependency_overrides.pop(require_user)
    try:
        response = await async_client.post("/api/v1/upload/batch", files={"files": ("x.json", b"{}")})
        assert response.status_code == 401
    finally:
        app.dependency_overrides[require_user] = override


@pytest.mark.asyncio
async def test_single_file_limit_still_applies(async_client, fake_db, batch_limits):
    response = await async_client.post("/api/v1/upload", files={"file": ("x.json", b"x" * 1_048_577)})
    assert response.status_code == 400
    assert not fake_db.store
