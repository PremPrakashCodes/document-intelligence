"""Generate the synthetic sample document the extraction tests run against.

The suite needs a document with the awkward properties a real filing schedule
has - a landscape page, two wide ruled tables, spanning column headers, and
right-aligned nil markers that straddle a column rule - without shipping
anyone's actual filing. So the fixture is *generated*: this script is the
single source of truth for both halves of it.

    tests/fixtures/sample-revenue-account.pdf
    tests/fixtures/sample-revenue-account.layout.json

Generating both together is the point. The JSON is not a recording of a
service call against some other file; it is derived from the very geometry
this script renders, which is what makes the matcher's job real. Azure's
characteristic failures are reproduced deliberately:

* the straddling nil dashes are rendered into the PDF and *omitted* from the
  layout, which is exactly what the live service did with them, and what the
  containment rule exists to recover;
* two blank cells carry the literal `:unselected:` checkbox marker, because a
  ruled schedule full of empty boxes is where the detector fires;
* word polygons carry a small deterministic jitter and per-word confidences,
  so nothing downstream can quietly assume pixel-exact agreement.

Everything in it is invented. The entity, the registration number and every
figure are fabricated; the vocabulary is the generic vocabulary of a revenue
account. Run it with `uv run python tests/fixtures/generate_sample.py`; the
output is deterministic, so a re-run is a no-op unless this file changed.
"""

from __future__ import annotations

import json
import pathlib
import random

import pymupdf

HERE = pathlib.Path(__file__).parent
PDF_PATH = HERE / "sample-revenue-account.pdf"
LAYOUT_PATH = HERE / "sample-revenue-account.layout.json"

# Landscape A4. The two page sizes disagree by a sub-percent amount on purpose:
# it is what stops the normalizer from assuming a flat 72 dpi.
PAGE_W, PAGE_H = 841.68, 595.2
AZURE_W, AZURE_H = 11.6806, 8.2639
SCALE_X, SCALE_Y = PAGE_W / AZURE_W, PAGE_H / AZURE_H  # 72.058, 72.025

FONT, FONT_BOLD = "helv", "hebo"
LEFT, RIGHT = 29.0, 810.0
PAD = 2.0

# The fraction of a nil dash that must sit inside its own column. Above the
# 0.55 containment threshold, and below 1.0, so the glyph genuinely crosses the
# rule the way a right-aligned dash in a narrow numeric column does.
DASH_INSIDE = 0.68

NIL = "-"

# A pinned PDF document id, so regenerating produces byte-identical output.
FIXED_ID = "D0C10FF1CE5A11P1E12E7E17ACC0173A"

TITLE_LINES = [
    ("QUARTERLY FINANCIAL DISCLOSURES", 8.5, FONT_BOLD),
    ("FORM SYN-1-B-RA", 8.5, FONT_BOLD),
    ("Name of the Entity: Northwind Assurance Company Limited", 7.0, FONT),
    ("Registration Number: 999    Date of Registration: 01/04/2019", 7.0, FONT),
    ("REVENUE ACCOUNT FOR THE QUARTER ENDED 30 JUNE 2024", 8.0, FONT_BOLD),
    ("(Amounts in thousands of currency units)", 6.5, FONT),
]

SEGMENTS_1 = ["Fire", "Marine", "Motor", "Health"]
QUARTERS_1 = ["CQ", "PQ", "CYTD", "PYTD"]

SEGMENTS_2 = ["Current Year", "Previous Year"]
QUARTERS_2 = ["Fire", "Marine", "Motor", "Health", "Liab", "Misc", "Total"]

# 27 data rows. `blank` rows are section breaks the document genuinely leaves
# empty across every numeric column - the "neither source read it" case.
ROWS_1: list[tuple[str, str, str]] = [
    ("1", "Premiums earned (net)", "value"),
    ("", "Add/Less :- Adjustment for change in reserve", "value"),
    ("2", "Profit on sale of investments", "value"),
    ("3", "Loss on sale of investments", "value"),
    ("4", "Interest, Dividend and Rent (Gross)", "value"),
    ("5", "Other income from underwriting", "value"),
    ("", "TOTAL (A)", "total"),
    ("", "", "blank"),
    ("6", "Claims incurred (net)", "value"),
    ("7", "Commission paid to intermediaries", "value"),
    ("8", "Operating expenses related to insurance business", "value"),
    ("9", "Premium deficiency reserve", "value"),
    ("10", "Provision for doubtful debts", "value"),
    ("11", "Amortisation of premium on investments", "value"),
    ("", "TOTAL (B)", "total"),
    ("", "", "blank"),
    ("", "Operating Profit / (Loss) C = (A - B)", "total"),
    ("", "", "blank"),
    ("", "APPROPRIATIONS", "section"),
    ("12", "Transfer to Shareholders Account", "value"),
    ("13", "Transfer to Catastrophe Reserve", "value"),
    ("14", "Transfer to Other Reserves", "value"),
    ("", "TOTAL (C)", "total"),
    ("", "", "blank"),
    ("15", "Balance carried forward to Balance Sheet", "value"),
    ("16", "Closing balance of policyholders funds", "value"),
    ("", "TOTAL (D)", "total"),
]

# 9 data rows for the schedule.
ROWS_2: list[tuple[str, str, str]] = [
    ("1", "Premium from direct business written", "value"),
    ("2", "Add: Premium on reinsurance accepted", "value"),
    ("3", "Less: Premium on reinsurance ceded", "value"),
    ("", "Net Premium", "total"),
    ("", "", "blank"),
    ("4", "Adjustment for change in reserve for unexpired risks", "value"),
    ("5", "Adjustment for premium deficiency", "value"),
    ("", "Total Premium Earned (Net)", "total"),
    ("", "", "blank"),
]


# --- content / span bookkeeping --------------------------------------------


class Content:
    """Builds Azure's flat `content` string and hands back spans into it.

    Azure grades a cell's confidence by averaging the words whose character
    spans fall inside the cell's spans, so the offsets have to be real. Growing
    the string and the spans together is the only way to keep them honest.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._offset = 0

    def add(self, text: str) -> dict:
        span = {"offset": self._offset, "length": len(text)}
        self._parts.append(text)
        self._offset += len(text)
        return span

    def sep(self, text: str = "\n") -> None:
        self._parts.append(text)
        self._offset += len(text)

    @property
    def offset(self) -> int:
        return self._offset

    def build(self) -> str:
        return "".join(self._parts)


def to_inches(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    """A points rectangle as Azure's 4-point polygon, in inches."""
    ax0, ay0 = x0 / SCALE_X, y0 / SCALE_Y
    ax1, ay1 = x1 / SCALE_X, y1 / SCALE_Y
    return [
        round(v, 4) for v in (ax0, ay0, ax1, ay0, ax1, ay1, ax0, ay1)
    ]


def column_edges(numeric_count: int) -> list[float]:
    """Left edges plus the final right edge, for a 3-label + N-numeric grid."""
    label_widths = [14.0, 175.0, 46.0]
    numeric_width = (RIGHT - LEFT - sum(label_widths)) / numeric_count
    edges, x = [LEFT], LEFT
    for w in label_widths:
        x += w
        edges.append(x)
    for _ in range(numeric_count):
        x += numeric_width
        edges.append(x)
    edges[-1] = RIGHT
    return edges


def row_edges(top: float, heights: list[float]) -> list[float]:
    edges, y = [top], top
    for h in heights:
        y += h
        edges.append(y)
    return edges


# --- the table model --------------------------------------------------------


class Cell:
    """One cell: where it is, what the PDF says, and what Azure claims."""

    def __init__(
        self,
        row: int,
        col: int,
        rect: tuple[float, float, float, float],
        *,
        text: str = "",
        kind: str = "content",
        col_span: int = 1,
        align: str = "left",
        bold: bool = False,
        azure_text: str | None = None,
        dropped: bool = False,
    ) -> None:
        self.row, self.col = row, col
        self.rect = rect
        self.text = text
        self.kind = kind
        self.col_span = col_span
        self.align = align
        self.bold = bold
        # `azure_text` defaults to the truth; `dropped` is how the service's
        # habit of losing a lone dash is reproduced.
        self.azure_text = text if azure_text is None else azure_text
        self.dropped = dropped
        self.word_boxes: list[tuple[str, tuple[float, float, float, float]]] = []


def build_table(
    *,
    top: float,
    numeric_count: int,
    segments: list[str],
    sub_labels: list[str],
    rows: list[tuple[str, str, str]],
    header_heights: tuple[float, float],
    data_height: float,
    rng: random.Random,
    nil_bias: float,
) -> tuple[list[Cell], list[float], list[float]]:
    cols = column_edges(numeric_count)
    heights = [header_heights[0], header_heights[1]] + [data_height] * len(rows)
    rws = row_edges(top, heights)
    span = numeric_count // len(segments)
    cells: list[Cell] = []

    def rect(r: int, c: int, cspan: int = 1) -> tuple[float, float, float, float]:
        return (cols[c], rws[r], cols[c + cspan], rws[r + 1])

    # Row 0: the label columns plus one spanning cell per segment.
    for c, label in enumerate(["", "Particulars", "Schedule Ref."]):
        cells.append(Cell(0, c, rect(0, c), text=label, kind="columnHeader", bold=True))
    for i, seg in enumerate(segments):
        c = 3 + i * span
        cells.append(
            Cell(0, c, rect(0, c, span), text=seg, kind="columnHeader",
                 col_span=span, align="center", bold=True)
        )

    # Row 1: the quarter/segment sub-headers under each spanning cell.
    for c in range(3):
        cells.append(Cell(1, c, rect(1, c), kind="columnHeader"))
    for i in range(len(segments)):
        for j, label in enumerate(sub_labels):
            c = 3 + i * span + j
            cells.append(
                Cell(1, c, rect(1, c), text=label, kind="columnHeader",
                     align="center", bold=True)
            )

    # Data rows.
    for r_i, (serial, particular, style) in enumerate(rows):
        r = r_i + 2
        bold = style in {"total", "section"}
        cells.append(Cell(r, 0, rect(r, 0), text=serial, align="center"))
        cells.append(Cell(r, 1, rect(r, 1), text=particular, bold=bold))
        schedule = "" if style in {"blank", "section"} else str(rng.randint(1, 9))
        cells.append(Cell(r, 2, rect(r, 2), text=schedule, align="center"))
        for c in range(3, 3 + numeric_count):
            if style in {"blank", "section"}:
                cells.append(Cell(r, c, rect(r, c), align="right"))
                continue
            if rng.random() < nil_bias:
                # A nil marker: in the PDF, absent from the layout.
                cells.append(
                    Cell(r, c, rect(r, c), text=NIL, align="right",
                         azure_text="", dropped=True)
                )
            else:
                value = f"{rng.randint(1, 999_999):,}"
                cells.append(Cell(r, c, rect(r, c), text=value, align="right", bold=bold))
    return cells, cols, rws


# --- rendering --------------------------------------------------------------


def render(page: pymupdf.Page, cells: list[Cell], cols: list[float], rws: list[float]) -> None:
    """Draw the ruled grid, then place every cell's text and record its box."""
    for x in cols:
        page.draw_line((x, rws[0]), (x, rws[-1]), color=(0.45, 0.45, 0.45), width=0.3)
    for y in rws:
        page.draw_line((cols[0], y), (cols[-1], y), color=(0.45, 0.45, 0.45), width=0.3)

    for cell in cells:
        if not cell.text:
            continue
        x0, y0, x1, y1 = cell.rect
        size = 6.5 if cell.kind == "columnHeader" else 6.0
        font = FONT_BOLD if cell.bold else FONT
        width = pymupdf.get_text_length(cell.text, fontname=font, fontsize=size)
        baseline = y0 + (y1 - y0 + size * 0.66) / 2

        if cell.text == NIL:
            # Straddle the column rule, which is the geometry the whole
            # containment rule was written for.
            x = x1 - DASH_INSIDE * width
        elif cell.align == "right":
            x = x1 - PAD - width
        elif cell.align == "center":
            x = x0 + (x1 - x0 - width) / 2
        else:
            x = x0 + PAD
        page.insert_text((x, baseline), cell.text, fontname=font, fontsize=size)


def collect_word_boxes(page: pymupdf.Page, cells: list[Cell]) -> None:
    """Attach the *rendered* word boxes to each cell.

    Read back from the page rather than predicted, so the layout polygons
    describe the glyphs the PDF actually contains.
    """
    words = page.get_text("words")
    for cell in cells:
        if not cell.text:
            continue
        x0, y0, x1, y1 = cell.rect
        wanted = cell.text.split()
        found: list[tuple[str, tuple[float, float, float, float]]] = []
        for wx0, wy0, wx1, wy1, text, *_ in words:
            if not (y0 - 1 <= (wy0 + wy1) / 2 <= y1 + 1):
                continue
            cx = (wx0 + wx1) / 2
            # A dash sits partly outside its cell; everything else is well in.
            bound_lo, bound_hi = (x0 - 3, x1 + 3) if cell.text == NIL else (x0 - 1, x1 + 1)
            if not (bound_lo <= cx <= bound_hi):
                continue
            if text in wanted:
                found.append((text, (wx0, wy0, wx1, wy1)))
        cell.word_boxes = found


# --- layout assembly --------------------------------------------------------


def azure_table(
    cells: list[Cell],
    rows: int,
    columns: int,
    content: Content,
    words_out: list[dict],
    rng: random.Random,
) -> dict:
    """Serialise a table into Azure's shape, growing `content` as it goes."""
    out_cells = []
    table_start = content.offset
    for cell in cells:
        entry = {
            "rowIndex": cell.row,
            "columnIndex": cell.col,
            "content": cell.azure_text,
            "kind": cell.kind,
            "boundingRegions": [{"pageNumber": 1, "polygon": to_inches(*cell.rect)}],
            "spans": [],
        }
        if cell.col_span > 1:
            entry["columnSpan"] = cell.col_span

        if cell.dropped or not cell.azure_text:
            # Nothing the service read, so nothing enters the content stream.
            # A marker still needs a span: it is content as far as Azure is
            # concerned, even though the box below it is empty.
            if cell.azure_text:
                entry["spans"] = [content.add(cell.azure_text)]
                content.sep(" ")
            out_cells.append(entry)
            continue

        start = content.offset
        for text, box in cell.word_boxes:
            span = content.add(text)
            content.sep(" ")
            # A few thousandths of an inch of jitter, so nothing downstream can
            # quietly assume Azure agrees with PyMuPDF to the last decimal.
            polygon = [
                round(v + rng.uniform(-0.0015, 0.0015), 4) for v in to_inches(*box)
            ]
            words_out.append(
                {
                    "content": text,
                    "polygon": polygon,
                    "confidence": round(rng.uniform(0.93, 0.996), 3),
                    "span": span,
                }
            )
        length = content.offset - start
        entry["spans"] = [{"offset": start, "length": max(length - 1, 0)}]
        out_cells.append(entry)

    xs = [c.rect[0] for c in cells] + [c.rect[2] for c in cells]
    ys = [c.rect[1] for c in cells] + [c.rect[3] for c in cells]
    return {
        "rowCount": rows,
        "columnCount": columns,
        "cells": out_cells,
        "boundingRegions": [
            {"pageNumber": 1, "polygon": to_inches(min(xs), min(ys), max(xs), max(ys))}
        ],
        "spans": [{"offset": table_start, "length": content.offset - table_start}],
    }



def mark_selection_marks(cells: list[Cell], count: int = 2) -> None:
    """Put Azure's checkbox marker on blank cells, the way the live service does.

    `prebuilt-layout` reports a detected checkbox as the literal `:unselected:`,
    and on a ruled schedule it fires on empty boxes - so the marker arrives as
    the *only* content a genuinely blank cell has. Reproduced here because it is
    the one reading the pipeline is allowed to overrule.
    """
    blanks = [c for c in cells if not c.text and not c.azure_text and c.col >= 3]
    for cell in blanks[:: max(len(blanks) // count, 1)][:count]:
        cell.azure_text = ":unselected:"


def main() -> None:
    rng = random.Random(20240630)
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    # Title block.
    title_boxes: list[tuple[str, float, float]] = []
    y = 46.0
    for text, size, font in TITLE_LINES:
        width = pymupdf.get_text_length(text, fontname=font, fontsize=size)
        x = (PAGE_W - width) / 2
        page.insert_text((x, y), text, fontname=font, fontsize=size)
        title_boxes.append((text, y - size, y + size * 0.25))
        y += size + 5.0

    cells_1, cols_1, rws_1 = build_table(
        top=112.0, numeric_count=16, segments=SEGMENTS_1, sub_labels=QUARTERS_1,
        rows=ROWS_1, header_heights=(16.0, 13.0), data_height=10.0,
        rng=rng, nil_bias=0.34,
    )
    render(page, cells_1, cols_1, rws_1)

    schedule_y = rws_1[-1] + 16.0
    page.insert_text((LEFT, schedule_y), "SCHEDULE 1 - PREMIUM EARNED (NET)",
                     fontname=FONT_BOLD, fontsize=7.5)
    title_boxes.append(("SCHEDULE 1 - PREMIUM EARNED (NET)", schedule_y - 7.5, schedule_y + 2))

    cells_2, cols_2, rws_2 = build_table(
        top=schedule_y + 8.0, numeric_count=14, segments=SEGMENTS_2, sub_labels=QUARTERS_2,
        rows=ROWS_2, header_heights=(15.0, 13.0), data_height=10.0,
        rng=rng, nil_bias=0.30,
    )
    render(page, cells_2, cols_2, rws_2)

    mark_selection_marks(cells_1)

    doc.set_metadata(
        {
            "title": "Revenue Account - Northwind Assurance Company Limited",
            "author": "Document Intelligence test fixtures",
            "subject": "Synthetic revenue account for extraction tests",
            "keywords": "synthetic, fixture, revenue account",
            "creator": "generate_sample.py",
            "producer": "Document Intelligence fixture generator",
            "creationDate": "D:20240630000000Z",
            "modDate": "D:20240630000000Z",
        }
    )
    # MuPDF stamps a fresh random /ID on every save, which would make the
    # fixture's bytes differ on each run for no reason anyone can see. Pinning
    # it is what lets a regeneration be a genuine no-op - and the extractor's
    # "same bytes, same output" guarantee is exactly the kind of thing a
    # spuriously churning fixture hides.
    doc.xref_set_key(-1, "ID", f"[<{FIXED_ID}><{FIXED_ID}>]")
    pdf_bytes = doc.tobytes(deflate=True, garbage=4, no_new_id=True)
    doc.close()

    # Re-open the saved bytes so the recorded boxes come from the very file the
    # tests will read, not from an in-memory page that was still being built.
    doc = pymupdf.open("pdf", pdf_bytes)
    page = doc[0]
    collect_word_boxes(page, cells_1)
    collect_word_boxes(page, cells_2)

    content = Content()
    words: list[dict] = []
    paragraphs: list[dict] = []

    for text, top_y, bottom_y in title_boxes:
        span = content.add(text)
        content.sep("\n")
        paragraphs.append(
            {
                "content": text,
                "role": "title" if text is TITLE_LINES[0][0] else None,
                "boundingRegions": [{"pageNumber": 1, "polygon": to_inches(LEFT, top_y, RIGHT, bottom_y)}],
                "spans": [span],
            }
        )
        for wx0, wy0, wx1, wy1, word, *_ in page.get_text("words"):
            if top_y <= (wy0 + wy1) / 2 <= bottom_y:
                words.append(
                    {
                        "content": word,
                        "polygon": to_inches(wx0, wy0, wx1, wy1),
                        "confidence": round(rng.uniform(0.95, 0.996), 3),
                        "span": {"offset": span["offset"], "length": len(word)},
                    }
                )

    tables = [
        azure_table(cells_1, len(rws_1) - 1, len(cols_1) - 1, content, words, rng),
        azure_table(cells_2, len(rws_2) - 1, len(cols_2) - 1, content, words, rng),
    ]

    layout = {
        "apiVersion": "2024-11-30",
        "modelId": "prebuilt-layout",
        "stringIndexType": "textElements",
        "contentFormat": "text",
        "content": content.build(),
        "pages": [
            {
                "pageNumber": 1,
                "width": AZURE_W,
                "height": AZURE_H,
                "unit": "inch",
                "angle": 0.0,
                "words": words,
                "lines": [],
                "selectionMarks": [],
                "spans": [{"offset": 0, "length": len(content.build())}],
            }
        ],
        "tables": tables,
        "paragraphs": [{k: v for k, v in p.items() if v is not None} for p in paragraphs],
        "sections": [{"elements": ["/tables/0", "/tables/1"], "spans": [{"offset": 0, "length": len(content.build())}]}],
        "styles": [],
    }

    PDF_PATH.write_bytes(pdf_bytes)
    LAYOUT_PATH.write_text(json.dumps(layout, separators=(",", ":")))

    total = sum(len(t["cells"]) for t in tables)
    dropped = sum(1 for c in cells_1 + cells_2 if c.dropped)
    print(f"pdf     : {PDF_PATH.name} ({len(pdf_bytes):,} bytes)")
    print(f"layout  : {LAYOUT_PATH.name}")
    print(f"words   : {len(page.get_text('words'))} in pdf, {len(words)} in layout")
    print(f"tables  : {[(t['rowCount'], t['columnCount'], len(t['cells'])) for t in tables]}")
    print(f"cells   : {total} total, {dropped} nil dashes dropped by azure")
    doc.close()


if __name__ == "__main__":
    main()
