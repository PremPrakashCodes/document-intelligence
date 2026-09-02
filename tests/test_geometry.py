"""Coordinate normalization: the layer every bbox in the system passes through."""

import pytest

from extraction.geometry import (
    BBox,
    calculate_iou,
    calculate_overlap,
    clamp_bbox,
    contains_point,
    intersection,
    normalize_bbox,
    polygon_to_bbox,
    rotate_rect,
    scale_bbox,
    union_bbox,
)


class TestNormalizeBbox:
    def test_orders_reversed_corners(self):
        assert normalize_bbox((10, 20, 5, 8)) == BBox(5, 8, 10, 20)

    def test_leaves_ordered_boxes_alone(self):
        assert normalize_bbox((1, 2, 3, 4)) == BBox(1, 2, 3, 4)

    def test_rejects_wrong_arity(self):
        with pytest.raises(ValueError, match="exactly 4"):
            normalize_bbox((1, 2, 3))


class TestPolygonToBbox:
    def test_takes_axis_aligned_hull(self):
        # Azure sends 4 points clockwise from the top-left.
        assert polygon_to_bbox([1, 1, 5, 1, 5, 3, 1, 3]) == BBox(1, 1, 5, 3)

    def test_hulls_a_skewed_quadrilateral(self):
        # A page scanned at a slight angle: the hull is the conservative read.
        assert polygon_to_bbox([1, 1.2, 5, 1, 5.1, 3, 1.1, 3.2]) == BBox(1, 1, 5.1, 3.2)

    def test_rejects_odd_length(self):
        with pytest.raises(ValueError, match="even count"):
            polygon_to_bbox([1, 2, 3])


class TestRotateRect:
    """PyMuPDF reports text in unrotated space but renders rotated; these are
    the exact matrices and results taken from PyMuPDF itself."""

    @pytest.mark.parametrize(
        ("matrix", "expected"),
        [
            ((1, 0, 0, 1, 0, 0), (100.0, 187.1, 139.3, 203.6)),          # 0
            ((0, 1, -1, 0, 842, 0), (638.4, 100.0, 654.9, 139.3)),        # 90
            ((-1, 0, 0, -1, 595, 842), (455.7, 638.4, 495.0, 654.9)),     # 180
            ((0, -1, 1, 0, 0, 595), (187.1, 455.7, 203.6, 495.0)),        # 270
        ],
    )
    def test_matches_pymupdf(self, matrix, expected):
        result = rotate_rect((100.0, 187.1, 139.3, 203.6), matrix).rounded(1)
        assert result.as_tuple() == expected

    def test_rejects_wrong_arity(self):
        with pytest.raises(ValueError, match="exactly 6"):
            rotate_rect((0, 0, 1, 1), (1, 0, 0, 1))


class TestOverlapAndIou:
    def test_iou_is_symmetric(self):
        a, b = BBox(0, 0, 10, 10), BBox(5, 5, 15, 15)
        assert calculate_iou(a, b) == pytest.approx(calculate_iou(b, a))

    def test_iou_of_disjoint_boxes_is_zero(self):
        assert calculate_iou(BBox(0, 0, 1, 1), BBox(5, 5, 6, 6)) == 0.0

    def test_iou_of_identical_boxes_is_one(self):
        assert calculate_iou(BBox(0, 0, 4, 4), BBox(0, 0, 4, 4)) == 1.0

    def test_containment_ignores_outer_size(self):
        """The property that makes containment the right matching test: a word
        fully inside its cell scores 1.0 whatever the cell's padding."""
        word = BBox(10, 10, 12, 14)
        for cell in (BBox(0, 0, 20, 20), BBox(0, 0, 200, 40), BBox(9, 9, 13, 15)):
            assert calculate_overlap(word, cell) == 1.0

    def test_iou_by_contrast_collapses_with_padding(self):
        """Why IoU is not used: the same perfect match scores near zero."""
        word = BBox(10, 10, 12, 14)
        assert calculate_iou(word, BBox(0, 0, 200, 40)) < 0.002

    def test_partial_containment_is_the_area_fraction(self):
        # Half the word's width sits inside.
        assert calculate_overlap(BBox(0, 0, 10, 10), BBox(5, 0, 20, 10)) == pytest.approx(0.5)

    def test_zero_area_box_falls_back_to_its_position(self):
        assert calculate_overlap(BBox(5, 5, 5, 5), BBox(0, 0, 10, 10)) == 1.0
        assert calculate_overlap(BBox(50, 5, 50, 5), BBox(0, 0, 10, 10)) == 0.0

    def test_containment_above_half_is_exclusive(self):
        """The invariant the matcher's membership rule depends on: in a
        non-overlapping grid, a word can exceed 0.5 in at most one cell."""
        left, right = BBox(0, 0, 10, 10), BBox(10, 0, 20, 10)
        straddler = BBox(8, 0, 13, 10)  # 40% left, 60% right
        scores = [calculate_overlap(straddler, left), calculate_overlap(straddler, right)]
        assert sum(1 for score in scores if score > 0.5) == 1


class TestHelpers:
    def test_intersection_returns_none_when_disjoint(self):
        assert intersection(BBox(0, 0, 1, 1), BBox(2, 2, 3, 3)) is None

    def test_touching_edges_do_not_intersect(self):
        assert intersection(BBox(0, 0, 5, 5), BBox(5, 0, 10, 5)) is None

    def test_scale_bbox_scales_about_the_origin(self):
        assert scale_bbox(BBox(1, 2, 3, 4), 10, 100) == BBox(10, 200, 30, 400)

    def test_union_of_nothing_is_none(self):
        assert union_bbox([]) is None

    def test_union_covers_every_input(self):
        assert union_bbox([BBox(5, 5, 6, 6), BBox(1, 2, 3, 4)]) == BBox(1, 2, 6, 6)

    def test_clamp_keeps_boxes_on_the_page(self):
        assert clamp_bbox(BBox(-5, -5, 700, 900), 595, 842) == BBox(0, 0, 595, 842)

    def test_contains_point_tolerates_float_noise(self):
        assert contains_point(BBox(0, 0, 10, 10), (10.02, 5))
        assert not contains_point(BBox(0, 0, 10, 10), (10.5, 5))

