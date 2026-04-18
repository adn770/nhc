"""Tests for SVG rendering of Building exterior walls (M4+).

See design/building_generator.md section 7 (Rendering) for the
full specification. M4 covers the brick-wall 3-strip renderer.
"""

import re

import pytest

from nhc.rendering._building_walls import (
    BRICK_FILL,
    BRICK_MISSING,
    BRICK_SEAM,
    BRICK_STRIP_COUNT,
    BRICK_WALL_THICKNESS,
    STONE_CORNER_RADIUS,
    STONE_FILL,
    STONE_MISSING_PROBABILITY,
    STONE_SEAM,
    render_brick_wall_run,
    render_stone_wall_run,
)


class TestBrickWallRunSignature:
    def test_returns_list_of_strings(self):
        out = render_brick_wall_run(0, 50, 200, 50)
        assert isinstance(out, list)
        assert all(isinstance(s, str) for s in out)

    def test_zero_length_returns_empty(self):
        assert render_brick_wall_run(50, 50, 50, 50) == []

    def test_diagonal_run_rejected(self):
        with pytest.raises(ValueError):
            render_brick_wall_run(0, 0, 20, 10)


class TestBrickWallRunHorizontal:
    def test_three_strip_backgrounds(self):
        out = render_brick_wall_run(0, 50, 200, 50, seed=1)
        strip_bgs = [s for s in out if f'fill="{BRICK_FILL}"' in s]
        assert len(strip_bgs) == BRICK_STRIP_COUNT

    def test_strip_background_spans_full_run(self):
        out = render_brick_wall_run(0, 50, 200, 50, seed=1)
        strip_bgs = [s for s in out if f'fill="{BRICK_FILL}"' in s]
        for bg in strip_bgs:
            assert 'width="200.0"' in bg

    def test_emits_brick_seam_lines(self):
        out = render_brick_wall_run(0, 50, 200, 50, seed=1)
        seams = [
            s for s in out if f'stroke="{BRICK_SEAM}"' in s
            and '<line' in s
        ]
        # 200px / ~12px mean brick width ~= 17 bricks per strip,
        # so 16 seams per strip, 48+ total.
        assert len(seams) > 20


class TestBrickWallRunVertical:
    def test_three_strip_backgrounds(self):
        out = render_brick_wall_run(50, 0, 50, 200, seed=1)
        strip_bgs = [s for s in out if f'fill="{BRICK_FILL}"' in s]
        assert len(strip_bgs) == BRICK_STRIP_COUNT

    def test_strip_background_spans_full_run(self):
        out = render_brick_wall_run(50, 0, 50, 200, seed=1)
        strip_bgs = [s for s in out if f'fill="{BRICK_FILL}"' in s]
        for bg in strip_bgs:
            assert 'height="200.0"' in bg


class TestBrickWallDeterminism:
    def test_same_seed_produces_same_output(self):
        a = render_brick_wall_run(0, 50, 200, 50, seed=42)
        b = render_brick_wall_run(0, 50, 200, 50, seed=42)
        assert a == b

    def test_different_seeds_produce_different_output(self):
        a = render_brick_wall_run(0, 50, 200, 50, seed=1)
        b = render_brick_wall_run(0, 50, 200, 50, seed=2)
        assert a != b

    def test_same_seed_across_orientations(self):
        """Horizontal and vertical with same seed differ (different coords)."""
        h = render_brick_wall_run(0, 50, 200, 50, seed=7)
        v = render_brick_wall_run(50, 0, 50, 200, seed=7)
        assert h != v


class TestBrickMissingOverlays:
    def test_long_wall_has_some_missing_bricks(self):
        """Over hundreds of bricks, expect a handful of missing."""
        out = render_brick_wall_run(0, 50, 1200, 50, seed=1)
        missing = [s for s in out if f'fill="{BRICK_MISSING}"' in s]
        # ~5% of ~100 bricks per strip * 3 strips ~= 15 missing on avg
        assert 1 <= len(missing) < 80

    def test_missing_bricks_are_rects(self):
        out = render_brick_wall_run(0, 50, 1200, 50, seed=1)
        missing = [s for s in out if f'fill="{BRICK_MISSING}"' in s]
        for s in missing:
            assert s.lstrip().startswith("<rect ")


class TestBrickStripStagger:
    def test_strip_seams_do_not_all_align(self):
        """Running-bond: the three courses use different offsets."""
        out = render_brick_wall_run(0, 50, 300, 50, seed=3)

        # Split output into groups by strip: each strip begins with
        # its background rect, followed by seams/missing for that strip.
        strips: list[list[str]] = []
        current: list[str] = []
        for s in out:
            if f'fill="{BRICK_FILL}"' in s:
                if current:
                    strips.append(current)
                current = [s]
            else:
                current.append(s)
        if current:
            strips.append(current)

        assert len(strips) == BRICK_STRIP_COUNT

        # Extract the first seam x-coord for each strip from its
        # <line x1="..."/> elements.
        def first_seam_x(items: list[str]) -> float | None:
            for s in items:
                if '<line' in s and f'stroke="{BRICK_SEAM}"' in s:
                    import re
                    m = re.search(r'x1="([0-9.]+)"', s)
                    if m:
                        return float(m.group(1))
            return None

        firsts = [first_seam_x(strip) for strip in strips]
        # At least two distinct values across the three strips.
        distinct = {f for f in firsts if f is not None}
        assert len(distinct) >= 2, (
            f"expected staggered seams, got first-seam x-values "
            f"{firsts}"
        )


class TestBrickWallConstantsAreSane:
    def test_strip_count_is_three(self):
        assert BRICK_STRIP_COUNT == 3

    def test_wall_thickness_positive(self):
        assert BRICK_WALL_THICKNESS > 0


def _count_matches(items: list[str], pattern: str) -> int:
    return sum(1 for s in items if pattern in s)


class TestStoneWallRunSignature:
    def test_returns_list_of_strings(self):
        out = render_stone_wall_run(0, 50, 200, 50)
        assert isinstance(out, list)
        assert all(isinstance(s, str) for s in out)

    def test_zero_length_returns_empty(self):
        assert render_stone_wall_run(50, 50, 50, 50) == []

    def test_diagonal_run_rejected(self):
        with pytest.raises(ValueError):
            render_stone_wall_run(0, 0, 20, 10)


class TestStoneWallRunRendering:
    def test_emits_stone_fill_rects(self):
        out = render_stone_wall_run(0, 50, 200, 50, seed=1)
        # Each stone is its own rect; a wall that wide yields many.
        stones = _count_matches(out, f'fill="{STONE_FILL}"')
        assert stones > 10

    def test_each_stone_has_rounded_corners(self):
        out = render_stone_wall_run(0, 50, 200, 50, seed=1)
        stones = [s for s in out if f'fill="{STONE_FILL}"' in s]
        for s in stones:
            assert f'rx="{STONE_CORNER_RADIUS}"' in s
            assert f'ry="{STONE_CORNER_RADIUS}"' in s

    def test_stones_stroked_with_seam_color(self):
        out = render_stone_wall_run(0, 50, 200, 50, seed=1)
        stones = [s for s in out if f'fill="{STONE_FILL}"' in s]
        assert stones
        for s in stones:
            assert f'stroke="{STONE_SEAM}"' in s

    def test_three_courses_by_y_coord(self):
        """Horizontal run: stones cluster into 3 distinct y-rows."""
        out = render_stone_wall_run(0, 100, 300, 100, seed=2)
        stones = [s for s in out if f'fill="{STONE_FILL}"' in s]
        ys: set[str] = set()
        for s in stones:
            m = re.search(r'y="([0-9.]+)"', s)
            if m:
                ys.add(m.group(1))
        assert len(ys) == BRICK_STRIP_COUNT


class TestStoneWallDeterminism:
    def test_same_seed_produces_same_output(self):
        a = render_stone_wall_run(0, 50, 200, 50, seed=42)
        b = render_stone_wall_run(0, 50, 200, 50, seed=42)
        assert a == b

    def test_different_seeds_produce_different_output(self):
        a = render_stone_wall_run(0, 50, 200, 50, seed=1)
        b = render_stone_wall_run(0, 50, 200, 50, seed=2)
        assert a != b


class TestStoneWidthDistribution:
    def test_width_has_wider_range_than_brick(self):
        """Stone widths vary more than brick widths at the same seed."""
        out = render_stone_wall_run(0, 50, 1000, 50, seed=5)
        widths = []
        for s in out:
            if f'fill="{STONE_FILL}"' not in s:
                continue
            m = re.search(r'width="([0-9.]+)"', s)
            if m:
                widths.append(float(m.group(1)))
        assert len(widths) > 20
        spread = max(widths) - min(widths)
        # Stones: 0.7x - 1.6x of ~12px mean => spread ~10px+
        assert spread > 5.0


class TestStoneMissingProbability:
    def test_missing_probability_lower_than_brick(self):
        assert STONE_MISSING_PROBABILITY < 0.05

    def test_long_wall_rarely_misses_stones(self):
        """A reasonably long wall has at most a few missing-stone gaps."""
        out = render_stone_wall_run(0, 50, 600, 50, seed=1)
        # Missing stones are the only rects WITHOUT STONE_FILL and
        # with fill=BG; the brick module's BRICK_MISSING constant is
        # the same BG value.
        missing = _count_matches(out, f'fill="{BRICK_MISSING}"')
        assert 0 <= missing < 15


class TestStoneVsBrickContrast:
    def test_stone_uses_different_palette(self):
        assert STONE_FILL != BRICK_FILL
        assert STONE_SEAM != BRICK_SEAM

    def test_stone_output_differs_from_brick_at_same_seed(self):
        b = render_brick_wall_run(0, 50, 200, 50, seed=11)
        s = render_stone_wall_run(0, 50, 200, 50, seed=11)
        assert b != s
