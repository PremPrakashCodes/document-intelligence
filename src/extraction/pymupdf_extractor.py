"""PyMuPDF extraction: the deterministic half of the pipeline.

This module owns everything a PDF can state about itself - metadata, page
geometry, exact text and its coordinates, images, links, annotations, fonts.
Azure DI never overrides any of it.

Three invariants matter:

1. **Display space.** PyMuPDF reports text in the unrotated mediabox space but
   renders in the rotated space. Every box produced here is pushed through
   `page.rotation_matrix` first, so text coordinates and rendered pixels agree
   on a `/Rotate 90` page. See `geometry` for the derivation.
2. **Determinism.** No heuristics beyond the documented scanned-page
   threshold, and no ordering that depends on dict iteration - the same bytes
   always produce byte-identical canonical output.
3. **Clip paths place text; they do not censor it.** MuPDF crops extracted
   text to the page's clip paths by default, which truncates every label a
   spreadsheet overflowed past its column. Extraction runs with that off, so
   the text layer is what the PDF says rather than what it happens to show -
   but the clip is still read, because *where* a run is shown is what says
   which cell owns it. A word therefore carries all of its text and only the
   box it is visible in. See `_TEXT_FLAGS` and `_WORD_FLAGS`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import pymupdf

from extraction.errors import EmptyPdfError, EncryptedPdfError, InvalidPdfError
from extraction.geometry import BBox, clamp_bbox, normalize_bbox, rotate_rect, union_bbox
from extraction.types import (
    Annotation,
    Block,
    Font,
    Image,
    Line,
    Link,
    Page,
    PageContent,
    PageGeometry,
    Span,
    Word,
)

log = logging.getLogger(__name__)

# PyMuPDF block type codes from `get_text("dict")`.
_BLOCK_TEXT = 0
_BLOCK_IMAGE = 1

# MuPDF applies the page's *clip paths* to extracted text by default. That is
# right for a rendering device and wrong for a text layer: a spreadsheet
# printed to PDF gives every cell its own clip rectangle, so a label wider than
# its column is drawn in full and then cropped. The characters are in the
# content stream - "FORM NL-39- AGEING OF CLAIMS" - but the default flags hand
# back "RM NL-39- AGEING OF CLAIMS", and Azure DI, which reads the rendered
# page, agrees with the crop. Dropping the flag recovers what the PDF actually
# says, which is the whole point of running PyMuPDF at all.
#
# The flag does not gate off-page text: MuPDF discards anything drawn outside
# the mediabox either way, so the only thing this changes is text a clip path
# was hiding.
_TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_CLIP
_DICT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_CLIP

# Words are extracted twice, and the two passes answer different questions.
#
# `_WORD_FLAGS` (unclipped) answers *what the word says*. `_SHOWN_WORD_FLAGS`
# (clipped, MuPDF's default) answers *where it is shown* - which is the same
# question as "whose cell is it in", because the clip rectangle a spreadsheet
# puts around a label is that label's column. `_words` joins them: full text,
# shown box. Without the second pass a run wide enough to overflow scatters its
# own words across three columns - page 6 of the sample filing draws
# "Public/ Product Liability" centred on a 35pt column, and area containment
# alone hands "Public/" to the column on the left, keeps "Product", and gives
# "Liability" to the column on the right. The clip says all three are one
# column's, and the clip is the PDF author speaking.
#
# Both passes ask for `rawdict`, and the join is made on individual glyphs,
# because a glyph is the only unit MuPDF will not rearrange. Clipping never
# moves or crops a glyph - it drops the ones that fall outside - so a glyph
# that survives is at the same origin in both passes, and a word's shown box is
# the union of its own surviving glyphs. Nothing coarser holds: asked for the
# clipped page, MuPDF will merge two runs whose fragments end up adjacent into
# a single word *and* a single span, even under `PRESERVE_SPANS`, so
# "Health" and the surviving "c/" of "Public/" come back fused as "Healthc/"
# and there is no fragment left to attribute to either run.
#
# The unclipped pass keeps `PRESERVE_SPANS` for the same reason in reverse:
# without it MuPDF merges two runs that touch into one span, and `_words`
# splits words at span boundaries, so the run boundary has to survive that far.
# A run is one `Tj`, one thing the PDF drew in one go, and it is the honest
# place to stop merging - a word broken across runs by kerning is a single run
# per fragment only in theory, and in practice never overlaps its neighbour.
_WORD_FLAGS = (pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_CLIP) | pymupdf.TEXT_PRESERVE_SPANS
_SHOWN_WORD_FLAGS = pymupdf.TEXTFLAGS_RAWDICT

_LINK_KINDS = {
    pymupdf.LINK_NONE: "none",
    pymupdf.LINK_GOTO: "goto",
    pymupdf.LINK_URI: "uri",
    pymupdf.LINK_LAUNCH: "launch",
    pymupdf.LINK_NAMED: "named",
    pymupdf.LINK_GOTOR: "gotor",
}


def _glyph_key(char: dict) -> tuple[float, float, str]:
    """Identity of one drawn glyph: what it is and where it was put.

    Rounded to a hundredth of a point, far below the tolerance anything else
    here works at, so the same glyph reported by two passes always agrees.
    """
    origin = char["origin"]
    return (round(origin[0], 2), round(origin[1], 2), char["c"])


def _shown_glyphs(page: pymupdf.Page) -> set[tuple[float, float, str]]:
    """Every glyph the page's clip paths actually leave visible."""
    return {
        _glyph_key(char)
        for block in page.get_text("rawdict", flags=_SHOWN_WORD_FLAGS)["blocks"]
        if block["type"] == _BLOCK_TEXT
        for line in block.get("lines", [])
        for span in line["spans"]
        for char in span["chars"]
    }


def _span_words(chars: Sequence[dict]) -> list[list[dict]]:
    """A run's glyphs grouped into words, split on whitespace.

    Words are built per run rather than taken from `get_text("words")` because
    that splits on whitespace *alone*: two runs that touch with no space
    between them - two overflowing column headers, or a label and its
    superscript footnote marker - come back as one word, which is then assigned
    to one cell whole. A word never spans two runs, so this cannot happen here.
    """
    words: list[list[dict]] = []
    current: list[dict] = []
    for char in chars:
        if char["c"].isspace():
            if current:
                words.append(current)
                current = []
            continue
        current.append(char)
    if current:
        words.append(current)
    return words


class PdfExtractor:
    """Extracts deterministic PDF data. Stateless; safe to share."""

    def __init__(self, *, text_layer_min_chars: int = 24) -> None:
        self._text_layer_min_chars = text_layer_min_chars

    @property
    def version(self) -> str:
        return pymupdf.__version__

    # --- document lifecycle -------------------------------------------------

    def open(self, data: bytes) -> pymupdf.Document:
        """Open PDF bytes, raising a typed failure for anything unusable.

        An encrypted document is given the empty password first: many filings
        are "protected" only against editing and open fine that way.
        """
        if not data:
            raise EmptyPdfError("The uploaded file is empty")
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as err:  # MuPDF raises bare exceptions for bad input
            raise InvalidPdfError(f"Could not open the PDF: {err}") from err

        if doc.needs_pass:
            # authenticate() returns 0 on failure, non-zero for the access
            # level it granted.
            if not doc.authenticate(""):
                doc.close()
                raise EncryptedPdfError("The PDF is password-protected")

        if doc.page_count == 0:
            doc.close()
            raise EmptyPdfError("The PDF has no pages")
        return doc

    def metadata(self, doc: pymupdf.Document) -> dict[str, str]:
        """The /Info dictionary, with empty entries dropped."""
        raw = doc.metadata or {}
        return {key: str(value) for key, value in sorted(raw.items()) if value}

    # --- pages --------------------------------------------------------------

    def extract_pages(self, doc: pymupdf.Document) -> list[Page]:
        return [self.extract_page(doc, number) for number in range(doc.page_count)]

    def extract_page(self, doc: pymupdf.Document, index: int) -> Page:
        """One page, fully described, with every box in display space."""
        page = doc[index]
        matrix = tuple(page.rotation_matrix)
        rect = page.rect
        width, height = rect.width, rect.height

        geometry = PageGeometry(
            width=round(width, 2),
            height=round(height, 2),
            rotation=page.rotation,
            mediabox=normalize_bbox(tuple(page.mediabox)).rounded().as_tuple(),
        )

        text = page.get_text("text", flags=_TEXT_FLAGS)
        blocks, images_in_blocks = self._blocks(page, matrix, width, height)
        content = PageContent(
            text=text,
            blocks=blocks,
            words=self._words(page, matrix, width, height),
            images=self._images(page, images_in_blocks, matrix, width, height),
            links=self._links(page, matrix, width, height),
            annotations=self._annotations(page, matrix, width, height),
            fonts=self._fonts(page),
        )

        return Page(
            page_number=index + 1,
            geometry=geometry,
            has_text_layer=len(text.strip()) >= self._text_layer_min_chars,
            content=content,
        )

    # --- primitives ---------------------------------------------------------

    def _box(self, raw: Sequence[float], matrix: Sequence[float], width: float, height: float) -> BBox:
        """Map a raw PyMuPDF box into clamped, rounded display space."""
        return clamp_bbox(rotate_rect(raw, matrix), width, height).rounded()

    def _blocks(
        self, page: pymupdf.Page, matrix: Sequence[float], width: float, height: float
    ) -> tuple[list[Block], dict[int, BBox]]:
        """Text and image blocks in PyMuPDF's order.

        Image blocks are returned separately as well, keyed by block number:
        `get_text("dict")` knows where an image was *placed*, which
        `get_images()` does not, so the two are joined in `_images`.
        """
        blocks: list[Block] = []
        image_boxes: dict[int, BBox] = {}

        for raw_block in page.get_text("dict", flags=_DICT_FLAGS)["blocks"]:
            number = raw_block["number"]
            box = self._box(raw_block["bbox"], matrix, width, height)

            if raw_block["type"] == _BLOCK_IMAGE:
                image_boxes[number] = box
                blocks.append(Block(number=number, type="image", bbox=box.as_tuple()))
                continue

            lines = [
                Line(
                    bbox=self._box(raw_line["bbox"], matrix, width, height).as_tuple(),
                    direction=tuple(raw_line.get("dir", (1.0, 0.0))),
                    spans=[
                        Span(
                            text=raw_span["text"],
                            bbox=self._box(raw_span["bbox"], matrix, width, height).as_tuple(),
                            font=raw_span.get("font", ""),
                            size=round(raw_span.get("size", 0.0), 2),
                            flags=raw_span.get("flags", 0),
                            color=raw_span.get("color", 0),
                        )
                        for raw_span in raw_line["spans"]
                    ],
                )
                for raw_line in raw_block.get("lines", [])
            ]
            blocks.append(Block(number=number, type="text", bbox=box.as_tuple(), lines=lines))

        return blocks, image_boxes

    def _words(self, page: pymupdf.Page, matrix: Sequence[float], width: float, height: float) -> list[Word]:
        """Word-level boxes - the unit the table matcher works in.

        Each word takes its *text* from every glyph the run drew and its *box*
        from the glyphs the page actually shows, so `text` is the whole of what
        the word says and `bbox` is the part of it a reader can see. The two
        differ exactly when a PDF draws a label wider than the cell it belongs
        to, and both consumers want the shown box: the matcher, because the
        clip is what says which cell the word is in, and the overlay, because a
        highlight belongs on visible glyphs.

        A word hidden completely keeps the box the PDF drew it at. There is
        nothing better to say about where it is, and it is the reading the
        earlier, clip-respecting extraction would have thrown away entirely.
        """
        shown = _shown_glyphs(page)
        words: list[Word] = []

        for block in page.get_text("rawdict", flags=_WORD_FLAGS)["blocks"]:
            if block["type"] != _BLOCK_TEXT:
                continue
            for line_number, line in enumerate(block.get("lines", [])):
                # Numbered across the line, not the run, to match the (block,
                # line, word) reading order MuPDF's own `words` output uses.
                word_number = 0
                for span in line["spans"]:
                    for chars in _span_words(span["chars"]):
                        visible = [c["bbox"] for c in chars if _glyph_key(c) in shown]
                        box = union_bbox(
                            [normalize_bbox(b) for b in (visible or [c["bbox"] for c in chars])]
                        )
                        if box is None:
                            continue
                        words.append(
                            Word(
                                text="".join(c["c"] for c in chars),
                                bbox=self._box(box, matrix, width, height).as_tuple(),
                                block=block["number"],
                                line=line_number,
                                word=word_number,
                            )
                        )
                        word_number += 1
        return words

    def _images(
        self,
        page: pymupdf.Page,
        block_boxes: dict[int, BBox],
        matrix: Sequence[float],
        width: float,
        height: float,
    ) -> list[Image]:
        """Embedded images joined to where they were drawn.

        `get_image_bbox` is authoritative but raises for images referenced
        through a form XObject; the block boxes collected above are the
        fallback, matched by draw order.
        """
        placements = sorted(block_boxes.items())
        images: list[Image] = []

        for position, raw in enumerate(page.get_images(full=True)):
            xref, _smask, img_width, img_height, bpc, colorspace, *_ = raw
            box: BBox | None = None
            try:
                box = self._box(tuple(page.get_image_bbox(raw)), matrix, width, height)
            except (ValueError, RuntimeError):
                box = None
            if box is None or box.area <= 0:
                box = placements[position][1] if position < len(placements) else None
            if box is None:
                # Referenced but never drawn on this page; nothing to show.
                continue
            images.append(
                Image(
                    xref=xref,
                    bbox=box.as_tuple(),
                    width=img_width,
                    height=img_height,
                    colorspace=colorspace or None,
                    bits_per_component=bpc,
                )
            )
        return images

    def _links(self, page: pymupdf.Page, matrix: Sequence[float], width: float, height: float) -> list[Link]:
        links: list[Link] = []
        for raw in page.get_links():
            target = raw.get("page")
            links.append(
                Link(
                    kind=_LINK_KINDS.get(raw.get("kind"), "unknown"),
                    bbox=self._box(tuple(raw["from"]), matrix, width, height).as_tuple(),
                    uri=raw.get("uri"),
                    # PyMuPDF numbers link targets from 0; the canonical
                    # schema numbers pages from 1 everywhere.
                    target_page=target + 1 if isinstance(target, int) and target >= 0 else None,
                )
            )
        return links

    def _annotations(
        self, page: pymupdf.Page, matrix: Sequence[float], width: float, height: float
    ) -> list[Annotation]:
        annotations: list[Annotation] = []
        for annot in page.annots():
            info = annot.info or {}
            annotations.append(
                Annotation(
                    # annot.type is (code, name); the name is the useful half.
                    type=annot.type[1] if len(annot.type) > 1 else str(annot.type[0]),
                    bbox=self._box(tuple(annot.rect), matrix, width, height).as_tuple(),
                    content=info.get("content") or None,
                    author=info.get("title") or None,
                )
            )
        return annotations

    def _fonts(self, page: pymupdf.Page) -> list[Font]:
        """Fonts referenced by this page.

        `get_fonts(full=True)` yields
        `(xref, ext, type, basefont, name, encoding, referencer)`; `ext` is
        "n/a" for a font that is not embedded.
        """
        fonts: list[Font] = []
        for raw in page.get_fonts(full=True):
            xref, ext, font_type, basefont, _name, encoding, *_ = raw
            fonts.append(
                Font(
                    xref=xref,
                    name=basefont,
                    type=font_type,
                    encoding=encoding or None,
                    embedded=bool(ext) and ext != "n/a",
                )
            )
        return fonts

    # --- rendering ----------------------------------------------------------

    def render_page(self, doc: pymupdf.Document, index: int, *, scale: float = 2.0) -> bytes:
        """Render one page to PNG at `scale` (1.0 == 72 dpi).

        `get_pixmap` works in display space, the same space every canonical
        bbox lives in, so the frontend positions an overlay with a bare
        multiply by `scale` - no calibration, no rotation handling client-side.
        """
        page = doc[index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")
