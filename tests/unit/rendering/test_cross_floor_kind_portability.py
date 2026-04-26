"""Phase 7 backstop: cross-floor-kind portability tests.

After the rendering refactor, the per-tile decorators and the
terrain palette are floor-kind-agnostic. These tests construct
minimal synthetic levels of each floor kind and assert that
matching tiles paint their decorator output regardless of the
surrounding context.

These tests pass *trivially* after the refactor -- they're
documentation of the framework's portability guarantee, not
behavioural gates. Adding a new biome / theme variant should not
break any of them.
"""

from __future__ import annotations

import random

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
)
from nhc.rendering.svg import render_floor_svg


def _floor_grid(w: int, h: int) -> Level:
    """Build a wall-bordered FLOOR grid with one Room covering the
    interior. Sufficient for ``render_floor_svg`` to produce a
    dungeon-poly clip."""
    level = Level.create_empty("L", "L", 1, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, w, h))]
    return level


# ── Trees on every floor kind ─────────────────────────────────


class TestTreePortability:
    def test_tree_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].feature = "tree"
        svg = render_floor_svg(level)
        assert 'class="tree-feature"' in svg

    def test_tree_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].feature = "tree"
        svg = render_floor_svg(level)
        assert 'class="tree-feature"' in svg

    def test_tree_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3].feature = "tree"
        svg = render_floor_svg(level)
        assert 'class="tree-feature"' in svg

    def test_tree_paints_on_cave(self) -> None:
        level = _floor_grid(6, 6)
        level.rooms = [Room(
            id="cave1",
            rect=Rect(0, 0, 6, 6),
            shape=CaveShape(tiles={
                (x, y) for y in range(6) for x in range(6)
            }),
        )]
        level.tiles[3][3].feature = "tree"
        svg = render_floor_svg(level, seed=11)
        assert 'class="tree-feature"' in svg


# ── Water on every floor kind ─────────────────────────────────


class TestWaterPortability:
    def test_water_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        svg = render_floor_svg(level)
        assert 'class="terrain-water"' in svg

    def test_water_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        svg = render_floor_svg(level)
        assert 'class="terrain-water"' in svg

    def test_water_paints_on_surface(self) -> None:
        level = _floor_grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3] = Tile(terrain=Terrain.WATER)
        svg = render_floor_svg(level)
        assert 'class="terrain-water"' in svg


# ── Cobblestone on every floor kind ──────────────────────────


class TestCobblestonePortability:
    _COBBLE = '#8A7A6A'  # canonical stroke colour

    def test_street_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level)
        assert self._COBBLE in svg

    def test_paved_paints_on_building_interior(self) -> None:
        level = _floor_grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].surface_type = SurfaceType.PAVED
        svg = render_floor_svg(level)
        assert self._COBBLE in svg

    def test_street_paints_on_cave(self) -> None:
        level = _floor_grid(6, 6)
        level.rooms = [Room(
            id="cave1",
            rect=Rect(0, 0, 6, 6),
            shape=CaveShape(tiles={
                (x, y) for y in range(6) for x in range(6)
            }),
        )]
        level.tiles[3][3].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level, seed=11)
        assert self._COBBLE in svg


# ── Garden hoe rows on every floor kind ──────────────────────


class TestGardenOverlayPortability:
    def test_garden_paints_on_dungeon(self) -> None:
        level = _floor_grid(6, 6)
        level.tiles[3][3] = Tile(
            terrain=Terrain.GRASS, surface_type=SurfaceType.GARDEN,
        )
        # Force the GARDEN_LINE decorator to fire on at least one
        # of 16 deterministic seeds (it's probabilistic per tile).
        for seed in range(16):
            svg = render_floor_svg(level, seed=seed)
            from nhc.rendering._floor_detail import GARDEN_LINE_STROKE
            if GARDEN_LINE_STROKE in svg:
                return
        # If none of the 16 seeds rolled a hoe row the probability
        # constants must have changed -- surface the failure here
        # so the change is reviewed.
        raise AssertionError(
            "GARDEN_LINE never fired across 16 seeds for a single "
            "garden tile -- inspect GARDEN_LINE_PROBABILITY"
        )
