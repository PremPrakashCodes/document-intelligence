"""Cell matching: deterministic, exclusive, and biased toward the actual PDF."""

import pytest

from extraction.geometry import BBox
from extraction.matcher import TableMatcher, WordIndex, normalize_text
from extraction.types import MatchMethod, Source, Word


def word(text: str, bbox: tuple[float, ...], *, block: int = 0, line: int = 0, index: int = 0) -> Word:
    return Word(text=text, bbox=bbox, block=block, line=line, word=index)


@pytest.fixture
def simple_matcher() -> TableMatcher:
    return TableMatcher(word_containment_threshold=0.55, cell_containment_threshold=0.55)


class TestNormalizeText:
    def test_collapses_whitespace(self):
        assert normalize_text("  Policy   Number\n") == "Policy Number"

    def test_folds_compatibility_forms(self):
        assert normalize_text("ﬁle") == "file"          # fi ligature
        assert normalize_text("A B") == "A B"           # non-breaking space

    def test_preserves_currency_and_indian_grouping(self):
        """The values this system exists to extract must survive untouched."""
        assert normalize_text("₹1,25,000") == "₹1,25,000"


class TestWordIndex:
    def test_finds_the_same_words_as_a_full_scan(self):
        words = [word(str(i), (0, i * 10, 5, i * 10 + 8)) for i in range(50)]
        index = WordIndex(words)
        box = BBox(0, 95, 10, 165)
        from_index = {w.text for w, _ in index.candidates(box)}
        from_scan = {
            w.text for w in words if w.bbox[1] <= box.y1 and w.bbox[3] >= box.y0
        }
        assert from_index == from_scan

    def test_handles_an_empty_page(self):
        assert WordIndex([]).candidates(BBox(0, 0, 10, 10)) == []


class TestMatchCell:
    def test_exact_match_prefers_pymupdf(self, simple_matcher):
        index = WordIndex([word("Premium", (12, 12, 40, 20))])
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "Premium", index)
        assert match.text == "Premium"
        assert match.source.method is MatchMethod.EXACT
        assert match.source.source is Source.PYMUPDF
        assert match.source.matched is True
        assert match.source.containment == 1.0

    def test_whitespace_only_difference_still_counts_as_exact(self, simple_matcher):
        index = WordIndex(
            [word("1,25", (12, 12, 30, 20), index=0), word("000", (32, 12, 44, 20), index=1)]
        )
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "1,25 000", index)
        assert match.source.method is MatchMethod.EXACT

    def test_differing_text_inside_the_cell_is_spatial_and_still_prefers_pymupdf(self, simple_matcher):
        """The ownership rule: the PDF's own bytes win over Azure's reading."""
        index = WordIndex([word("₹25,000", (12, 12, 60, 20))])
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "25,000", index)
        assert match.source.method is MatchMethod.SPATIAL
        assert match.source.source is Source.PYMUPDF
        assert match.text == "₹25,000"
        # Azure's reading is preserved, never discarded.
        assert match.pymupdf_text == "₹25,000"

    def test_empty_cell_falls_back_to_azure(self, simple_matcher):
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "Sub-total", WordIndex([]))
        assert match.source.method is MatchMethod.NONE
        assert match.source.source is Source.AZURE_DI
        assert match.text == "Sub-total"
        assert match.pymupdf_text is None
        assert match.source.bbox is None

    def test_a_checkbox_marker_is_not_a_value(self, simple_matcher):
        """Azure's `:unselected:` is state, and the detector fires on the empty
        boxes a ruled schedule is full of. The cell reads empty; the raw
        reading survives on the cell's `azure_text`, which this layer sets."""
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), ":unselected:", WordIndex([]))
        assert match.text == ""
        assert match.pymupdf_text is None

    def test_a_marker_beside_real_text_keeps_the_text(self, simple_matcher):
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), ":selected: Yes", WordIndex([]))
        assert match.text == "Yes"

    def test_a_marker_does_not_block_an_exact_match(self, simple_matcher):
        """The PDF spells out `Yes`; Azure prefixes it with the checkbox it
        found. Comparing against the raw content would grade this SPATIAL and
        report a discrepancy that is not one."""
        index = WordIndex([word("Yes", (12, 12, 40, 20))])
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), ":selected: Yes", index)
        assert match.source.method is MatchMethod.EXACT
        assert match.text == "Yes"

    def test_a_word_mostly_outside_the_cell_is_ignored(self, simple_matcher):
        # Only 20% of this word lies inside, below the 0.55 membership bar.
        index = WordIndex([word("Neighbour", (90, 12, 140, 20))])
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "", index)
        assert match.source.method is MatchMethod.NONE
        assert match.source.word_count == 0

    def test_straddling_word_lands_in_exactly_one_cell(self, simple_matcher):
        """nl-1.pdf's nil markers sit 68/32 across a column rule. Each must be
        read into its own column and not duplicated into the neighbour."""
        dash = word("-", (28.57, 0.63, 30.57, 7.32))
        index = WordIndex([dash])
        left = simple_matcher.match_cell(BBox(0, 0, 29.93, 7.54), "", index)
        right = simple_matcher.match_cell(BBox(29.93, 0, 60, 7.54), "", index)
        assert (left.source.word_count, right.source.word_count) == (1, 0)
        assert left.text == "-"
        assert left.source.matched is True

    def test_short_text_in_a_wide_cell_is_not_penalised(self, simple_matcher):
        """The regression that motivated grading on containment: a lone dash in
        a wide numeric column has a near-zero IoU but belongs to the cell."""
        index = WordIndex([word("-", (60, 12, 62, 19))])
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "", index)
        assert match.source.matched is True
        assert match.text == "-"
        assert match.source.iou < 0.05  # IoU would have rejected this
        assert match.source.containment == 1.0

    def test_records_the_highlight_box_for_the_matched_words(self, simple_matcher):
        index = WordIndex(
            [word("Policy", (12, 12, 40, 20), index=0), word("Number", (42, 12, 80, 20), index=1)]
        )
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "Policy Number", index)
        assert match.source.bbox == (12.0, 12.0, 80.0, 20.0)
        assert match.source.word_count == 2

    def test_joins_words_in_pymupdf_reading_order(self, simple_matcher):
        """Words are given to the index out of order; the result must follow
        PyMuPDF's own (block, line, word) sequence."""
        index = WordIndex(
            [
                word("Number", (42, 12, 80, 20), block=0, line=0, index=1),
                word("Policy", (12, 12, 40, 20), block=0, line=0, index=0),
            ]
        )
        match = simple_matcher.match_cell(BBox(10, 10, 100, 25), "Policy Number", index)
        assert match.pymupdf_text == "Policy Number"

    def test_is_deterministic_across_input_orderings(self, simple_matcher):
        words = [
            word("beta", (42, 12, 80, 20), index=1),
            word("alpha", (12, 12, 40, 20), index=0),
        ]
        first = simple_matcher.match_cell(BBox(10, 10, 100, 25), "x", WordIndex(words))
        second = simple_matcher.match_cell(BBox(10, 10, 100, 25), "x", WordIndex(list(reversed(words))))
        assert first == second
