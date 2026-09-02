"""Response models for the documents API.

These are the wire format, kept separate from both the ORM rows and the
canonical extraction types. The split earns its keep in two places: responses
expose `table_id` as `id` (the ORM primary key is an internal integer), and
listings can omit heavy fields without weakening the canonical schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from extraction.geometry import BBoxTuple


class Paginated[T](BaseModel):
    """Envelope for every listing, so clients page uniformly."""

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class ExtractorRunOut(BaseModel):
    completed: bool
    version: str | None = None
    model: str | None = None
    duration_ms: int | None = None
    attempts: int = 1
    error: dict[str, Any] | None = None


class MatchingOut(BaseModel):
    total_cells: int = 0
    empty_cells: int = 0
    content_cells: int = 0
    matched_cells: int = 0
    exact_matches: int = 0
    spatial_matches: int = 0
    unmatched_cells: int = 0
    match_rate: float = 0.0


class ExtractionOut(BaseModel):
    pymupdf: ExtractorRunOut
    azure_di: ExtractorRunOut
    matching: MatchingOut = MatchingOut()
    config: dict[str, Any] | None = None
    extracted_at: datetime | None = None


class DocumentSummary(BaseModel):
    """A document without any page or table payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    mime_type: str
    file_size: int
    sha256: str
    page_count: int
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    metadata: dict[str, str] = Field(default_factory=dict)
    is_encrypted: bool = False
    extraction: ExtractionOut | None = None
    error: dict[str, Any] | None = None
    table_count: int = 0


class PageGeometryOut(BaseModel):
    width: float
    height: float
    rotation: int
    mediabox: BBoxTuple


class PageSummary(BaseModel):
    """A page listing entry: geometry and counts, never the word list."""

    page_number: int
    geometry: PageGeometryOut
    has_text_layer: bool
    text_length: int = 0
    table_count: int = 0


class PageDetail(BaseModel):
    page_number: int
    geometry: PageGeometryOut
    has_text_layer: bool
    text: str
    # blocks / words / images / links / annotations / fonts.
    content: dict[str, Any]
    table_ids: list[str] = Field(default_factory=list)


class TextSourceOut(BaseModel):
    source: str
    matched: bool
    method: str
    containment: float = 0.0
    iou: float = 0.0
    bbox: BBoxTuple | None = None
    word_count: int = 0


class TableCellOut(BaseModel):
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1
    kind: str = "content"
    text: str
    azure_text: str
    pymupdf_text: str | None = None
    bbox: BBoxTuple
    confidence: float | None = None
    text_source: TextSourceOut


class TableSummary(BaseModel):
    """Table metadata for a listing - no cells."""

    id: str
    page_number: int
    source: str
    bbox: BBoxTuple
    row_count: int
    column_count: int
    caption: str | None = None
    confidence: float | None = None
    continues_table_id: str | None = None
    cell_count: int = 0


class TableDetail(TableSummary):
    cells: list[TableCellOut] = Field(default_factory=list)


class UploadResponse(BaseModel):
    id: str
    filename: str
    status: str
    # The queued extraction job, when one was enqueued.
    job_id: str | None = None
