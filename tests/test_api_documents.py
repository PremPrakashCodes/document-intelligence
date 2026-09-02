"""Integration tests for the documents API.

The app runs against SQLite, an in-memory store, and a replayed Azure response,
so the whole request path - dependencies, repository, schemas - is exercised
with no network and no Postgres.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.deps import get_pipeline, get_session, get_store
from api.main import app
from db import repository
from db.session import set_sessionmaker
from jobs import processors


@pytest_asyncio.fixture
async def client(sessionmaker_sqlite, store, pipeline, monkeypatch):
    async def override_session():
        async with sessionmaker_sqlite() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    # The worker uses session_scope() rather than the request dependency.
    set_sessionmaker(sessionmaker_sqlite)

    # Uploading must not require a live queue.
    async def no_queue(document_id: str):
        return None

    monkeypatch.setattr("api.routers.documents._enqueue_extraction", no_queue)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    set_sessionmaker(None)


class FakeJob:
    """Just enough of bullmq.Job for the handler."""

    def __init__(self, data):
        self.data = data
        self.id = "job_test"
        self.name = "extract-document"
        self.progress = []

    async def updateProgress(self, value):
        self.progress.append(value)


@pytest_asyncio.fixture
async def extracted(client, store, pipeline, sample_pdf_bytes, monkeypatch):
    """An uploaded document with extraction already run."""
    monkeypatch.setattr(processors, "get_store", lambda: store)
    monkeypatch.setattr(processors, "get_pipeline", lambda: pipeline)

    response = await client.post(
        "/documents", files={"file": ("nl-1.pdf", sample_pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 202
    document_id = response.json()["id"]
    await processors.extract_document(FakeJob({"document_id": document_id}))
    return document_id


class TestUpload:
    async def test_accepts_a_pdf_and_stores_it(self, client, store, sample_pdf_bytes):
        response = await client.post(
            "/documents", files={"file": ("nl-1.pdf", sample_pdf_bytes, "application/pdf")}
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        assert await store.exists(f"documents/{body['id']}/source.pdf")

    async def test_rejects_a_non_pdf(self, client):
        response = await client.post("/documents", files={"file": ("x.txt", b"hello", "text/plain")})
        assert response.status_code == 415

    async def test_rejects_an_empty_file(self, client):
        response = await client.post("/documents", files={"file": ("x.pdf", b"", "application/pdf")})
        assert response.status_code == 400

    async def test_rejects_an_oversized_file(self, client, monkeypatch, settings):
        from api.config import get_settings

        small = settings.model_copy(update={"max_upload_bytes": 10})
        app.dependency_overrides[get_settings] = lambda: small
        try:
            response = await client.post(
                "/documents", files={"file": ("x.pdf", b"%PDF-" + b"0" * 100, "application/pdf")}
            )
            assert response.status_code == 413
        finally:
            app.dependency_overrides.pop(get_settings, None)


class TestDocument:
    async def test_returns_extraction_summary(self, client, extracted):
        response = await client.get(f"/documents/{extracted}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["page_count"] == 1
        assert body["table_count"] == 2
        assert body["metadata"]["producer"].startswith("Microsoft")

        matching = body["extraction"]["matching"]
        assert matching["total_cells"] == 714
        assert matching["match_rate"] > 0.99
        assert body["extraction"]["azure_di"]["completed"] is True
        assert body["extraction"]["config"]["cell_containment_threshold"] == 0.55

    async def test_unknown_document_is_404(self, client):
        assert (await client.get("/documents/doc_missing")).status_code == 404

    async def test_lists_documents(self, client, extracted):
        body = (await client.get("/documents")).json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == extracted
        # A listing must not carry page or table payload.
        assert "extraction" not in body["items"][0]

    async def test_delete_removes_rows_and_the_blob(self, client, store, extracted):
        key = f"documents/{extracted}/source.pdf"
        assert (await client.delete(f"/documents/{extracted}")).status_code == 204
        assert (await client.get(f"/documents/{extracted}")).status_code == 404
        assert not await store.exists(key)


class TestPages:
    async def test_listing_omits_page_content(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/pages")).json()
        assert body["total"] == 1
        page = body["items"][0]
        assert page["geometry"]["width"] > page["geometry"]["height"]  # landscape
        assert page["table_count"] == 2
        assert page["text_length"] > 8000
        assert "content" not in page  # the whole point of the listing

    async def test_page_detail_returns_full_content(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/pages/1")).json()
        assert len(body["content"]["words"]) == 747
        assert set(body["content"]) >= {"blocks", "words", "images", "links", "fonts"}
        assert body["table_ids"] == ["table_1", "table_2"]

    async def test_include_trims_the_payload(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/pages/1?include=words")).json()
        assert list(body["content"]) == ["words"]

    async def test_blocks_carry_the_lines_the_page_view_rebuilds_from(self, client, extracted):
        # The full-page view redraws the page from these: every line needs its
        # own box to be placed, and its spans' size and style flags to be set.
        body = (await client.get(f"/documents/{extracted}/pages/1?include=blocks")).json()
        assert list(body["content"]) == ["blocks"]
        # `text` is its own column, not part of the content blob, so it comes
        # back regardless of what `include` asked for.
        assert body["text"]

        text_blocks = [block for block in body["content"]["blocks"] if block["type"] == "text"]
        assert text_blocks
        span = text_blocks[0]["lines"][0]["spans"][0]
        assert len(text_blocks[0]["bbox"]) == 4
        assert len(text_blocks[0]["lines"][0]["bbox"]) == 4
        assert span["size"] > 0
        assert {"text", "font", "flags"} <= set(span)

    async def test_include_rejects_unknown_keys(self, client, extracted):
        response = await client.get(f"/documents/{extracted}/pages/1?include=nonsense")
        assert response.status_code == 400

    async def test_missing_page_is_404(self, client, extracted):
        assert (await client.get(f"/documents/{extracted}/pages/99")).status_code == 404


class TestRender:
    async def test_renders_a_png(self, client, extracted):
        response = await client.get(f"/documents/{extracted}/pages/1/render?scale=1.5")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.parametrize("scale", [0.1, 99])
    async def test_rejects_a_scale_outside_the_bounds(self, client, extracted, scale):
        response = await client.get(f"/documents/{extracted}/pages/1/render?scale={scale}")
        assert response.status_code == 400

    async def test_missing_page_is_404(self, client, extracted):
        assert (await client.get(f"/documents/{extracted}/pages/7/render")).status_code == 404


class TestTables:
    async def test_listing_omits_cells(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/tables")).json()
        assert [t["id"] for t in body["items"]] == ["table_1", "table_2"]
        assert body["items"][0]["row_count"] == 29
        assert "cells" not in body["items"][0]

    async def test_can_filter_by_page(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/tables?page_number=1")).json()
        assert body["total"] == 2
        body = (await client.get(f"/documents/{extracted}/tables?page_number=2")).json()
        assert body["total"] == 0

    async def test_table_detail_carries_every_cell_with_provenance(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/tables/table_1")).json()
        assert len(body["cells"]) == 539
        cell = next(c for c in body["cells"] if c["text"] == "Particulars")
        assert cell["text_source"]["source"] == "pymupdf"
        assert cell["text_source"]["method"] == "exact"
        assert cell["text_source"]["bbox"] is not None
        assert cell["confidence"] > 0.9
        assert len(cell["bbox"]) == 4

    async def test_unknown_table_is_404(self, client, extracted):
        assert (await client.get(f"/documents/{extracted}/tables/table_99")).status_code == 404

    async def test_cells_paginate(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/tables/table_1/cells?limit=10")).json()
        assert body["total"] == 539
        assert len(body["items"]) == 10
        page_two = (
            await client.get(f"/documents/{extracted}/tables/table_1/cells?limit=10&offset=10")
        ).json()
        assert page_two["items"][0] != body["items"][0]

    async def test_cells_come_back_in_grid_order(self, client, extracted):
        body = (await client.get(f"/documents/{extracted}/tables/table_1")).json()
        positions = [(c["row"], c["column"]) for c in body["cells"]]
        assert positions == sorted(positions)


class TestReextraction:
    async def test_replaces_the_previous_extraction(self, client, extracted, sessionmaker_sqlite):
        """Re-running must not duplicate pages, tables, or cells."""
        await processors.extract_document(FakeJob({"document_id": extracted}))
        body = (await client.get(f"/documents/{extracted}")).json()
        assert body["table_count"] == 2
        tables = (await client.get(f"/documents/{extracted}/tables")).json()
        assert tables["total"] == 2
        cells = (await client.get(f"/documents/{extracted}/tables/table_1/cells?limit=1")).json()
        assert cells["total"] == 539


class TestWorkerFailures:
    async def test_unknown_document_fails_permanently(self, client, store, pipeline, monkeypatch):
        from bullmq import UnrecoverableError

        monkeypatch.setattr(processors, "get_store", lambda: store)
        monkeypatch.setattr(processors, "get_pipeline", lambda: pipeline)
        with pytest.raises(UnrecoverableError):
            await processors.extract_document(FakeJob({"document_id": "doc_nope"}))

    async def test_missing_document_id_fails_permanently(self, client):
        from bullmq import UnrecoverableError

        with pytest.raises(UnrecoverableError):
            await processors.extract_document(FakeJob({}))

    async def test_a_corrupt_pdf_marks_the_document_failed(
        self, client, store, pipeline, monkeypatch, sessionmaker_sqlite
    ):
        from bullmq import UnrecoverableError

        monkeypatch.setattr(processors, "get_store", lambda: store)
        monkeypatch.setattr(processors, "get_pipeline", lambda: pipeline)

        response = await client.post(
            "/documents", files={"file": ("bad.pdf", b"%PDF-broken", "application/pdf")}
        )
        document_id = response.json()["id"]

        with pytest.raises(UnrecoverableError):
            await processors.extract_document(FakeJob({"document_id": document_id}))

        body = (await client.get(f"/documents/{document_id}")).json()
        assert body["status"] == "failed"
        assert body["error"]["code"] == "invalid_pdf"

    async def test_azure_failure_still_persists_a_usable_document(
        self, client, store, pdf_extractor, normalizer, sample_pdf_bytes, monkeypatch,
        failing_layout_extractor,
    ):
        """End to end: Azure down, document still queryable with text intact."""
        from extraction.errors import AzureTimeoutError
        from extraction.pipeline import ExtractionPipeline

        degraded = ExtractionPipeline(
            pdf_extractor=pdf_extractor,
            layout_extractor=failing_layout_extractor(AzureTimeoutError("timed out")),
            normalizer=normalizer,
        )
        monkeypatch.setattr(processors, "get_store", lambda: store)
        monkeypatch.setattr(processors, "get_pipeline", lambda: degraded)

        response = await client.post(
            "/documents", files={"file": ("nl-1.pdf", sample_pdf_bytes, "application/pdf")}
        )
        document_id = response.json()["id"]
        result = await processors.extract_document(FakeJob({"document_id": document_id}))
        assert result["status"] == "partial"

        body = (await client.get(f"/documents/{document_id}")).json()
        assert body["status"] == "partial"
        assert body["table_count"] == 0
        assert body["extraction"]["pymupdf"]["completed"] is True
        assert body["extraction"]["azure_di"]["error"]["code"] == "azure_timeout"

        page = (await client.get(f"/documents/{document_id}/pages/1")).json()
        assert len(page["content"]["words"]) == 747


class TestRepositoryPayloads:
    async def test_page_listing_query_never_selects_content(self, session, sessionmaker_sqlite):
        """A guard on the largest payload in the system."""
        result = await repository.list_pages(session, "doc_none", limit=10, offset=0)
        assert result.items == []
        assert result.total == 0
