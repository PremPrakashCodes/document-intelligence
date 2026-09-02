"""Deterministic association of Azure DI table cells with PyMuPDF text.

Azure says *where the cells are*; PyMuPDF says *exactly what the PDF contains*.
This module joins the two on geometry alone - no language model, no fuzzy
string matching, no heuristics beyond the two documented thresholds. The same
inputs always produce the same output, and every decision is recorded on the
resulting `TextSource` so it can be replayed and argued with.

The rules
---------
A PyMuPDF word belongs to a cell when at least
`word_containment_threshold` (default 0.55) of the word's area falls inside the
cell box. Containment, not IoU, is the right test here: a word is far smaller
than its cell, so a perfect match still scores a near-zero IoU.

The threshold is above 0.5 for a specific reason: **a cell grid does not
overlap, so a word can exceed 50% containment in at most one cell.** The
membership rule is therefore an exclusive assignment - each word lands in
exactly one cell, or none - with no tie-break needed and no chance of the same
word being read into two columns. The sample document leans on this: its nil
markers are
right-aligned dashes that straddle a column rule, sitting 68% in their own
column and 32% in the next. The rule puts each one in exactly the right cell.

The words that belong to a cell are joined in reading order to form the
candidate text. The match is then graded on `containment` - the fraction of
the *matched words' union* that lies inside the cell:

* `EXACT`   - the candidate equals Azure's content once whitespace and
              Unicode compatibility forms are normalized. PyMuPDF text wins.
* `SPATIAL` - the strings differ, but the words sit squarely inside the cell
              (containment at least `cell_containment_threshold`, default
              0.8). PyMuPDF text still wins: it is the literal PDF content,
              and the divergence is nearly always Azure re-reading, or
              dropping, a glyph the PDF already spells out. Both are kept.
* `WEAK`    - the words' union sprawls outside the cell despite each word
              passing membership, which means the cell box itself is suspect.
              Azure's reading wins; the PyMuPDF candidate is recorded but not
              promoted. Rare, and deliberately so - see below.
* `NONE`    - no words inside the cell: a scanned page, or an empty cell.
              Azure text wins.

Azure's `:selected:` / `:unselected:` checkbox markers are stripped before any
of this: they are state, not content, and the detector fires on the empty boxes
a ruled filing schedule is full of. See `strip_selection_marks`.

Why containment and not IoU
---------------------------
IoU between a cell and its text is not a measure of match quality - it is a
measure of how much padding the cell has. In the sample document, 148 cells hold a single
"-" (the nil marker) in a 30pt-wide numeric column. Those dashes are genuine
PDF content that Azure dropped, and every one of them sits perfectly inside its
cell - yet their IoU is about 0.05. Grading on IoU rejected all 148 and kept
Azure's empty string, silently losing real PDF text and inverting the
ownership rule this pipeline exists to enforce.

Containment has no such bias: a word wholly inside its cell scores 1.0 whether
the cell is snug or generously padded. IoU is still computed and reported, so a
reviewer can see the geometry, but it never decides anything.

Why the two thresholds are equal by default
-------------------------------------------
`cell_containment_threshold` defaults to the same 0.55 as the membership rule,
and that is not laziness. Because membership is already exclusive, a word that
passed it is unambiguously this cell's word; re-testing the assembled union
against a *stricter* bar would reject text the first rule just proved belongs
here. An earlier draft of this module set the cell bar at 0.8 and dropped 148
straddling dashes on the sample document, keeping Azure's empty string over real PDF
content. Holding both at the exclusivity bound leaves `WEAK` to catch the one
case membership cannot: several individually-contained words whose *union* box
still escapes the cell, which only happens when the cell geometry is wrong.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

from extraction.geometry import (
    BBox,
    calculate_iou,
    calculate_overlap,
    normalize_bbox,
    union_bbox,
)
from extraction.types import MatchMethod, Source, TextSource, Word

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Fold a string to its comparison form.

    NFKC collapses compatibility variants - the `ﬁ` ligature, full-width
    digits, the non-breaking space - that a PDF and an OCR engine can spell
    differently while meaning the same thing. Currency signs and Indian digit
    grouping survive untouched, which matters here: `₹1,25,000` must not become
    anything else.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


_SELECTION_MARK = re.compile(r":(?:un)?selected:")


def strip_selection_marks(value: str) -> str:
    """Drop Azure's checkbox markers from a cell's content.

    Azure DI reports a detected checkbox as the literal text `:selected:` or
    `:unselected:`. That is *state*, not the cell's text - and on a ruled
    filing schedule the detector fires on empty boxes, so the marker is
    routinely the only "content" a genuinely blank cell has. Left in, it
    reaches the reviewer as a value: a column of `:unselected:` where the
    document shows nothing at all.

    Stripping happens where the cell's text is *chosen*, never where Azure's
    reading is *recorded*: `azure_text` keeps the raw content, so the marker
    is still auditable and nothing this pipeline was told is discarded.
    """
    return _WHITESPACE.sub(" ", _SELECTION_MARK.sub(" ", value)).strip()


def _comparable(value: str) -> str:
    """Comparison form ignoring spacing entirely.

    Azure and PyMuPDF routinely disagree on whether a wide gap inside a number
    is a space. That difference is not a discrepancy worth flagging.
    """
    return normalize_text(value).replace(" ", "")


class WordIndex:
    """Words sorted by vertical position, for range queries by cell.

    A real filing page carries hundreds of words and a table can hold hundreds
    of cells, so scanning every word per cell is quadratic. Words are sorted by
    `y0` once; a cell then only considers the slice that could vertically reach
    it. The result is identical to a full scan - this is an index, not a
    heuristic.
    """

    __slots__ = ("_words", "_boxes", "_tops", "_max_height")

    def __init__(self, words: Sequence[Word]) -> None:
        ordered = sorted(words, key=lambda w: (w.bbox[1], w.bbox[0]))
        self._words = tuple(ordered)
        self._boxes = tuple(normalize_bbox(w.bbox) for w in ordered)
        self._tops = [box.y0 for box in self._boxes]
        self._max_height = max((box.height for box in self._boxes), default=0.0)

    def __len__(self) -> int:
        return len(self._words)

    def candidates(self, box: BBox) -> list[tuple[Word, BBox]]:
        """Words whose vertical extent could intersect `box`.

        A word starting more than `_max_height` above the cell cannot reach
        into it, which gives the lower bound for the slice.
        """
        if not self._words:
            return []
        start = bisect_left(self._tops, box.y0 - self._max_height)
        out: list[tuple[Word, BBox]] = []
        for index in range(start, len(self._words)):
            word_box = self._boxes[index]
            if word_box.y0 > box.y1:
                break  # sorted by y0: nothing later can reach up into the cell
            if word_box.y1 >= box.y0:
                out.append((self._words[index], word_box))
        return out


@dataclass(frozen=True, slots=True)
class CellMatch:
    """The outcome of matching one cell against the PyMuPDF text layer."""

    text: str
    pymupdf_text: str | None
    source: TextSource

    @property
    def matched(self) -> bool:
        return self.source.matched


class TableMatcher:
    """Matches Azure DI cells to PyMuPDF words. Stateless; safe to share."""

    def __init__(
        self,
        *,
        word_containment_threshold: float = 0.55,
        cell_containment_threshold: float = 0.55,
    ) -> None:
        self.word_containment_threshold = word_containment_threshold
        self.cell_containment_threshold = cell_containment_threshold

    def build_index(self, words: Sequence[Word]) -> WordIndex:
        return WordIndex(words)

    def match_text_to_cell(self, cell_bbox: BBox, index: WordIndex) -> tuple[list[Word], BBox | None]:
        """The PyMuPDF words inside `cell_bbox`, in reading order.

        Returns the words and the box covering them - what the UI highlights
        when a cell is selected.
        """
        contained = [
            (word, box)
            for word, box in index.candidates(cell_bbox)
            if calculate_overlap(box, cell_bbox) >= self.word_containment_threshold
        ]
        # PyMuPDF's (block, line, word) indices are the reading order MuPDF
        # itself determined, so they are used rather than re-deriving one from
        # coordinates. A geometric key has to bucket near-equal baselines to
        # keep a line together, and any bucket boundary eventually splits two
        # glyphs that differ by less than the tolerance.
        contained.sort(key=lambda pair: (pair[0].block, pair[0].line, pair[0].word))
        return [word for word, _ in contained], union_bbox([box for _, box in contained])

    def match_cell(self, cell_bbox: BBox, azure_text: str, index: WordIndex) -> CellMatch:
        """Resolve one cell's text and record how the decision was made."""
        words, words_bbox = self.match_text_to_cell(cell_bbox, index)
        # Azure's checkbox markers are state, not text, so they take no part in
        # either the fallback value or the comparison. A cell whose only Azure
        # content was a marker is an empty cell.
        azure_content = strip_selection_marks(azure_text)

        if not words or words_bbox is None:
            # Nothing in the text layer here: a scanned page, or an empty cell.
            return CellMatch(
                text=azure_content,
                pymupdf_text=None,
                source=TextSource(
                    source=Source.AZURE_DI,
                    matched=False,
                    method=MatchMethod.NONE,
                    containment=0.0,
                    iou=0.0,
                    bbox=None,
                    word_count=0,
                ),
            )

        pymupdf_text = " ".join(word.text for word in words)
        containment = calculate_overlap(words_bbox, cell_bbox)
        iou = calculate_iou(cell_bbox, words_bbox)

        if _comparable(pymupdf_text) == _comparable(azure_content):
            method = MatchMethod.EXACT
        elif containment >= self.cell_containment_threshold:
            method = MatchMethod.SPATIAL
        else:
            method = MatchMethod.WEAK

        # PyMuPDF text is preferred on a strong match only. A weak match means
        # the words hang outside the cell and probably belong to a neighbour,
        # so Azure's own reading is the safer value - but the PyMuPDF candidate
        # is still recorded rather than discarded.
        prefer_pymupdf = method in (MatchMethod.EXACT, MatchMethod.SPATIAL)

        return CellMatch(
            text=normalize_text(pymupdf_text) if prefer_pymupdf else azure_content,
            pymupdf_text=normalize_text(pymupdf_text),
            source=TextSource(
                source=Source.PYMUPDF if prefer_pymupdf else Source.AZURE_DI,
                matched=prefer_pymupdf,
                method=method,
                containment=round(containment, 4),
                iou=round(iou, 4),
                bbox=words_bbox.rounded().as_tuple(),
                word_count=len(words),
            ),
        )
