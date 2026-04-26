"""Farm vegetation pass.

Mirrors the town / cottage vegetation pattern at lower density
-- most farmland is hoed rows so trees and bushes fringe the
periphery sparsely.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites._types import SiteTier
from nhc.sites.farm import (
    FARM_BUSH_DENSITY,
    FARM_TREE_DENSITY,
    assemble_farm,
)


def _tree_positions(site) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, tile in enumerate(row)
        if tile.feature == "tree"
    }


def _bush_positions(site) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, tile in enumerate(row)
        if tile.feature == "bush"
    }


def _building_footprints(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for b in site.buildings:
        out |= b.base_shape.floor_tiles(b.base_rect)
    return out


def _garden_tiles(site) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, tile in enumerate(row)
        if tile.surface_type == SurfaceType.GARDEN
    }


# ── Trees ────────────────────────────────────────────────────


class TestFarmTrees:
    def test_trees_only_on_field(self) -> None:
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            for x, y in _tree_positions(site):
                tile = site.surface.tiles[y][x]
                assert tile.surface_type == SurfaceType.FIELD, (
                    f"seed={seed}: tree at ({x},{y}) on "
                    f"{tile.surface_type!r}, expected FIELD"
                )

    def test_trees_not_4adjacent_to_footprint(self) -> None:
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            footprints = _building_footprints(site)
            for x, y in _tree_positions(site):
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (x + dx, y + dy)
                    assert nb not in footprints, (
                        f"seed={seed}: tree at ({x},{y}) is "
                        f"4-adjacent to building footprint {nb}"
                    )

    def test_trees_not_on_garden_ring(self) -> None:
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert not (_garden_tiles(site) & _tree_positions(site))

    def test_tree_count_in_density_band(self) -> None:
        density = FARM_TREE_DENSITY
        total_field = 0
        total_trees = 0
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            footprints = _building_footprints(site)
            for y, row in enumerate(site.surface.tiles):
                for x, tile in enumerate(row):
                    if tile.surface_type != SurfaceType.FIELD:
                        continue
                    blocked = False
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        if (x + dx, y + dy) in footprints:
                            blocked = True
                            break
                    if blocked:
                        continue
                    if tile.feature is not None and tile.feature != "tree":
                        continue
                    total_field += 1
                    if tile.feature == "tree":
                        total_trees += 1
        if total_field == 0:
            pytest.skip("no eligible FIELD tiles in 40 seeds")
        rate = total_trees / total_field
        lo = density * 0.5
        hi = density * 1.7
        assert lo <= rate <= hi, (
            f"farm tree rate {rate:.3f} outside "
            f"[{lo:.3f}, {hi:.3f}] for density={density}"
        )

    def test_deterministic_per_seed(self) -> None:
        for seed in (1, 7, 42):
            a = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            b = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert _tree_positions(a) == _tree_positions(b)


# ── Bushes ───────────────────────────────────────────────────


class TestFarmBushes:
    def test_bushes_only_on_field(self) -> None:
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            for x, y in _bush_positions(site):
                tile = site.surface.tiles[y][x]
                assert tile.surface_type == SurfaceType.FIELD, (
                    f"seed={seed}: bush at ({x},{y}) on "
                    f"{tile.surface_type!r}, expected FIELD"
                )

    def test_bushes_not_on_garden_ring(self) -> None:
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert not (_garden_tiles(site) & _bush_positions(site))

    def test_bush_count_in_density_band(self) -> None:
        density = FARM_BUSH_DENSITY
        total_field = 0
        total_bushes = 0
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            for y, row in enumerate(site.surface.tiles):
                for x, tile in enumerate(row):
                    if tile.surface_type != SurfaceType.FIELD:
                        continue
                    if tile.feature is not None and tile.feature != "bush":
                        continue
                    total_field += 1
                    if tile.feature == "bush":
                        total_bushes += 1
        if total_field == 0:
            pytest.skip("no eligible FIELD tiles in 40 seeds")
        rate = total_bushes / total_field
        lo = density * 0.5
        hi = density * 2.5
        assert lo <= rate <= hi, (
            f"farm bush rate {rate:.3f} outside "
            f"[{lo:.3f}, {hi:.3f}] for density={density}"
        )

    def test_no_feature_collisions_with_trees(self) -> None:
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert not (
                _tree_positions(site) & _bush_positions(site)
            )

    def test_deterministic_per_seed(self) -> None:
        for seed in (1, 7, 42):
            a = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            b = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert _bush_positions(a) == _bush_positions(b)
