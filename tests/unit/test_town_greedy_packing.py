"""Greedy row-packing for town building placement (C2).

Replaces the per-row fixed-width draw with a greedy placer that
takes a per-building ``(w, h)`` pair and wraps to the next row when
the cursor would exceed the surface width. Row heights grow
dynamically from the tallest building in each row, so variable
per-role building sizes (landing in C3) don't overflow.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites.town import _SIZE_CLASSES, assemble_town


def _rects_overlap(a, b) -> bool:
    return (
        a.x < b.x2 and b.x < a.x2
        and a.y < b.y2 and b.y < a.y2
    )


class TestGreedyPackingFitsSurface:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_every_building_fits_surface_bounds(self, size_class):
        config = _SIZE_CLASSES[size_class]
        # 200 seeds surfaces edge cases in large size classes; the
        # previous per-row fixed draw overflowed "city" at seed 93+.
        for seed in range(200):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            for b in site.buildings:
                r = b.base_rect
                assert 0 <= r.x and r.x2 <= config.surface_width, (
                    f"seed={seed} {size_class}: building {b.id} "
                    f"x-range [{r.x}, {r.x2}) exceeds "
                    f"surface_width={config.surface_width}"
                )
                assert 0 <= r.y and r.y2 <= config.surface_height, (
                    f"seed={seed} {size_class}: building {b.id} "
                    f"y-range [{r.y}, {r.y2}) exceeds "
                    f"surface_height={config.surface_height}"
                )


class TestNoBuildingOverlap:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_no_pair_overlaps(self, size_class):
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            rects = [b.base_rect for b in site.buildings]
            for i, a in enumerate(rects):
                for b in rects[i + 1:]:
                    assert not _rects_overlap(a, b), (
                        f"seed={seed} {size_class}: overlapping "
                        f"buildings {a} and {b}"
                    )


class TestPalisadeGateInRowGap:
    """``gate_y`` (main-street y) should land in a vertical strip
    that isn't occupied by any building footprint. That's the
    "main street" — buildings must not block it."""

    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_gate_y_has_no_building_in_row(self, size_class):
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            gate_ys = {gy for (_, gy, _) in site.enclosure.gates}
            assert len(gate_ys) == 1, (
                f"seed={seed} {size_class}: gates should share a y"
            )
            gate_y = next(iter(gate_ys))
            for b in site.buildings:
                r = b.base_rect
                assert not (r.y <= gate_y < r.y2), (
                    f"seed={seed} {size_class}: building {b.id} "
                    f"spans gate_y={gate_y}"
                )
