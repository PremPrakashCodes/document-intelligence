"""Normalization against the recorded live Azure response for nl-1.pdf."""

import pytest

from extraction.errors import AzureRateLimitError, InvalidPdfError
from extraction.geometry import BBox
from extraction.matcher import strip_selection_marks
from extraction.pipeline import ExtractionPipeline
from extraction.types import DocumentStatus, MatchMethod, Source


class TestCoordinateMapping:
    def test_scale_is_derived_from_the_two_page_sizes(self, normalizer, pdf_extractor, sample_pdf_bytes, sample_layout):
        """Not a hard-coded 72 dpi: the ratio absorbs the sub-percent
        disagreement between Azure's page size and the PDF's mediabox."""
        doc = pdf_extractor.open(sample_pdf_bytes)
        page = pdf_extractor.extract_page(doc, 0)
        scale_x, scale_y = normalizer.page_scale(page, sample_layout)
        # 841.68pt / 11.6806in and 595.2pt / 8.2639in. Neither is exactly 72:
        # assuming that constant would misplace the right-hand columns.
        assert scale_x == pytest.approx(72.058, abs=0.01)
        assert scale_y == pytest.approx(72.024, abs=0.01)
        assert scale_x != scale_y  # they genuinely differ
        doc.close()

    def test_scale_falls_back_to_identity_for_an_unknown_page(self, normalizer, pdf_extractor, sample_pdf_bytes, sample_layout):
        doc = pdf_extractor.open(sample_pdf_bytes)
        page = pdf_extractor.extract_page(doc, 0).model_copy(update={"page_number": 99})
        assert normalizer.page_scale(page, sample_layout) == (1.0, 1.0)
        doc.close()

    def test_every_table_and_cell_box_lands_on_the_page(self, canonical):
        page = canonical.pages[0]
        for table in page.tables:
            box = BBox(*table.bbox)
            assert 0 <= box.x0 < box.x1 <= page.geometry.width
            assert 0 <= box.y0 < box.y1 <= page.geometry.height
            for cell in table.cells:
                cell_box = BBox(*cell.bbox)
                assert 0 <= cell_box.x0 <= cell_box.x1 <= page.geometry.width
                assert 0 <= cell_box.y0 <= cell_box.y1 <= page.geometry.height


class TestTables:
    def test_finds_both_tables_with_azure_structure_intact(self, canonical):
        tables = canonical.tables
        assert [(t.id, t.row_count, t.column_count) for t in tables] == [
            ("table_1", 29, 19),
            ("table_2", 11, 17),
        ]
        assert all(t.source is Source.AZURE_DI for t in tables)
        assert all(t.page_number == 1 for t in tables)

    def test_cells_are_ordered_by_row_then_column(self, canonical):
        for table in canonical.tables:
            positions = [(c.row, c.column) for c in table.cells]
            assert positions == sorted(positions)

    def test_preserves_column_spans_from_azure(self, canonical):
        header = next(c for c in canonical.tables[0].cells if c.row == 0 and c.column == 3)
        assert header.text == "Fire"
        assert header.column_span == 4  # spans its four quarter columns

    def test_keeps_azure_cell_kinds(self, canonical):
        kinds = {c.kind for c in canonical.tables[0].cells}
        assert "columnHeader" in kinds

    def test_reports_confidence_averaged_over_words(self, canonical):
        table = canonical.tables[0]
        assert 0.9 < table.confidence <= 1.0
        populated = [c for c in table.cells if c.confidence is not None]
        assert populated and all(0.0 < c.confidence <= 1.0 for c in populated)


class TestProvenance:
    def test_every_cell_records_both_readings(self, canonical):
        for table in canonical.tables:
            for cell in table.cells:
                assert cell.azure_text is not None
                # The chosen text always equals one of the two sources - with
                # Azure's checkbox markers stripped, which is the one edit this
                # pipeline makes to a reading it was given.
                if cell.text_source.source is Source.PYMUPDF:
                    assert cell.text == cell.pymupdf_text
                else:
                    assert cell.text == strip_selection_marks(cell.azure_text)

    def test_matched_cells_carry_a_highlight_box(self, canonical):
        matched = [c for t in canonical.tables for c in t.cells if c.text_source.matched]
        assert matched
        for cell in matched:
            assert cell.text_source.bbox is not None
            assert cell.text_source.word_count > 0

    def test_headline_match_rate_on_real_data(self, canonical):
        """The end-to-end quality number, pinned so a regression is visible."""
        stats = canonical.extraction.matching
        assert stats.total_cells == 714
        # 193 cells neither source read, plus the two whose only Azure content
        # was a checkbox marker over an empty box.
        assert stats.empty_cells == 195
        assert stats.content_cells == 519
        assert stats.matched_cells == 519
        assert stats.unmatched_cells == 0
        assert stats.match_rate == 1.0

    def test_azure_selection_marks_do_not_become_cell_values(self, canonical):
        """Azure reports checkbox state as the literal text `:unselected:`.

        On a ruled filing schedule the detector fires on empty boxes, so left
        in it would put `:unselected:` in front of a reviewer as the value of a
        cell the document shows as blank. The raw reading is kept on
        `azure_text`; the cell itself reads empty, which is what the PDF says.
        """
        # Matched on the marker, not on a bare colon: real cells contain one
        # ("Add/Less :-"), and they are not what this is about.
        marked = [
            c
            for t in canonical.tables
            for c in t.cells
            if ":unselected:" in c.azure_text or ":selected:" in c.azure_text
        ]
        assert [c.azure_text for c in marked] == [":unselected:", ":unselected:"]
        assert all(c.text == "" for c in marked)
        assert all(not c.pymupdf_text for c in marked)

    def test_no_populated_cell_is_left_unmatched(self, canonical):
        """With the markers out of the way, every cell holding text matches."""
        unmatched = [
            c
            for t in canonical.tables
            for c in t.cells
            if not c.text_source.matched and (c.text.strip() or (c.pymupdf_text or "").strip())
        ]
        assert unmatched == []

    def test_recovers_nil_dashes_azure_dropped(self, canonical):
        """The regression that drove the containment rule: 148 right-aligned
        dashes that straddle a column rule. Azure returns empty for them;
        PyMuPDF has them, and they must survive."""
        recovered = [
            c
            for t in canonical.tables
            for c in t.cells
            if c.pymupdf_text == "-" and not c.azure_text.strip()
        ]
        assert len(recovered) > 100
        assert all(c.text == "-" for c in recovered)
        assert all(c.text_source.source is Source.PYMUPDF for c in recovered)
        assert all(c.text_source.method is MatchMethod.SPATIAL for c in recovered)

    def test_records_the_thresholds_used(self, canonical):
        config = canonical.extraction.config
        assert config.word_containment_threshold == 0.55
        assert config.cell_containment_threshold == 0.55
        assert config.text_layer_min_chars == 24


class TestDegradation:
    async def test_azure_failure_keeps_the_pymupdf_extraction(
        self, pdf_extractor, normalizer, sample_pdf_bytes, failing_layout_extractor
    ):
        """The rule the pipeline exists to enforce."""
        pipeline = ExtractionPipeline(
            pdf_extractor=pdf_extractor,
            layout_extractor=failing_layout_extractor(AzureRateLimitError("429 from Azure")),
            normalizer=normalizer,
        )
        doc = await pipeline.run(sample_pdf_bytes, document_id="doc_x", filename="nl-1.pdf")

        assert doc.document.status is DocumentStatus.PARTIAL
        assert doc.extraction.pymupdf.completed is True
        assert doc.extraction.azure_di.completed is False
        assert doc.extraction.azure_di.error.code == "azure_rate_limited"
        assert doc.extraction.azure_di.error.retryable is True

        # Everything deterministic survived; only the tables are missing.
        page = doc.pages[0]
        assert len(page.content.words) == 747
        assert page.tables == []
        assert "REVENUE ACCOUNT" in page.content.text

    async def test_no_azure_client_configured_still_extracts(
        self, pdf_extractor, normalizer, sample_pdf_bytes
    ):
        pipeline = ExtractionPipeline(
            pdf_extractor=pdf_extractor, layout_extractor=None, normalizer=normalizer
        )
        doc = await pipeline.run(sample_pdf_bytes, document_id="doc_y", filename="nl-1.pdf")
        assert doc.document.status is DocumentStatus.PARTIAL
        assert doc.extraction.azure_di.error.code == "azure_not_configured"
        assert doc.pages[0].content.words

    async def test_an_unexpected_azure_bug_does_not_lose_the_document(
        self, pdf_extractor, normalizer, sample_pdf_bytes, failing_layout_extractor
    ):
        pipeline = ExtractionPipeline(
            pdf_extractor=pdf_extractor,
            layout_extractor=failing_layout_extractor(RuntimeError("something unforeseen")),
            normalizer=normalizer,
        )
        doc = await pipeline.run(sample_pdf_bytes, document_id="doc_z", filename="nl-1.pdf")
        assert doc.document.status is DocumentStatus.PARTIAL
        assert doc.extraction.azure_di.error.code == "azure_unexpected_error"
        assert doc.pages[0].content.words

    async def test_a_pymupdf_failure_is_fatal(self, pipeline):
        """There is no document without PyMuPDF, so this one does propagate."""
        with pytest.raises(InvalidPdfError):
            await pipeline.run(b"not a pdf", document_id="doc_bad", filename="bad.pdf")


class TestDeterminism:
    async def test_two_runs_produce_identical_output(self, pipeline, sample_pdf_bytes):
        first = await pipeline.run(sample_pdf_bytes, document_id="d", filename="nl-1.pdf")
        second = await pipeline.run(sample_pdf_bytes, document_id="d", filename="nl-1.pdf")
        # Wall-clock fields legitimately differ between runs; every extracted
        # value must not.
        exclude = {
            "extraction": {
                "extracted_at": True,
                "pymupdf": {"duration_ms"},
                "azure_di": {"duration_ms"},
            }
        }
        assert first.model_dump(exclude=exclude) == second.model_dump(exclude=exclude)

    async def test_pages_and_cells_are_identical_across_runs(self, pipeline, sample_pdf_bytes):
        """The audit guarantee stated plainly: same bytes, same 714 cells."""
        first = await pipeline.run(sample_pdf_bytes, document_id="d", filename="nl-1.pdf")
        second = await pipeline.run(sample_pdf_bytes, document_id="d", filename="nl-1.pdf")
        assert [p.model_dump_json() for p in first.pages] == [
            p.model_dump_json() for p in second.pages
        ]
