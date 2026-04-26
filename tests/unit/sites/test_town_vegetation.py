"""Town vegetation pass (Phase 4a).

Scatter ``tree`` tiles across FIELD periphery via per-size
density. Skips tiles 4-adjacent to building footprints (Q16 --
prevents the medium canopy from visually bleeding onto roofs),
tiles adjacent to building entry doors, street tiles and tiles
that already carry a feature. Courtyard GARDEN patches stay
shrub-free (Q7) so they read as paved working yards and remain
free for door candidates.

See ``town_redesign_plan.md`` Phase 4a for the design.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites.town import (
    TOWN_TREE_DENSITY, _SIZE_CLASSES, assemble_town,
)


def _tree_positions(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for y, row in enumerate(site.surface.tiles):
        for x, tile in enumerate(row):
            if tile.feature == "tree":
                out.add((x, y))
    return out


def _building_footprints(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for b in site.buildings:
        out |= b.base_shape.floor_tiles(b.base_rect)
    return out


# ── 1. Trees only land on FIELD tiles ─────────────────────────


class TestTreeSurface:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_every_tree_on_field_tile(self, size_class):
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            for x, y in _tree_positions(site):
                tile = site.surface.tiles[y][x]
                assert tile.surface_type == SurfaceType.FIELD, (
                    f"seed={seed} {size_class}: tree at ({x},{y}) "
                    f"on {tile.surface_type!r}, expected FIELD"
                )


# ── 2. Trees never abut buildings (Q16) ───────────────────────


class TestTreeBuildingClearance:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_no_tree_4adjacent_to_building_footprint(
        self, size_class,
    ):
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            footprints = _building_footprints(site)
            for x, y in _tree_positions(site):
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (x + dx, y + dy)
                    assert nb not in footprints, (
                        f"seed={seed} {size_class}: tree at "
                        f"({x},{y}) is 4-adjacent to building "
                        f"footprint {nb}"
                    )


# ── 3. Doors stay clear of trees ──────────────────────────────


class TestDoorClearance:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_door_4ring_is_tree_free(self, size_class):
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            trees = _tree_positions(site)
            for sxy in site.building_doors:
                sx, sy = sxy
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (sx + dx, sy + dy)
                    assert nb not in trees, (
                        f"seed={seed} {size_class}: tree at {nb} "
                        f"is 4-adjacent to door at {sxy}"
                    )


# ── 4. Density falls in expected band per size class ──────────


class TestTreeDensity:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_tree_count_in_density_band(self, size_class):
        """Aggregate tree count across many seeds matches the
        configured density × FIELD-tile area, within a wide band.
        We collect FIELD tiles + tree tiles across every seed and
        check that the empirical hit-rate sits roughly within
        [0.5x, 1.5x] of the configured density."""
        density = TOWN_TREE_DENSITY[size_class]
        total_field = 0
        total_trees = 0
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            footprints = _building_footprints(site)
            door_ring: set[tuple[int, int]] = set()
            for sx, sy in site.building_doors:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    door_ring.add((sx + dx, sy + dy))
            for y, row in enumerate(site.surface.tiles):
                for x, tile in enumerate(row):
                    if tile.surface_type != SurfaceType.FIELD:
                        continue
                    # Count only tiles that are eligible scatter
                    # candidates (so the density check matches the
                    # actual scatter pool).
                    blocked_neighbour = False
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        if (x + dx, y + dy) in footprints:
                            blocked_neighbour = True
                            break
                    if blocked_neighbour:
                        continue
                    if (x, y) in door_ring:
                        continue
                    if tile.feature is not None and tile.feature != "tree":
                        continue
                    total_field += 1
                    if tile.feature == "tree":
                        total_trees += 1
        if total_field == 0:
            pytest.skip(
                f"{size_class}: no eligible FIELD tiles in 20 seeds"
            )
        rate = total_trees / total_field
        lo = density * 0.5
        hi = density * 1.5
        assert lo <= rate <= hi, (
            f"{size_class}: tree rate {rate:.3f} outside "
            f"[{lo:.3f}, {hi:.3f}] for density={density}"
        )


# ── 5. Courtyard GARDEN patches stay shrub-free ───────────────


class TestCourtyardShrubFree:
    def test_no_tree_inside_courtyard_bbox(self):
        """Q7: courtyard cluster GARDEN patches read as paved
        inner yards and stay vegetation-free."""
        for seed in range(40):
            site = assemble_town(
                "t1", random.Random(seed), size_class="city",
            )
            trees = _tree_positions(site)
            for plan in site.cluster_plans:
                if plan.kind != "courtyard":
                    continue
                bbox = plan.bbox
                for x, y in list(trees):
                    if (bbox.x <= x < bbox.x2
                            and bbox.y <= y < bbox.y2):
                        raise AssertionError(
                            f"seed={seed}: tree at ({x},{y}) "
                            f"inside courtyard bbox {bbox}"
                        )


# ── 6. Trees are deterministic per seed ───────────────────────


class TestTreeDeterminism:
    def test_same_seed_same_tree_set(self):
        for seed in (1, 7, 42):
            a = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            b = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            assert _tree_positions(a) == _tree_positions(b), (
                f"seed={seed}: tree positions diverged across "
                "two assembler runs"
            )
