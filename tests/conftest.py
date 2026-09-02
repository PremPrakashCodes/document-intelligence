"""Shared fixtures.

The suite runs with no network and no Postgres: Azure is replayed from a
recorded response, storage is in-memory, and the database is SQLite through the
same SQLAlchemy models the app uses in Postgres.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import Settings
from db.models import Base
from extraction.azure_di import AzureLayout, layout_from_sdk
from extraction.matcher import TableMatcher
from extraction.normalizer import DocumentNormalizer
from extraction.pipeline import ExtractionPipeline
from extraction.pymupdf_extractor import PdfExtractor
from storage.memory import InMemoryDocumentStore

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# A real IRDAI NL-1 revenue account: landscape A4, born-digital, two wide
# financial tables, and the straddling nil-marker dashes the matcher exists to
# get right.
SAMPLE_PDF = pathlib.Path(__file__).parents[1] / "nl-1.pdf"
SAMPLE_LAYOUT = FIXTURES / "nl-1.layout.json"


class ReplayLayoutExtractor:
    """A `LayoutExtractor` that replays a recorded Azure response.

    Recorded from the live `prebuilt-layout` model against nl-1.pdf, so the
    matcher and normalizer are exercised on genuine service output - real
    polygons in inches, real per-word confidences, real quirks - rather than
    on coordinates invented to make the tests pass.
    """

    model = "prebuilt-layout"
    configured = True

    def __init__(self, layout: AzureLayout) -> None:
        self._layout = layout
        self.calls = 0

    async def analyze(self, data: bytes) -> AzureLayout:
        self.calls += 1
        return self._layout


class FailingLayoutExtractor:
    """A `LayoutExtractor` that always fails, for the degradation tests."""

    model = "prebuilt-layout"
    configured = True

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def analyze(self, data: bytes) -> AzureLayout:
        raise self._error


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        azure_di_endpoint="https://example.invalid/",
        azure_di_key="test-key",
        r2_access_key_id="",
        r2_secret_access_key="",
    )


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    if not SAMPLE_PDF.exists():
        pytest.skip(f"sample PDF not present at {SAMPLE_PDF}")
    return SAMPLE_PDF.read_bytes()


@pytest.fixture(scope="session")
def sample_layout() -> AzureLayout:
    from azure.ai.documentintelligence.models import AnalyzeResult

    raw = json.loads(SAMPLE_LAYOUT.read_text())
    return layout_from_sdk(AnalyzeResult(raw), "prebuilt-layout")


@pytest.fixture
def pdf_extractor(settings: Settings) -> PdfExtractor:
    return PdfExtractor(text_layer_min_chars=settings.text_layer_min_chars)


@pytest.fixture
def matcher(settings: Settings) -> TableMatcher:
    return TableMatcher(
        word_containment_threshold=settings.cell_word_containment_threshold,
        cell_containment_threshold=settings.cell_match_containment_threshold,
    )


@pytest.fixture
def normalizer(matcher: TableMatcher, settings: Settings) -> DocumentNormalizer:
    return DocumentNormalizer(matcher, text_layer_min_chars=settings.text_layer_min_chars)


@pytest.fixture
def pipeline(pdf_extractor, normalizer, sample_layout) -> ExtractionPipeline:
    return ExtractionPipeline(
        pdf_extractor=pdf_extractor,
        layout_extractor=ReplayLayoutExtractor(sample_layout),
        normalizer=normalizer,
    )


@pytest_asyncio.fixture
async def canonical(pipeline, sample_pdf_bytes):
    """The sample document, fully extracted. Session-expensive, so reused."""
    return await pipeline.run(sample_pdf_bytes, document_id="doc_test", filename="nl-1.pdf")


@pytest.fixture
def failing_layout_extractor():
    """The `FailingLayoutExtractor` class, for tests that need Azure to fail.

    Exposed as a fixture because `tests/` is not a package, so test modules
    cannot import from conftest directly.
    """
    return FailingLayoutExtractor


@pytest.fixture
def store() -> InMemoryDocumentStore:
    return InMemoryDocumentStore()


@pytest_asyncio.fixture
async def sessionmaker_sqlite():
    """A throwaway SQLite database with the real schema.

    The models use `JSON().with_variant(JSONB, "postgresql")`, so the same
    mappings run here unchanged - the tests exercise the production model
    definitions, not a parallel set.
    """
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(sessionmaker_sqlite):
    async with sessionmaker_sqlite() as session:
        yield session
        await session.commit()
