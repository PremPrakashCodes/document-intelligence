"""Azure Document Intelligence: table structure, layout, and OCR.

Azure owns what a PDF cannot state about itself - which rectangles form a
table, how they divide into rows and columns, and what scanned pixels say.
It never supplies metadata, page geometry, or born-digital text; PyMuPDF does.

The service's own SDK types stop at this module's edge. Everything downstream
sees the plain dataclasses below, which keeps the normalizer, the matcher, and
their tests free of Azure imports and makes a recorded fixture a first-class
substitute for the live service.

Two details are worth knowing:

* **Coordinates.** Polygons are 4 points in the units named by
  `AzurePage.unit` - "inch" for PDFs, "pixel" for images - on a page Azure has
  already rotated upright. Conversion to points happens in the normalizer,
  which knows the matching PyMuPDF page size.
* **Confidence.** `DocumentTableCell` has no confidence field; only words do.
  A cell's confidence is therefore derived here, by averaging the words whose
  character spans fall inside the cell's spans.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from extraction.errors import (
    AzureAuthError,
    AzureNotConfiguredError,
    AzureRateLimitError,
    AzureServiceError,
    AzureTimeoutError,
    AzureUnsupportedDocumentError,
    ExtractionFailure,
)

log = logging.getLogger(__name__)

# Service error codes that mean "these bytes will never analyse", so the job
# should fail fast rather than burn its retry budget.
_PERMANENT_CODES = frozenset(
    {
        "InvalidRequest",
        "InvalidContent",
        "InvalidContentDimensions",
        "UnsupportedContent",
        "InvalidArgument",
        "ContentSourceNotAccessible",
        "InvalidContentSourceFormat",
    }
)


# --- SDK-independent result shape ------------------------------------------


@dataclass(frozen=True, slots=True)
class AzureSpan:
    """A character range into `AzureLayout.content`."""

    offset: int
    length: int

    @property
    def end(self) -> int:
        return self.offset + self.length

    def overlaps(self, other: AzureSpan) -> bool:
        return self.offset < other.end and other.offset < self.end


@dataclass(frozen=True, slots=True)
class AzureWord:
    content: str
    polygon: tuple[float, ...]
    confidence: float | None
    span: AzureSpan | None


@dataclass(frozen=True, slots=True)
class AzurePage:
    page_number: int
    width: float
    height: float
    # "inch" for PDF input, "pixel" for images.
    unit: str
    # Detected skew in degrees; not the /Rotate quarter-turn, which Azure has
    # already applied.
    angle: float | None
    words: tuple[AzureWord, ...] = ()


@dataclass(frozen=True, slots=True)
class AzureCell:
    row_index: int
    column_index: int
    row_span: int
    column_span: int
    content: str
    kind: str
    page_number: int | None
    polygon: tuple[float, ...] | None
    spans: tuple[AzureSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class AzureTable:
    row_count: int
    column_count: int
    page_number: int | None
    polygon: tuple[float, ...] | None
    caption: str | None
    cells: tuple[AzureCell, ...] = ()
    spans: tuple[AzureSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class AzureParagraph:
    content: str
    role: str | None
    page_number: int | None
    polygon: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class AzureLayout:
    """One `prebuilt-layout` analysis, flattened."""

    model_id: str
    content: str = ""
    pages: tuple[AzurePage, ...] = ()
    tables: tuple[AzureTable, ...] = ()
    paragraphs: tuple[AzureParagraph, ...] = ()
    attempts: int = 1
    duration_ms: int = 0

    def page(self, page_number: int) -> AzurePage | None:
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None

    def cell_confidence(self, page_number: int, spans: Sequence[AzureSpan]) -> float | None:
        """Mean confidence of the words covered by `spans` on `page_number`.

        Azure reports confidence per word, not per cell, so a cell's number is
        the average over the words it contains. Returns None when no word in
        range carried a confidence - usual for born-digital PDFs, where the
        service reads embedded text instead of running OCR - so the UI can say
        "not reported" rather than implying a zero-confidence read.
        """
        page = self.page(page_number)
        if page is None or not spans:
            return None
        scores = [
            word.confidence
            for word in page.words
            if word.confidence is not None
            and word.span is not None
            and any(word.span.overlaps(span) for span in spans)
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)


@runtime_checkable
class LayoutExtractor(Protocol):
    """The seam the pipeline depends on, so the service can be swapped out."""

    @property
    def model(self) -> str: ...

    @property
    def configured(self) -> bool: ...

    async def analyze(self, data: bytes) -> AzureLayout: ...


# --- SDK mapping ------------------------------------------------------------


def _enum_str(value, default: str = "") -> str:
    """The wire value of an SDK field that may arrive as a str or an enum.

    The SDK types several string fields as enums that only sometimes
    deserialize as one - `kind` comes back as the plain "content" for a body
    cell but as `DocumentTableCellKind.COLUMN_HEADER` for a header. Bare
    `str()` would persist the Python repr, so the enum's own value is taken
    whenever there is one.
    """
    if value is None:
        return default
    return str(getattr(value, "value", value))


def _span(raw) -> AzureSpan | None:
    if raw is None:
        return None
    return AzureSpan(offset=int(raw.offset or 0), length=int(raw.length or 0))


def _spans(raw) -> tuple[AzureSpan, ...]:
    return tuple(span for span in (_span(item) for item in (raw or [])) if span is not None)


def _region(raw_regions) -> tuple[int | None, tuple[float, ...] | None]:
    """First bounding region as `(page_number, polygon)`.

    A table that continues across a page break carries several regions; the
    first is the one that anchors it, and the continuation is stitched back on
    in the normalizer.
    """
    regions = raw_regions or []
    if not regions:
        return None, None
    first = regions[0]
    polygon = tuple(float(v) for v in (first.polygon or ())) or None
    return (int(first.page_number) if first.page_number is not None else None), polygon


def layout_from_sdk(result, model_id: str, *, attempts: int = 1, duration_ms: int = 0) -> AzureLayout:
    """Flatten an `AnalyzeResult` into the plain shape above.

    Kept module-level and free of client state so a recorded JSON fixture can
    be replayed through `AnalyzeResult` and land in exactly the same place as a
    live call.
    """
    pages: list[AzurePage] = []
    for raw_page in result.pages or []:
        words = tuple(
            AzureWord(
                content=word.content or "",
                polygon=tuple(float(v) for v in (word.polygon or ())),
                confidence=float(word.confidence) if word.confidence is not None else None,
                span=_span(word.span),
            )
            for word in (raw_page.words or [])
        )
        pages.append(
            AzurePage(
                page_number=int(raw_page.page_number),
                width=float(raw_page.width or 0.0),
                height=float(raw_page.height or 0.0),
                unit=_enum_str(raw_page.unit, "inch"),
                angle=float(raw_page.angle) if raw_page.angle is not None else None,
                words=words,
            )
        )

    tables: list[AzureTable] = []
    for raw_table in result.tables or []:
        table_page, table_polygon = _region(raw_table.bounding_regions)
        cells: list[AzureCell] = []
        for raw_cell in raw_table.cells or []:
            cell_page, cell_polygon = _region(raw_cell.bounding_regions)
            cells.append(
                AzureCell(
                    row_index=int(raw_cell.row_index),
                    column_index=int(raw_cell.column_index),
                    row_span=int(raw_cell.row_span or 1),
                    column_span=int(raw_cell.column_span or 1),
                    content=raw_cell.content or "",
                    kind=_enum_str(raw_cell.kind, "content") or "content",
                    page_number=cell_page if cell_page is not None else table_page,
                    polygon=cell_polygon,
                    spans=_spans(raw_cell.spans),
                )
            )
        caption = getattr(raw_table.caption, "content", None) if raw_table.caption else None
        tables.append(
            AzureTable(
                row_count=int(raw_table.row_count or 0),
                column_count=int(raw_table.column_count or 0),
                page_number=table_page,
                polygon=table_polygon,
                caption=caption,
                cells=tuple(cells),
                spans=_spans(raw_table.spans),
            )
        )

    paragraphs: list[AzureParagraph] = []
    for raw_paragraph in result.paragraphs or []:
        page_number, polygon = _region(raw_paragraph.bounding_regions)
        paragraphs.append(
            AzureParagraph(
                content=raw_paragraph.content or "",
                role=_enum_str(raw_paragraph.role) or None,
                page_number=page_number,
                polygon=polygon,
            )
        )

    return AzureLayout(
        model_id=model_id,
        content=result.content or "",
        pages=tuple(pages),
        tables=tuple(tables),
        paragraphs=tuple(paragraphs),
        attempts=attempts,
        duration_ms=duration_ms,
    )


# --- the extractor ----------------------------------------------------------


@dataclass(slots=True)
class RetryPolicy:
    """Exponential backoff with full jitter, capped by `max_attempts`.

    Hand-rolled rather than pulled from a library: the whole policy is the
    twenty lines below, and `Retry-After` has to override the curve anyway.
    """

    max_attempts: int = 4
    backoff_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    # Injectable so tests are instant and deterministic.
    sleep: object = field(default=None)

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        """Seconds to wait before `attempt` + 1. `retry_after` always wins."""
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, self.max_delay_seconds)
        ceiling = min(self.backoff_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
        # Full jitter: uniform over [0, ceiling] spreads a thundering herd of
        # workers far better than a fixed curve with a small random addend.
        return random.uniform(0.0, ceiling)


class AzureDocumentIntelligenceExtractor:
    """Calls `prebuilt-layout`, with typed failures and bounded retries.

    The client is built lazily and cached, so constructing this without Azure
    credentials is harmless - `configured` reports False and `analyze` raises
    `AzureNotConfiguredError`, which the pipeline records as a recoverable
    Azure failure while keeping the PyMuPDF half of the extraction.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        key: str,
        model: str = "prebuilt-layout",
        timeout: float = 300.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._key = key
        self._model = model
        self._timeout = timeout
        self._retry = retry or RetryPolicy()
        self._client = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def configured(self) -> bool:
        return bool(self._endpoint and self._key)

    def _get_client(self):
        if self._client is None:
            # Imported here so the module loads without the SDK installed and
            # so an unconfigured deployment never builds a transport.
            from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential

            self._client = DocumentIntelligenceClient(
                endpoint=self._endpoint,
                credential=AzureKeyCredential(self._key),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def analyze(self, data: bytes) -> AzureLayout:
        """Analyse `data`, retrying only failures that could plausibly clear."""
        if not self.configured:
            raise AzureNotConfiguredError(
                "AZURE_DI_ENDPOINT and AZURE_DI_KEY are not set; skipping table extraction"
            )

        started = time.monotonic()
        last: ExtractionFailure | None = None

        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                result = await self._analyze_once(data)
            except ExtractionFailure as err:
                last = err
                if not err.retryable or attempt == self._retry.max_attempts:
                    raise
                delay = self._retry.delay_for(attempt, getattr(err, "retry_after", None))
                log.warning(
                    "azure di attempt %d/%d failed (%s); retrying in %.1fs",
                    attempt,
                    self._retry.max_attempts,
                    err.code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            duration_ms = int((time.monotonic() - started) * 1000)
            return layout_from_sdk(result, self._model, attempts=attempt, duration_ms=duration_ms)

        # Unreachable: the loop either returns or re-raises on the last attempt.
        raise last or AzureServiceError("Azure Document Intelligence failed")

    async def _analyze_once(self, data: bytes):
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        client = self._get_client()
        try:
            async with asyncio.timeout(self._timeout):
                poller = await client.begin_analyze_document(
                    self._model,
                    AnalyzeDocumentRequest(bytes_source=data),
                )
                return await poller.result()
        except TimeoutError as err:
            raise AzureTimeoutError(
                f"Azure Document Intelligence did not respond within {self._timeout:.0f}s"
            ) from err
        except Exception as err:
            raise map_azure_error(err) from err


def map_azure_error(err: Exception) -> ExtractionFailure:
    """Translate an SDK or transport exception into a typed failure.

    Retryability is decided here, once, so the retry loop stays free of
    HTTP-status reasoning and the same judgement reaches the stored error.
    """
    from azure.core.exceptions import (
        ClientAuthenticationError,
        ServiceRequestError,
        ServiceResponseError,
    )

    if isinstance(err, ExtractionFailure):
        return err

    if isinstance(err, ClientAuthenticationError):
        return AzureAuthError("Azure Document Intelligence rejected the credentials")

    # Network-level: the request never landed, or the response was cut off.
    if isinstance(err, (ServiceRequestError, ServiceResponseError)):
        return AzureServiceError(f"Could not reach Azure Document Intelligence: {err}")

    status = getattr(err, "status_code", None)
    code = getattr(getattr(err, "error", None), "code", None)
    message = getattr(err, "message", None) or str(err)

    if status in (401, 403):
        return AzureAuthError(f"Azure Document Intelligence rejected the credentials: {message}")
    if status == 429:
        failure = AzureRateLimitError(f"Azure Document Intelligence rate limit reached: {message}")
        failure.retry_after = _retry_after(err)
        return failure
    if status == 408 or status == 504:
        return AzureTimeoutError(f"Azure Document Intelligence timed out: {message}")
    if code in _PERMANENT_CODES or (status is not None and 400 <= status < 500 and status != 429):
        return AzureUnsupportedDocumentError(
            f"Azure Document Intelligence could not process the document: {message}"
        )

    failure = AzureServiceError(f"Azure Document Intelligence failed: {message}")
    failure.retry_after = _retry_after(err)
    return failure


def _retry_after(err: Exception) -> float | None:
    """The service's own `Retry-After`, in seconds, when it sent one."""
    response = getattr(err, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # The header may be an HTTP-date; the backoff curve covers that case.
        return None
