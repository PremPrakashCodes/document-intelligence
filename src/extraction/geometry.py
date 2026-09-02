"""Coordinate normalization shared by every extractor.

Canonical space
---------------
All bounding boxes in the canonical document live in **page display space**:

* origin at the top-left of the page as a human sees it,
* units of PDF points (1/72 inch),
* axis-aligned, `x0 <= x1` and `y0 <= y1`,
* page size equal to PyMuPDF's `page.rect`, i.e. **after** `/Rotate`.

The two extractors do not natively agree on this, so both are converted:

* **PyMuPDF** reports text in the *unrotated* mediabox space. On a page with
  `/Rotate 90` a word sits at (100, 187) while the rendered pixmap is
  842x595 - the box would land off-page. `page.rotation_matrix` maps it into
  display space; `rotate_rect` applies it. Rendering (`get_pixmap`) is already
  in display space, so overlays line up with no further calibration.
* **Azure DI** reports 4-point polygons in the units named
  by `page.unit` ("inch" for PDFs, "pixel" for images), relative to a page it
  has already turned upright. `polygon_to_bbox` takes the axis-aligned hull and
  `scale_bbox` rescales it by the ratio of the two page sizes, which converts
  inches or pixels to points without assuming a DPI.

Everything here is pure, deterministic, and free of PDF library types so it can
be unit-tested directly and reused by the matcher.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import NamedTuple

# A bbox is (x0, y0, x1, y1) in page display space.
BBoxTuple = tuple[float, float, float, float]

# Boxes closer than this on every edge are treated as identical. Chosen at a
# twentieth of a point: far below the width of a rendered pixel at any sane
# zoom, but large enough to absorb float noise from matrix multiplication.
EPSILON = 0.05


class BBox(NamedTuple):
    """An axis-aligned box in page display space (points, top-left origin)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    def as_tuple(self) -> BBoxTuple:
        return (self.x0, self.y0, self.x1, self.y1)

    def rounded(self, digits: int = 2) -> BBox:
        """A copy rounded to `digits`, so serialized output is stable."""
        return BBox(*(round(v, digits) for v in self))


def normalize_bbox(values: Sequence[float]) -> BBox:
    """Coerce any 4-number box into a canonical, correctly-ordered `BBox`.

    Accepts the (x0, y0, x1, y1) that PyMuPDF and Azure DI both eventually
    produce in either corner order, and swaps the edges so the result always
    satisfies `x0 <= x1` and `y0 <= y1`.
    """
    if len(values) != 4:
        raise ValueError(f"A bbox needs exactly 4 numbers, got {len(values)}")
    x0, y0, x1, y1 = (float(v) for v in values)
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return BBox(x0, y0, x1, y1)


def polygon_to_bbox(polygon: Sequence[float]) -> BBox:
    """Axis-aligned hull of an Azure DI polygon.

    Azure sends a flat `[x1, y1, x2, y2, x3, y3, x4, y4]` running clockwise
    from the top-left. The quadrilateral is only non-rectangular when the page
    is skewed; the hull is the honest conservative reading of it either way.
    """
    if len(polygon) < 4 or len(polygon) % 2 != 0:
        raise ValueError(f"A polygon needs an even count of at least 4 values, got {len(polygon)}")
    xs = [float(v) for v in polygon[0::2]]
    ys = [float(v) for v in polygon[1::2]]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def scale_bbox(box: BBox, scale_x: float, scale_y: float) -> BBox:
    """Scale a box about the page origin (top-left), which both spaces share."""
    return BBox(box.x0 * scale_x, box.y0 * scale_y, box.x1 * scale_x, box.y1 * scale_y)


def rotate_rect(box: Sequence[float], matrix: Sequence[float]) -> BBox:
    """Apply a PyMuPDF-style 6-tuple matrix `(a, b, c, d, e, f)` to a box.

    PyMuPDF's own `Rect * Matrix` does exactly this, but keeping it here means
    the transform is testable without constructing a document, and the rest of
    the geometry layer stays free of PDF library types. Because a rotation may
    reorder the corners, all four are transformed and re-hulled.
    """
    if len(matrix) != 6:
        raise ValueError(f"A matrix needs exactly 6 values, got {len(matrix)}")
    a, b, c, d, e, f = (float(v) for v in matrix)
    x0, y0, x1, y1 = normalize_bbox(box)
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    points = [(x * a + y * c + e, x * b + y * d + f) for x, y in corners]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def intersection(first: BBox, second: BBox) -> BBox | None:
    """The overlapping region, or None when the boxes are disjoint."""
    x0 = max(first.x0, second.x0)
    y0 = max(first.y0, second.y0)
    x1 = min(first.x1, second.x1)
    y1 = min(first.y1, second.y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(x0, y0, x1, y1)


def intersection_area(first: BBox, second: BBox) -> float:
    overlap = intersection(first, second)
    return overlap.area if overlap else 0.0


def calculate_iou(first: BBox, second: BBox) -> float:
    """Intersection over union, in [0, 1].

    Symmetric, so it answers "are these the same region?" rather than "is one
    inside the other?" - use `calculate_overlap` for the latter.
    """
    overlap = intersection_area(first, second)
    if overlap <= 0.0:
        return 0.0
    union = first.area + second.area - overlap
    if union <= 0.0:
        return 0.0
    return overlap / union


def calculate_overlap(inner: BBox, outer: BBox) -> float:
    """Fraction of `inner`'s area that falls inside `outer`, in [0, 1].

    This, not IoU, is the right test for "does this word belong to that cell":
    a word is far smaller than the cell containing it, so their IoU is tiny
    even on a perfect match, while containment is 1.0.
    """
    if inner.area <= 0.0:
        # A zero-area box (an empty span, a hairline rule) still has a
        # position, so fall back to asking whether that position is inside.
        return 1.0 if contains_point(outer, inner.center) else 0.0
    return intersection_area(inner, outer) / inner.area


def contains_point(box: BBox, point: tuple[float, float]) -> bool:
    x, y = point
    return box.x0 - EPSILON <= x <= box.x1 + EPSILON and box.y0 - EPSILON <= y <= box.y1 + EPSILON


def union_bbox(boxes: Iterable[BBox]) -> BBox | None:
    """Smallest box covering every input, or None when there are no inputs."""
    boxes = list(boxes)
    if not boxes:
        return None
    return BBox(
        min(b.x0 for b in boxes),
        min(b.y0 for b in boxes),
        max(b.x1 for b in boxes),
        max(b.y1 for b in boxes),
    )


def clamp_bbox(box: BBox, width: float, height: float) -> BBox:
    """Clip a box to the page, so rounding never pushes an overlay off-canvas."""
    return BBox(
        min(max(box.x0, 0.0), width),
        min(max(box.y0, 0.0), height),
        min(max(box.x1, 0.0), width),
        min(max(box.y1, 0.0), height),
    )

