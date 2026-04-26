"""Cobblestone decorator tests for Phase 2 of the rendering refactor.

Confirms that:
* The renamed cobblestone helpers paint on ``SurfaceType.STREET``
  (preserved town behaviour).
* They also paint on the new ``SurfaceType.PAVED`` (keep interiors).
* The decorator-driven walk works on any floor_kind that contains a
  matching tile (portability proof for future biome variants).
* Real keep buildings stamp interior FLOOR tiles as PAVED so the
  cobble overlay reaches the architecture expected by Phase 2.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import (
    Level, RectShape, Room, Rect, SurfaceType, Terrain, Tile,
)
from nhc.rendering._decorators import walk_and_paint
from nhc.rendering._floor_detail import COBBLESTONE, COBBLE_STONE
from nhc.rendering._render_context import build_render_context
from nhc.rendering.svg import render_floor_svg
from nhc.sites._site import assemble_site


_COBBLE_GROUP_OPEN = (
    '<g opacity="0.35" fill="none" stroke="#8A7A6A" '
    'stroke-width="0.4">'
)


def _stamp(level: Level, x: int, y: int, **kwargs) -> None:
    base = level.tiles[y][x]
    fields = {
        "terrain": base.terrain,
        "surface_type": base.surface_type,
        "feature": base.feature,
    }
    fields.update(kwargs)
    level.tiles[y][x] = Tile(**fields)


def _level_with_one_tile(*, surface_type, terrain=Terrain.FLOOR) -> Level:
    level = Level.create_empty("L", "L", 0, 4, 4)
    _stamp(level, 1, 1, terrain=terrain, surface_type=surface_type)
    return level


class TestCobblestonePredicate:
    def test_fires_on_street_tile(self) -> None:
        level = _level_with_one_tile(surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert any(_COBBLE_GROUP_OPEN in line for line in out)

    def test_fires_on_paved_tile(self) -> None:
        level = _level_with_one_tile(surface_type=SurfaceType.PAVED)
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert any(_COBBLE_GROUP_OPEN in line for line in out)

    def test_skips_field_tile(self) -> None:
        level = _level_with_one_tile(surface_type=SurfaceType.FIELD)
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert out == []

    def test_skips_garden_tile(self) -> None:
        level = _level_with_one_tile(surface_type=SurfaceType.GARDEN)
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert out == []

    def test_skips_plain_floor(self) -> None:
        level = _level_with_one_tile(surface_type=SurfaceType.NONE)
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert out == []


class TestCrossFloorKindPortability:
    """A STREET / PAVED tile dropped into any floor_kind paints
    cobblestone. The decorator is data-driven, not floor-kind-driven."""

    def test_paved_in_synthetic_dungeon(self) -> None:
        # Manufacture a dungeon-shaped level (rooms list non-empty,
        # no building_id, no prerevealed flag) with one PAVED tile.
        level = Level.create_empty("d", "d", 1, 6, 6)
        for y in range(6):
            for x in range(6):
                _stamp(level, x, y, terrain=Terrain.FLOOR)
        level.rooms.append(Room(
            id="r1",
            rect=Rect(0, 0, 6, 6),
            shape=RectShape(),
        ))
        _stamp(level, 3, 3,
               terrain=Terrain.FLOOR,
               surface_type=SurfaceType.PAVED)
        ctx = build_render_context(level, seed=0)
        assert ctx.floor_kind == "dungeon"
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert any(_COBBLE_GROUP_OPEN in line for line in out)

    def test_street_in_synthetic_building(self) -> None:
        level = Level.create_empty("b", "b", 0, 4, 4)
        level.building_id = "b1"
        _stamp(level, 1, 1,
               terrain=Terrain.FLOOR,
               surface_type=SurfaceType.STREET)
        ctx = build_render_context(level, seed=0)
        assert ctx.floor_kind == "building"
        out = walk_and_paint(ctx, [COBBLESTONE])
        assert any(_COBBLE_GROUP_OPEN in line for line in out)


class TestKeepInteriorsCobblestone:
    """End-to-end check: a real keep ground floor renders with the
    cobblestone overlay. Before Phase 2 this output had no
    cobblestone group at all."""

    def test_keep_ground_floor_has_cobblestone(self) -> None:
        site = assemble_site("keep", "kp_cobble", random.Random(7))
        ground = site.buildings[0].ground
        # Sanity: every interior FLOOR tile is now stamped PAVED.
        any_paved = any(
            ground.tiles[y][x].surface_type is SurfaceType.PAVED
            for y in range(ground.height)
            for x in range(ground.width)
            if ground.tiles[y][x].terrain is Terrain.FLOOR
        )
        assert any_paved, "keep floors expected to carry PAVED tag"

        svg = render_floor_svg(ground, seed=7)
        assert _COBBLE_GROUP_OPEN in svg


class TestTownSurfaceUnchanged:
    """Sanity guard: existing town surfaces (STREET tiles) keep
    rendering cobblestone after the rename + broadening."""

    def test_town_surface_has_cobblestone(self) -> None:
        site = assemble_site("town", "tn_cobble", random.Random(3))
        svg = render_floor_svg(site.surface, seed=3)
        assert _COBBLE_GROUP_OPEN in svg
