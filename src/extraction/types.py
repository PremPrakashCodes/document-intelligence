"""The canonical document schema.

Every value carries its provenance. Nothing here merges PyMuPDF and Azure DI
into an anonymous blob: a cell keeps the Azure text, the PyMuPDF text, which
one was chosen, and why. See `docs/extraction.md` for the full contract.

All bounding boxes are in page display space (see `geometry`).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from extraction.geometry import BBoxTuple


class Source(StrEnum):
    """Which extractor a value came from."""

    PYMUPDF = "pymupdf"
    AZURE_DI = "azure_di"


class MatchMethod(StrEnum):
    """How a cell's text was resolved against the PyMuPDF text layer."""

    # PyMuPDF words fell inside the cell and their concatenation equals the
    # Azure DI content once whitespace is normalized. Highest confidence.
    EXACT = "exact"
    # Words fell inside the cell with strong spatial agreement, but the text
    # differs from Azure's reading (ligatures, OCR variance, currency glyphs).
    SPATIAL = "spatial"
    # Words were found but the spatial agreement was too weak to prefer them.
    WEAK = "weak"
    # No PyMuPDF words inside the cell at all - a scanned page, or an
    # genuinely empty cell.
    NONE = "none"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    # Both extractors finished.
    COMPLETED = "completed"
    # PyMuPDF finished, Azure DI did not. The document is still usable.
    PARTIAL = "partial"
    # PyMuPDF itself failed; there is nothing to show.
    FAILED = "failed"


class CanonicalModel(BaseModel):
    """Base for every canonical model: immutable, and strict about extras."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- PyMuPDF primitives -----------------------------------------------------


class Span(CanonicalModel):
    """A run of characters sharing one font, size, and style."""

    text: str
    bbox: BBoxTuple
    font: str
    size: float
    # PyMuPDF's packed style flags (superscript, italic, serif, mono, bold).
    flags: int = 0
    color: int = 0


class Line(CanonicalModel):
    bbox: BBoxTuple
    # Writing direction as a unit vector; (1, 0) is normal left-to-right.
    direction: tuple[float, float] = (1.0, 0.0)
    spans: list[Span] = Field(default_factory=list)


class Block(CanonicalModel):
    """A text or image block, in PyMuPDF's own block order."""

    number: int
    # "text" or "image" - PyMuPDF block types 0 and 1.
    type: str
    bbox: BBoxTuple
    lines: list[Line] = Field(default_factory=list)


class Word(CanonicalModel):
    """A whitespace-delimited word with its own box - the matcher's atom."""

    text: str
    bbox: BBoxTuple
    block: int
    line: int
    word: int


class Image(CanonicalModel):
    xref: int
    bbox: BBoxTuple
    width: int
    height: int
    colorspace: str | None = None
    bits_per_component: int | None = None


class Link(CanonicalModel):
    # PyMuPDF's LINK_* kind, as a name: "uri", "goto", "launch", ...
    kind: str
    bbox: BBoxTuple
    uri: str | None = None
    target_page: int | None = None


class Annotation(CanonicalModel):
    type: str
    bbox: BBoxTuple
    content: str | None = None
    author: str | None = None


class Font(CanonicalModel):
    xref: int
    name: str
    type: str
    encoding: str | None = None
    embedded: bool = False


class PageGeometry(CanonicalModel):
    """Page size in display space, plus the rotation already applied to it."""

    width: float
    height: float
    rotation: int
    # The unrotated mediabox, kept so a caller can retrace the transform.
    mediabox: BBoxTuple


class PageContent(CanonicalModel):
    """Everything PyMuPDF knows about one page."""

    text: str
    blocks: list[Block] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    fonts: list[Font] = Field(default_factory=list)


# --- Azure DI structure, normalized ----------------------------------------


class TextSource(CanonicalModel):
    """Provenance for one cell's text: what matched, how well, and from where."""

    source: Source
    matched: bool
    method: MatchMethod
    # Fraction of the matched words' area that falls inside the cell. This is
    # the decision variable: it asks "do these words belong to this cell?"
    # independently of how much blank padding the cell has.
    containment: float = 0.0
    # IoU between the cell and the words' union. Diagnostic only - it scales
    # with cell padding, so a lone "-" in a wide column scores ~0.05 while
    # sitting perfectly inside it. Reported so a reviewer can see the geometry,
    # never used to accept or reject a match.
    iou: float = 0.0
    # Union of the matched PyMuPDF words - what to highlight in the PDF.
    bbox: BBoxTuple | None = None
    word_count: int = 0


class TableCell(CanonicalModel):
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1
    # Azure's cell role: "content", "columnHeader", "rowHeader", ...
    kind: str = "content"

    # The chosen value. Equal to `pymupdf_text` on a strong match, otherwise to
    # `azure_text`. Both inputs are kept so the choice is always auditable.
    text: str
    azure_text: str
    pymupdf_text: str | None = None

    bbox: BBoxTuple
    # Mean OCR confidence of the Azure words inside this cell; None when the
    # service reported no per-word confidence (born-digital PDFs often do not).
    confidence: float | None = None
    text_source: TextSource


class Table(CanonicalModel):
    id: str
    source: Source = Source.AZURE_DI
    page_number: int
    bbox: BBoxTuple
    row_count: int
    column_count: int
    caption: str | None = None
    # Mean of the cells' confidences, or None when none of them had one.
    confidence: float | None = None
    # Set when this table continues one from an earlier page.
    continues_table_id: str | None = None
    cells: list[TableCell] = Field(default_factory=list)


class Paragraph(CanonicalModel):
    page_number: int
    # Azure's semantic role: "title", "sectionHeading", "pageHeader", ...
    role: str | None = None
    content: str
    bbox: BBoxTuple | None = None


# --- Document ---------------------------------------------------------------


class Page(CanonicalModel):
    page_number: int
    geometry: PageGeometry
    # False when the page carries too little embedded text to be usable, i.e.
    # it is scanned and its words must come from Azure DI's OCR.
    has_text_layer: bool
    content: PageContent
    tables: list[Table] = Field(default_factory=list)


class ExtractionError(CanonicalModel):
    code: str
    message: str
    # True when a retry could plausibly succeed (timeout, 429, 5xx).
    retryable: bool = False


class ExtractorRun(CanonicalModel):
    """The outcome of one extractor, successful or not."""

    completed: bool
    version: str | None = None
    model: str | None = None
    duration_ms: int | None = None
    attempts: int = 1
    error: ExtractionError | None = None


class MatchingStats(CanonicalModel):
    """How well the two sources agreed - the headline audit number.

    Empty cells are counted separately and excluded from `match_rate`. A real
    filing table is mostly blank grid: nl-1.pdf has 714 cells of which 343 hold
    nothing at all. Counting those as match failures would report a 52% match
    rate for an extraction that in fact resolved 369 of 371 populated cells
    exactly - an operator would rightly stop trusting the number.
    """

    total_cells: int = 0
    # Cells with no text from either source: blank grid, not a failure.
    empty_cells: int = 0
    matched_cells: int = 0
    exact_matches: int = 0
    spatial_matches: int = 0
    # Populated cells the text layer could not confirm. On a born-digital PDF
    # these are worth a look; on a scanned one, every cell lands here.
    unmatched_cells: int = 0

    @property
    def content_cells(self) -> int:
        return self.total_cells - self.empty_cells

    @property
    def match_rate(self) -> float:
        """Fraction of *populated* cells confirmed against the text layer."""
        return self.matched_cells / self.content_cells if self.content_cells else 0.0


class MatchingConfig(CanonicalModel):
    """The thresholds this document was extracted with.

    Persisted with the result so a stored document can be explained even after
    the defaults change.
    """

    word_containment_threshold: float
    cell_containment_threshold: float
    text_layer_min_chars: int


class Extraction(CanonicalModel):
    pymupdf: ExtractorRun
    azure_di: ExtractorRun
    matching: MatchingStats = MatchingStats()
    config: MatchingConfig | None = None
    extracted_at: datetime | None = None


class DocumentInfo(CanonicalModel):
    id: str
    filename: str
    mime_type: str = "application/pdf"
    page_count: int
    file_size: int
    sha256: str
    status: DocumentStatus
    # PDF /Info dictionary: title, author, producer, creationDate, ...
    metadata: dict[str, str] = Field(default_factory=dict)
    # True when the PDF was encrypted but opened with an empty owner password.
    is_encrypted: bool = False


class CanonicalDocument(CanonicalModel):
    """The complete, self-describing extraction result."""

    document: DocumentInfo
    pages: list[Page] = Field(default_factory=list)
    extraction: Extraction

    @property
    def tables(self) -> list[Table]:
        return [table for page in self.pages for table in page.tables]
