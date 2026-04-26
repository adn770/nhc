"""Cottage vegetation pass (M5).

Mirrors the town vegetation pattern at lower density: trees on
the FIELD ring (excluding tiles 4-adjacent to the footprint so
canopies don't bleed onto the cottage roof), bushes on FIELD
only (never on the GARDEN ring -- curated planting per the
cottage design).
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites.cottage import (
    COTTAGE_BUSH_DENSITY,
    COTTAGE_TREE_DENSITY,
    assemble_cottage,
)


def _tree_positions(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for y, row in enumerate(site.surface.tiles):
        for x, tile in enumerate(row):
            if tile.feature == "tree":
                out.add((x, y))
    return out


def _bush_positions(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for y, row in enumerate(site.surface.tiles):
        for x, tile in enumerate(row):
            if tile.feature == "bush":
                out.add((x, y))
    return out


def _building_footprints(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for b in site.buildings:
        out |= b.base_shape.floor_tiles(b.base_rect)
    return out


def _garden_tiles(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for y, row in enumerate(site.surface.tiles):
        for x, tile in enumerate(row):
            if tile.surface_type == SurfaceType.GARDEN:
                out.add((x, y))
    return out


# ── Trees ────────────────────────────────────────────────────


class TestCottageTrees:
    def test_trees_only_on_field(self) -> None:
        for seed in range(40):
            site = assemble_cottage(
                "c1", random.Random(seed),
            )
            for x, y in _tree_positions(site):
                tile = site.surface.tiles[y][x]
                assert tile.surface_type == SurfaceType.FIELD, (
                    f"seed={seed}: tree at ({x},{y}) on "
                    f"{tile.surface_type!r}, expected FIELD"
                )

    def test_trees_not_4adjacent_to_footprint(self) -> None:
        for seed in range(40):
            site = assemble_cottage(
                "c1", random.Random(seed),
            )
            footprints = _building_footprints(site)
            for x, y in _tree_positions(site):
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (x + dx, y + dy)
                    assert nb not in footprints, (
                        f"seed={seed}: tree at ({x},{y}) is "
                        f"4-adjacent to cottage footprint {nb}"
                    )

    def test_trees_not_on_garden_ring(self) -> None:
        for seed in range(40):
            site = assemble_cottage(
                "c1", random.Random(seed),
            )
            gardens = _garden_tiles(site)
            trees = _tree_positions(site)
            assert not (gardens & trees), (
                f"seed={seed}: trees on GARDEN ring: "
                f"{gardens & trees}"
            )

    def test_tree_count_in_density_band(self) -> None:
        density = COTTAGE_TREE_DENSITY
        total_field = 0
        total_trees = 0
        for seed in range(60):
            site = assemble_cottage(
                "c1", random.Random(seed),
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
            pytest.skip("no eligible FIELD tiles in 60 seeds")
        rate = total_trees / total_field
        lo = density * 0.5
        hi = density * 1.5
        assert lo <= rate <= hi, (
            f"cottage tree rate {rate:.3f} outside "
            f"[{lo:.3f}, {hi:.3f}] for density={density}"
        )

    def test_deterministic_per_seed(self) -> None:
        for seed in (1, 7, 42):
            a = assemble_cottage("c1", random.Random(seed))
            b = assemble_cottage("c1", random.Random(seed))
            assert _tree_positions(a) == _tree_positions(b), (
                f"seed={seed}: tree positions diverged"
            )


# ── Bushes ───────────────────────────────────────────────────


class TestCottageBushes:
    def test_bushes_only_on_field(self) -> None:
        for seed in range(40):
            site = assemble_cottage(
                "c1", random.Random(seed),
            )
            for x, y in _bush_positions(site):
                tile = site.surface.tiles[y][x]
                assert tile.surface_type == SurfaceType.FIELD, (
                    f"seed={seed}: bush at ({x},{y}) on "
                    f"{tile.surface_type!r}, expected FIELD"
                )

    def test_bushes_not_on_garden_ring(self) -> None:
        for seed in range(40):
            site = assemble_cottage(
                "c1", random.Random(seed),
            )
            gardens = _garden_tiles(site)
            bushes = _bush_positions(site)
            assert not (gardens & bushes), (
                f"seed={seed}: bushes on GARDEN ring: "
                f"{gardens & bushes}"
            )

    def test_bush_count_in_density_band(self) -> None:
        density = COTTAGE_BUSH_DENSITY
        total_field = 0
        total_bushes = 0
        for seed in range(60):
            site = assemble_cottage(
                "c1", random.Random(seed),
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
            pytest.skip("no eligible FIELD tiles in 60 seeds")
        rate = total_bushes / total_field
        lo = density * 0.5
        hi = density * 2.0
        assert lo <= rate <= hi, (
            f"cottage bush rate {rate:.3f} outside "
            f"[{lo:.3f}, {hi:.3f}] for density={density}"
        )

    def test_no_feature_collisions_with_trees(self) -> None:
        for seed in range(60):
            site = assemble_cottage(
                "c1", random.Random(seed),
            )
            shared = _tree_positions(site) & _bush_positions(site)
            assert not shared, (
                f"seed={seed}: trees and bushes share tiles "
                f"{shared}"
            )

    def test_deterministic_per_seed(self) -> None:
        for seed in (1, 7, 42):
            a = assemble_cottage("c1", random.Random(seed))
            b = assemble_cottage("c1", random.Random(seed))
            assert _bush_positions(a) == _bush_positions(b), (
                f"seed={seed}: bush positions diverged"
            )
