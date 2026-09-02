"""Serve the synthetic sample document, for the README screenshots.

The screenshots have to show a *fully extracted* document, which normally
means R2, a live Azure DI call and a worker. None of that is wanted just to
take a picture, and pointing a screenshot run at a real dev database risks
putting someone's actual filing in the README.

So this seeds a throwaway `demo` database straight from the test fixture -
the same replayed layout the suite uses - and serves the PDF from an
in-process store via a dependency override. No network, no R2, no Azure, and
the dev database is never touched.

    createdb / migrate:
        docker exec <postgres> psql -U postgres -c "CREATE DATABASE demo"
        DATABASE_URL=postgresql://postgres:password@localhost:5432/demo \
            uv run alembic upgrade head

    run:
        uv run python scripts/screenshots/serve_sample.py   # API on :8001
        cd web && VITE_API_URL=http://127.0.0.1:8001 npx vite --port 5199
        node scripts/screenshots/capture.mjs               # needs playwright
"""
import asyncio, hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import os
os.environ["DATABASE_URL"] = "postgresql://postgres:password@localhost:5432/demo"
os.environ["R2_ACCESS_KEY_ID"] = ""
os.environ["R2_SECRET_ACCESS_KEY"] = ""
os.environ["R2_BUCKET_NAME"] = ""
os.environ["CORS_ORIGINS"] = "http://localhost:5199,http://127.0.0.1:5199"

from azure.ai.documentintelligence.models import AnalyzeResult
from api.config import Settings, get_settings
from api.deps import get_store
from api.main import app
from db import repository
from db.session import session_scope
from extraction.azure_di import layout_from_sdk
from extraction.matcher import TableMatcher
from extraction.normalizer import DocumentNormalizer
from extraction.pipeline import ExtractionPipeline
from extraction.pymupdf_extractor import PdfExtractor
from storage.base import document_key
from storage.memory import InMemoryDocumentStore

F = ROOT / "tests" / "fixtures"
PDF = (F / "sample-revenue-account.pdf").read_bytes()
DOC_ID = "doc_sample0000demo"
STORE = InMemoryDocumentStore()


class Replay:
    model, configured = "prebuilt-layout", True

    def __init__(self, layout):
        self._layout = layout

    async def analyze(self, data):
        return self._layout


async def seed() -> None:
    s = get_settings()
    layout = layout_from_sdk(
        AnalyzeResult(json.loads((F / "sample-revenue-account.layout.json").read_text())),
        "prebuilt-layout",
    )
    matcher = TableMatcher(
        word_containment_threshold=s.cell_word_containment_threshold,
        cell_containment_threshold=s.cell_match_containment_threshold,
    )
    pipeline = ExtractionPipeline(
        pdf_extractor=PdfExtractor(text_layer_min_chars=s.text_layer_min_chars),
        layout_extractor=Replay(layout),
        normalizer=DocumentNormalizer(matcher, text_layer_min_chars=s.text_layer_min_chars),
    )
    canonical = await pipeline.run(PDF, document_id=DOC_ID, filename="sample-revenue-account.pdf")

    async with session_scope() as session:
        if await repository.get_document(session, DOC_ID) is None:
            await repository.create_document(
                session,
                document_id=DOC_ID,
                filename="sample-revenue-account.pdf",
                file_size=len(PDF),
                sha256=hashlib.sha256(PDF).hexdigest(),
            )
        await repository.save_extraction(session, canonical)

    await STORE.put(document_key(DOC_ID), PDF)
    st = canonical.extraction.matching
    print(f"seeded {DOC_ID}: {len(canonical.tables)} tables, "
          f"{st.total_cells} cells, match rate {st.match_rate:.0%}")


app.dependency_overrides[get_store] = lambda: STORE

if __name__ == "__main__":
    import uvicorn
    asyncio.run(seed())
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
