"""The normalization layer: canonical documents from two disagreeing sources.

Ownership is strict. PyMuPDF supplies metadata, geometry, text, and every
primitive; Azure DI supplies table structure and confidence. This module maps
Azure's coordinates into PyMuPDF's space, hands each cell to the matcher, and
records what happened. It never invents a value and never drops one: where the
two sources disagree, both readings survive on the cell.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from extraction.azure_di import AzureLayout, AzureTable
from extraction.geometry import (
    BBox,
    clamp_bbox,
    polygon_to_bbox,
    scale_bbox,
    union_bbox,
)
from extraction.matcher import TableMatcher, strip_selection_marks
from extraction.types import (
    DocumentInfo,
    Extraction,
    ExtractorRun,
    MatchingConfig,
    MatchingStats,
    MatchMethod,
    Page,
    Source,
    Table,
    TableCell,
)

log = logging.getLogger(__name__)


class DocumentNormalizer:
    """Folds an Azure layout into pages PyMuPDF already produced."""

    def __init__(self, matcher: TableMatcher, *, text_layer_min_chars: int = 24) -> None:
        self._matcher = matcher
        self._text_layer_min_chars = text_layer_min_chars

    # --- coordinate mapping -------------------------------------------------

    @staticmethod
    def page_scale(page: Page, layout: AzureLayout) -> tuple[float, float]:
        """Azure page units -> PDF points, as an (x, y) pair.

        Derived from the ratio of the two page sizes rather than a fixed 72
        dpi. That is what makes the conversion unit-agnostic - it works
        identically for Azure's "inch" (PDF input) and "pixel" (image input) -
        and it absorbs the sub-percent disagreement the service has with the
        PDF's own mediabox. For the sample document the factors come out at 72.085 and
        71.9999: assuming 72 would misplace the right-hand columns by a point.

        Both pages are already upright, so no rotation enters here: PyMuPDF
        boxes were rotated into display space at extraction time, and Azure
        reports on a page it has itself turned upright.
        """
        azure_page = layout.page(page.page_number)
        if azure_page is None or azure_page.width <= 0 or azure_page.height <= 0:
            return 1.0, 1.0
        return page.geometry.width / azure_page.width, page.geometry.height / azure_page.height

    def _to_display(self, polygon, page: Page, scale: tuple[float, float]) -> BBox | None:
        """An Azure polygon as a clamped, rounded display-space box."""
        if not polygon:
            return None
        box = scale_bbox(polygon_to_bbox(polygon), scale[0], scale[1])
        return clamp_bbox(box, page.geometry.width, page.geometry.height).rounded()

    # --- tables -------------------------------------------------------------

    def normalize_tables(self, pages: list[Page], layout: AzureLayout) -> list[Page]:
        """Return `pages` with Azure's tables attached to the right page.

        Table ids are assigned from Azure's own ordering (`table_1`, `table_2`,
        ...) across the whole document, so an id is stable for a given
        document and reproducible on re-extraction.
        """
        by_number = {page.page_number: page for page in pages}
        indexes = {page.page_number: self._matcher.build_index(page.content.words) for page in pages}
        scales = {page.page_number: self.page_scale(page, layout) for page in pages}
        tables_by_page: dict[int, list[Table]] = {}

        previous_signature: tuple[int, str] | None = None
        previous_id: str | None = None

        for position, azure_table in enumerate(layout.tables, start=1):
            page_number = azure_table.page_number
            page = by_number.get(page_number) if page_number else None
            if page is None:
                log.warning(
                    "azure table %d references page %s, which the PDF does not have; skipping",
                    position,
                    page_number,
                )
                continue

            table_id = f"table_{position}"
            table = self._build_table(
                table_id=table_id,
                azure_table=azure_table,
                page=page,
                layout=layout,
                scale=scales[page.page_number],
                index=indexes[page.page_number],
            )

            # A table continued across a page break keeps Azure's column count
            # and header row. Linking rather than merging preserves both the
            # structure Azure found and the page each row actually sits on.
            signature = (table.column_count, _header_signature(table))
            if (
                previous_signature is not None
                and previous_id is not None
                and signature == previous_signature
                and table.page_number == _page_of(tables_by_page, previous_id) + 1
            ):
                table = table.model_copy(update={"continues_table_id": previous_id})

            previous_signature, previous_id = signature, table_id
            tables_by_page.setdefault(page.page_number, []).append(table)

        return [
            page.model_copy(update={"tables": tables_by_page.get(page.page_number, [])}) for page in pages
        ]

    def _build_table(
        self,
        *,
        table_id: str,
        azure_table: AzureTable,
        page: Page,
        layout: AzureLayout,
        scale: tuple[float, float],
        index,
    ) -> Table:
        cells: list[TableCell] = []
        confidences: list[float] = []

        for azure_cell in azure_table.cells:
            cell_bbox = self._to_display(azure_cell.polygon, page, scale)
            if cell_bbox is None:
                # Azure occasionally omits a region for a cell it inferred
                # rather than saw. Its text and position in the grid are still
                # good; there is simply nothing to match or highlight.
                cells.append(
                    TableCell(
                        row=azure_cell.row_index,
                        column=azure_cell.column_index,
                        row_span=azure_cell.row_span,
                        column_span=azure_cell.column_span,
                        kind=azure_cell.kind,
                        text=strip_selection_marks(azure_cell.content),
                        azure_text=azure_cell.content,
                        pymupdf_text=None,
                        bbox=(0.0, 0.0, 0.0, 0.0),
                        confidence=None,
                        text_source=_unmatched_source(),
                    )
                )
                continue

            match = self._matcher.match_cell(cell_bbox, azure_cell.content, index)
            confidence = layout.cell_confidence(page.page_number, azure_cell.spans)
            if confidence is not None:
                confidences.append(confidence)

            cells.append(
                TableCell(
                    row=azure_cell.row_index,
                    column=azure_cell.column_index,
                    row_span=azure_cell.row_span,
                    column_span=azure_cell.column_span,
                    kind=azure_cell.kind,
                    text=match.text,
                    azure_text=azure_cell.content,
                    pymupdf_text=match.pymupdf_text,
                    bbox=cell_bbox.as_tuple(),
                    confidence=round(confidence, 4) if confidence is not None else None,
                    text_source=match.source,
                )
            )

        # Azure's table polygon is authoritative, but fall back to the hull of
        # the cells when it is missing so the UI always has a region to frame.
        table_bbox = self._to_display(azure_table.polygon, page, scale)
        if table_bbox is None:
            table_bbox = union_bbox(
                [BBox(*cell.bbox) for cell in cells if any(cell.bbox)]
            ) or BBox(0.0, 0.0, page.geometry.width, page.geometry.height)

        return Table(
            id=table_id,
            source=Source.AZURE_DI,
            page_number=page.page_number,
            bbox=table_bbox.as_tuple(),
            row_count=azure_table.row_count,
            column_count=azure_table.column_count,
            caption=azure_table.caption,
            confidence=round(sum(confidences) / len(confidences), 4) if confidences else None,
            cells=sorted(cells, key=lambda cell: (cell.row, cell.column)),
        )

    # --- whole document -----------------------------------------------------

    def build(
        self,
        *,
        info: DocumentInfo,
        pages: list[Page],
        layout: AzureLayout | None,
        pymupdf_run: ExtractorRun,
        azure_run: ExtractorRun,
    ) -> tuple[list[Page], Extraction]:
        """Assemble the final pages and the extraction record.

        When `layout` is None - Azure failed, timed out, or was never
        configured - the PyMuPDF pages are returned untouched and the failure
        is recorded alongside them. The document stays usable.
        """
        if layout is not None:
            pages = self.normalize_tables(pages, layout)

        extraction = Extraction(
            pymupdf=pymupdf_run,
            azure_di=azure_run,
            matching=summarize_matching(pages),
            config=MatchingConfig(
                word_containment_threshold=self._matcher.word_containment_threshold,
                cell_containment_threshold=self._matcher.cell_containment_threshold,
                text_layer_min_chars=self._text_layer_min_chars,
            ),
            extracted_at=datetime.now(UTC),
        )
        return pages, extraction


def summarize_matching(pages: list[Page]) -> MatchingStats:
    """Count how the two sources agreed, across every cell in the document.

    A cell is "empty" when neither source found text in it. Those are excluded
    from the match rate - see `MatchingStats` for why that distinction is what
    makes the number readable.

    Emptiness is read off the *chosen* text rather than the raw `azure_text`,
    so a cell whose only Azure content was a stripped checkbox marker counts as
    the blank it is instead of as a populated cell nobody could match.
    """
    total = empty = matched = exact = spatial = 0
    for page in pages:
        for table in page.tables:
            for cell in table.cells:
                total += 1
                if not cell.text.strip() and not (cell.pymupdf_text or "").strip():
                    empty += 1
                    continue
                method = cell.text_source.method
                if cell.text_source.matched:
                    matched += 1
                if method is MatchMethod.EXACT:
                    exact += 1
                elif method is MatchMethod.SPATIAL:
                    spatial += 1
    return MatchingStats(
        total_cells=total,
        empty_cells=empty,
        matched_cells=matched,
        exact_matches=exact,
        spatial_matches=spatial,
        unmatched_cells=total - empty - matched,
    )


def _unmatched_source():
    from extraction.types import TextSource

    return TextSource(
        source=Source.AZURE_DI,
        matched=False,
        method=MatchMethod.NONE,
        containment=0.0,
        iou=0.0,
        bbox=None,
        word_count=0,
    )


def _header_signature(table: Table) -> str:
    """The first row's text, used to spot a table continued on the next page."""
    return "|".join(cell.text for cell in sorted(table.cells, key=lambda c: (c.row, c.column)) if cell.row == 0)


def _page_of(tables_by_page: dict[int, list[Table]], table_id: str) -> int:
    for page_number, tables in tables_by_page.items():
        if any(table.id == table_id for table in tables):
            return page_number
    return -1
