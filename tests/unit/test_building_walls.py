"""Tests for SVG rendering of Building exterior walls.

Brick and stone share one implementation: a chain of rounded
rounded <rect> elements laid down in two running-bond courses,
with a tight width jitter so units read as regularly sized.
Fill / stroke colour is the only difference between the two
materials. See design/building_generator.md section 7.
"""

import re

import pytest

from nhc.rendering._building_walls import (
    BRICK_FILL,
    BRICK_SEAM,
    MASONRY_CORNER_RADIUS,
    MASONRY_MEAN_WIDTH,
    MASONRY_STRIP_COUNT,
    MASONRY_WALL_THICKNESS,
    MASONRY_WIDTH_HIGH,
    MASONRY_WIDTH_LOW,
    STONE_FILL,
    STONE_SEAM,
    render_brick_wall_run,
    render_stone_wall_run,
)


def _parse_rects(items: list[str]) -> list[dict]:
    rects = []
    for s in items:
        if "<rect" not in s:
            continue
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', s))
        rects.append(attrs)
    return rects


class _SharedRunBehaviour:
    """Mixin of tests that both materials must satisfy."""

    renderer = None  # set by subclasses via staticmethod
    material_fill = None
    material_stroke = None

    def _render(self, *a, **kw):
        return type(self).renderer(*a, **kw)

    # ── signature ──

    def test_returns_list_of_strings(self):
        out = self._render(0, 50, 200, 50)
        assert isinstance(out, list)
        assert all(isinstance(s, str) for s in out)

    def test_zero_length_returns_empty(self):
        assert self._render(50, 50, 50, 50) == []

    def test_diagonal_run_renders_with_rotation(self):
        """Diagonal runs now emit rotated rects (per-rect
        transform='translate(...) rotate(...)')."""
        out = self._render(0, 0, 100, 100, seed=1)
        assert out
        rotated = [
            s for s in out
            if 'transform="translate(' in s and 'rotate(' in s
        ]
        assert rotated, (
            f"expected rotated rects on a diagonal run, got "
            f"{out[:1]}"
        )

    # ── per-unit rounded rects ──

    def test_emits_rounded_rects_only(self):
        out = self._render(0, 50, 200, 50, seed=1)
        rects = _parse_rects(out)
        assert rects
        for a in rects:
            assert a["fill"] == self.material_fill
            assert a["stroke"] == self.material_stroke
            assert "rx" in a and "ry" in a
            assert float(a["rx"]) == MASONRY_CORNER_RADIUS
            assert float(a["ry"]) == MASONRY_CORNER_RADIUS

    def test_no_non_rect_elements(self):
        """No <line>, no <path>, no background polygons -- only
        individual unit rects."""
        out = self._render(0, 50, 200, 50, seed=1)
        for s in out:
            assert s.lstrip().startswith("<rect "), (
                f"unexpected non-rect element: {s[:40]!r}"
            )

    # ── two strips ──

    def test_horizontal_run_has_two_y_rows(self):
        out = self._render(0, 100, 300, 100, seed=2)
        ys = {float(a["y"]) for a in _parse_rects(out)}
        assert len(ys) == MASONRY_STRIP_COUNT

    def test_vertical_run_has_two_x_columns(self):
        out = self._render(50, 0, 50, 300, seed=2)
        xs = {float(a["x"]) for a in _parse_rects(out)}
        assert len(xs) == MASONRY_STRIP_COUNT

    # ── regular width distribution ──

    def test_widths_stay_within_regular_jitter(self):
        out = self._render(0, 50, 1000, 50, seed=5)
        widths = [float(a["width"]) for a in _parse_rects(out)]
        # Last unit of each strip may be clipped to fit the run,
        # but the rest stay within the configured jitter band.
        mean = MASONRY_MEAN_WIDTH
        # Allow one clipped unit per strip (the tail).
        tail_tolerance = MASONRY_STRIP_COUNT
        within = [
            w for w in widths
            if mean * MASONRY_WIDTH_LOW - 0.01 <= w
            <= mean * MASONRY_WIDTH_HIGH + 0.01
        ]
        outliers = len(widths) - len(within)
        assert outliers <= tail_tolerance, (
            f"{outliers} widths outside [{mean * MASONRY_WIDTH_LOW}, "
            f"{mean * MASONRY_WIDTH_HIGH}]"
        )

    def test_width_range_tight(self):
        out = self._render(0, 50, 1000, 50, seed=5)
        widths = [float(a["width"]) for a in _parse_rects(out)]
        # Keep only widths inside the jitter band; clipped end-of-
        # strip tails are smaller than MASONRY_WIDTH_LOW * mean.
        mean = MASONRY_MEAN_WIDTH
        in_band = [
            w for w in widths
            if w >= mean * MASONRY_WIDTH_LOW - 0.01
        ]
        assert len(in_band) > 20
        spread = max(in_band) - min(in_band)
        # ±10% of 12 = 2.4px theoretical max; small margin for
        # 1-decimal SVG rounding.
        assert spread <= 3.0

    # ── no gaps ──

    def test_no_page_background_overlays(self):
        """Walls are fully filled: no background-coloured gap rects."""
        from nhc.rendering._svg_helpers import BG
        out = self._render(0, 50, 1200, 50, seed=1)
        for a in _parse_rects(out):
            assert a["fill"] != BG

    def test_adjacent_units_in_strip_have_no_gap(self):
        """Along each strip, consecutive unit rects abut or overlap
        (sub-pixel tolerance for .1f SVG rounding)."""
        out = self._render(0, 50, 400, 50, seed=3)
        rects = _parse_rects(out)
        rows: dict[float, list[dict]] = {}
        for a in rects:
            rows.setdefault(float(a["y"]), []).append(a)
        for row_rects in rows.values():
            row_rects.sort(key=lambda a: float(a["x"]))
            for prev, curr in zip(row_rects, row_rects[1:]):
                prev_right = float(prev["x"]) + float(prev["width"])
                curr_left = float(curr["x"])
                gap = curr_left - prev_right
                # One-decimal SVG formatting can introduce up to
                # 0.1 px of apparent gap or overlap per unit.
                assert gap <= 0.15, (
                    f"gap of {gap:.2f}px between units at "
                    f"x={prev['x']} and x={curr['x']}"
                )

    # ── seed determinism ──

    def test_same_seed_same_output(self):
        a = self._render(0, 50, 200, 50, seed=42)
        b = self._render(0, 50, 200, 50, seed=42)
        assert a == b

    def test_different_seeds_different_output(self):
        a = self._render(0, 50, 200, 50, seed=1)
        b = self._render(0, 50, 200, 50, seed=2)
        assert a != b


class TestBrickWallRun(_SharedRunBehaviour):
    renderer = staticmethod(render_brick_wall_run)
    material_fill = BRICK_FILL
    material_stroke = BRICK_SEAM


class TestStoneWallRun(_SharedRunBehaviour):
    renderer = staticmethod(render_stone_wall_run)
    material_fill = STONE_FILL
    material_stroke = STONE_SEAM


class TestMaterialContrast:
    def test_fills_differ(self):
        assert BRICK_FILL != STONE_FILL

    def test_strokes_differ(self):
        assert BRICK_SEAM != STONE_SEAM

    def test_same_seed_different_material_different_output(self):
        b = render_brick_wall_run(0, 50, 200, 50, seed=11)
        s = render_stone_wall_run(0, 50, 200, 50, seed=11)
        assert b != s

    def test_same_seed_same_geometry_across_materials(self):
        """Apart from fill/stroke, brick and stone produce the
        same x/y/width/height values under the same seed."""
        b = _parse_rects(render_brick_wall_run(0, 50, 200, 50, seed=7))
        s = _parse_rects(render_stone_wall_run(0, 50, 200, 50, seed=7))
        assert len(b) == len(s)
        for rb, rs in zip(b, s):
            assert rb["x"] == rs["x"]
            assert rb["y"] == rs["y"]
            assert rb["width"] == rs["width"]
            assert rb["height"] == rs["height"]


class TestMasonryConstants:
    def test_strip_count_is_two(self):
        assert MASONRY_STRIP_COUNT == 2

    def test_wall_thickness_positive(self):
        assert MASONRY_WALL_THICKNESS > 0

    def test_width_jitter_is_regular(self):
        """±10% around the mean is the "regular sizing" target."""
        assert 0.85 <= MASONRY_WIDTH_LOW <= 0.95
        assert 1.05 <= MASONRY_WIDTH_HIGH <= 1.15
