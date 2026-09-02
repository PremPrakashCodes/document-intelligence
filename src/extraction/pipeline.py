"""The extraction pipeline: run both extractors, normalize, never lose work.

The one rule this module exists to enforce: **a failure in Azure DI must never
discard a successful PyMuPDF extraction**. PyMuPDF runs first and its failure
is fatal (there is no document without it); Azure runs second and its failure
is recorded as data, leaving a `PARTIAL` document that still has text,
coordinates, geometry, and metadata - everything except tables.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from extraction.azure_di import AzureLayout, LayoutExtractor
from extraction.errors import ExtractionFailure
from extraction.matcher import TableMatcher
from extraction.normalizer import DocumentNormalizer
from extraction.pymupdf_extractor import PdfExtractor
from extraction.types import (
    CanonicalDocument,
    DocumentInfo,
    DocumentStatus,
    ExtractionError,
    ExtractorRun,
    Page,
)

log = logging.getLogger(__name__)


class ExtractionPipeline:
    """Composes the extractors, the matcher, and the normalizer.

    Every collaborator is injected, so a test can drive the whole pipeline with
    a recorded Azure layout and no network, and a deployment without Azure
    credentials degrades to PyMuPDF-only without a special code path.
    """

    def __init__(
        self,
        *,
        pdf_extractor: PdfExtractor,
        layout_extractor: LayoutExtractor | None,
        normalizer: DocumentNormalizer,
    ) -> None:
        self._pdf = pdf_extractor
        self._layout = layout_extractor
        self._normalizer = normalizer

    async def run(self, data: bytes, *, document_id: str, filename: str) -> CanonicalDocument:
        """Extract `data` into a canonical document.

        Raises only when PyMuPDF itself fails; every Azure outcome is folded
        into the returned document's `extraction` record.
        """
        pages, info, pymupdf_run = await asyncio.to_thread(
            self._run_pymupdf, data, document_id, filename
        )
        layout, azure_run = await self._run_azure(data)

        pages, extraction = self._normalizer.build(
            info=info,
            pages=pages,
            layout=layout,
            pymupdf_run=pymupdf_run,
            azure_run=azure_run,
        )

        status = DocumentStatus.COMPLETED if azure_run.completed else DocumentStatus.PARTIAL
        return CanonicalDocument(
            document=info.model_copy(update={"status": status}),
            pages=pages,
            extraction=extraction,
        )

    async def aclose(self) -> None:
        """Release the Azure client's HTTP transport.

        The aio SDK holds an aiohttp session and connection pool; without this
        a process exits complaining about an unclosed session, and long-running
        workers leak a connector per pipeline.
        """
        close = getattr(self._layout, "close", None)
        if close is not None:
            await close()

    async def render_page(self, data: bytes, page_index: int, *, scale: float = 2.0) -> bytes:
        """Render one page of `data` to PNG, off the event loop.

        Lives on the pipeline so callers never need the extractor itself, and
        so rendering is guaranteed to use the same configuration - and so the
        same display space - as the extraction that produced the coordinates.
        """

        def render() -> bytes:
            doc = self._pdf.open(data)
            try:
                return self._pdf.render_page(doc, page_index, scale=scale)
            finally:
                doc.close()

        return await asyncio.to_thread(render)

    # --- stages -------------------------------------------------------------

    def _run_pymupdf(
        self, data: bytes, document_id: str, filename: str
    ) -> tuple[list[Page], DocumentInfo, ExtractorRun]:
        """PyMuPDF is synchronous and CPU-bound, so callers push it to a thread."""
        started = time.monotonic()
        doc = self._pdf.open(data)
        try:
            pages = self._pdf.extract_pages(doc)
            info = DocumentInfo(
                id=document_id,
                filename=filename,
                page_count=doc.page_count,
                file_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                status=DocumentStatus.PROCESSING,
                metadata=self._pdf.metadata(doc),
                is_encrypted=bool(doc.is_encrypted),
            )
        finally:
            doc.close()

        run = ExtractorRun(
            completed=True,
            version=self._pdf.version,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return pages, info, run

    async def _run_azure(self, data: bytes) -> tuple[AzureLayout | None, ExtractorRun]:
        """Analyse with Azure DI, converting any failure into a record."""
        if self._layout is None or not self._layout.configured:
            return None, ExtractorRun(
                completed=False,
                model=self._layout.model if self._layout else None,
                error=ExtractionError(
                    code="azure_not_configured",
                    message="Azure Document Intelligence is not configured; tables were not extracted",
                    retryable=False,
                ),
            )

        started = time.monotonic()
        try:
            layout = await self._layout.analyze(data)
        except ExtractionFailure as err:
            log.warning("azure di failed (%s): %s", err.code, err.message)
            return None, ExtractorRun(
                completed=False,
                model=self._layout.model,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=ExtractionError(code=err.code, message=err.message, retryable=err.retryable),
            )
        except Exception as err:  # a bug here must not lose the PyMuPDF half
            log.exception("unexpected azure di failure")
            return None, ExtractorRun(
                completed=False,
                model=self._layout.model,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=ExtractionError(code="azure_unexpected_error", message=str(err), retryable=True),
            )

        return layout, ExtractorRun(
            completed=True,
            model=layout.model_id,
            duration_ms=layout.duration_ms or int((time.monotonic() - started) * 1000),
            attempts=layout.attempts,
        )


def build_pipeline(settings, *, layout_extractor: LayoutExtractor | None = None) -> ExtractionPipeline:
    """Wire a pipeline from settings, with the Azure client left overridable."""
    from extraction.azure_di import AzureDocumentIntelligenceExtractor, RetryPolicy

    if layout_extractor is None:
        layout_extractor = AzureDocumentIntelligenceExtractor(
            endpoint=settings.azure_di_endpoint,
            key=settings.azure_di_key,
            model=settings.azure_di_model,
            timeout=settings.azure_di_timeout,
            retry=RetryPolicy(
                max_attempts=settings.azure_di_max_attempts,
                backoff_seconds=settings.azure_di_backoff_seconds,
            ),
        )

    matcher = TableMatcher(
        word_containment_threshold=settings.cell_word_containment_threshold,
        cell_containment_threshold=settings.cell_match_containment_threshold,
    )
    return ExtractionPipeline(
        pdf_extractor=PdfExtractor(text_layer_min_chars=settings.text_layer_min_chars),
        layout_extractor=layout_extractor,
        normalizer=DocumentNormalizer(matcher, text_layer_min_chars=settings.text_layer_min_chars),
    )
