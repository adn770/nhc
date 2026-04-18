"""Tests for SVG rendering of Building exterior walls (M4+).

See design/building_generator.md section 7 (Rendering) for the
full specification. M4 covers the brick-wall 3-strip renderer.
"""

import pytest

from nhc.rendering._building_walls import (
    BRICK_FILL,
    BRICK_MISSING,
    BRICK_SEAM,
    BRICK_STRIP_COUNT,
    BRICK_WALL_THICKNESS,
    render_brick_wall_run,
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
