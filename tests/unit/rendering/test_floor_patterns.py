"""Variations of cobblestone: brick, flagstone, herringbone.

Each pattern is its own ``SurfaceType`` + ``TileDecorator`` and
fires on tiles that carry the matching tag, regardless of floor
kind (the same portability guarantee Phase 2's COBBLESTONE
decorator established).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import (
    Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
)
from nhc.rendering._decorators import walk_and_paint
from nhc.rendering._floor_detail import (
    BRICK,
    BRICK_STROKE,
    FLAGSTONE,
    FLAGSTONE_STROKE,
    HERRINGBONE,
    HERRINGBONE_STROKE,
)
from nhc.rendering._render_context import build_render_context
from nhc.rendering.svg import render_floor_svg


def _grid(w: int, h: int) -> Level:
    level = Level.create_empty("L", "L", 0, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, w, h))]
    return level


class TestSurfaceTypeEnumValues:
    def test_brick_value(self) -> None:
        assert SurfaceType("brick") is SurfaceType.BRICK

    def test_flagstone_value(self) -> None:
        assert SurfaceType("flagstone") is SurfaceType.FLAGSTONE

    def test_herringbone_value(self) -> None:
        assert SurfaceType("herringbone") is SurfaceType.HERRINGBONE


class TestBrickDecorator:
    def test_fires_on_brick_tile(self) -> None:
        level = _grid(4, 4)
        level.tiles[1][1].surface_type = SurfaceType.BRICK
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [BRICK])
        assert any(BRICK_STROKE in line for line in out)

    def test_does_not_fire_on_street(self) -> None:
        level = _grid(4, 4)
        level.tiles[1][1].surface_type = SurfaceType.STREET
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [BRICK])
        assert out == []

    def test_does_not_fire_on_plain_floor(self) -> None:
        level = _grid(4, 4)
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [BRICK])
        assert out == []


class TestFlagstoneDecorator:
    def test_fires_on_flagstone_tile(self) -> None:
        level = _grid(4, 4)
        level.tiles[1][1].surface_type = SurfaceType.FLAGSTONE
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [FLAGSTONE])
        assert any(FLAGSTONE_STROKE in line for line in out)

    def test_does_not_fire_on_brick(self) -> None:
        level = _grid(4, 4)
        level.tiles[1][1].surface_type = SurfaceType.BRICK
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [FLAGSTONE])
        assert out == []


class TestHerringboneDecorator:
    def test_fires_on_herringbone_tile(self) -> None:
        level = _grid(4, 4)
        level.tiles[1][1].surface_type = SurfaceType.HERRINGBONE
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [HERRINGBONE])
        assert any(HERRINGBONE_STROKE in line for line in out)

    def test_does_not_fire_on_flagstone(self) -> None:
        level = _grid(4, 4)
        level.tiles[1][1].surface_type = SurfaceType.FLAGSTONE
        ctx = build_render_context(level, seed=0)
        out = walk_and_paint(ctx, [HERRINGBONE])
        assert out == []


class TestEndToEndIntegration:
    """Through ``render_floor_svg``, each pattern's stroke colour
    appears in the final SVG so a future contributor can wire the
    pattern onto a new site by stamping the matching tag."""

    def test_brick_through_render_floor_svg(self) -> None:
        level = _grid(4, 4)
        level.tiles[2][2].surface_type = SurfaceType.BRICK
        svg = render_floor_svg(level, seed=0)
        assert BRICK_STROKE in svg

    def test_flagstone_through_render_floor_svg(self) -> None:
        level = _grid(4, 4)
        level.tiles[2][2].surface_type = SurfaceType.FLAGSTONE
        svg = render_floor_svg(level, seed=0)
        assert FLAGSTONE_STROKE in svg

    def test_herringbone_through_render_floor_svg(self) -> None:
        level = _grid(4, 4)
        level.tiles[2][2].surface_type = SurfaceType.HERRINGBONE
        svg = render_floor_svg(level, seed=0)
        assert HERRINGBONE_STROKE in svg


class TestPortability:
    """Drop one tagged tile into each floor kind; the matching
    pattern paints in every case (mirrors Phase 2's cobblestone
    portability proof)."""

    def test_brick_paints_on_building_interior(self) -> None:
        level = _grid(6, 6)
        level.building_id = "b1"
        level.tiles[3][3].surface_type = SurfaceType.BRICK
        svg = render_floor_svg(level, seed=0)
        assert BRICK_STROKE in svg

    def test_flagstone_paints_on_surface(self) -> None:
        level = _grid(6, 6)
        level.metadata.prerevealed = True
        level.tiles[3][3].surface_type = SurfaceType.FLAGSTONE
        svg = render_floor_svg(level, seed=0)
        assert FLAGSTONE_STROKE in svg

    def test_herringbone_paints_on_dungeon(self) -> None:
        level = _grid(6, 6)
        level.tiles[3][3].surface_type = SurfaceType.HERRINGBONE
        svg = render_floor_svg(level, seed=0)
        assert HERRINGBONE_STROKE in svg


class TestSiteAssemblerHooks:
    """End-to-end check: the three target sites render the
    expected pattern stroke after Phase 2-style assembler
    integration."""

    def test_mansion_ground_floor_uses_brick(self) -> None:
        from nhc.sites.mansion import assemble_mansion
        site = assemble_mansion("m1", random.Random(7))
        ground = site.buildings[0].ground
        # Stone-floored ground floor expected to carry BRICK tag
        # on at least one interior FLOOR tile.
        any_brick = any(
            ground.tiles[y][x].surface_type is SurfaceType.BRICK
            for y in range(ground.height)
            for x in range(ground.width)
            if ground.tiles[y][x].terrain is Terrain.FLOOR
        )
        assert any_brick, "mansion ground floor expected BRICK tag"

    def test_temple_ground_floor_uses_flagstone(self) -> None:
        from nhc.sites.temple import assemble_temple
        site = assemble_temple("t1", random.Random(7))
        ground = site.buildings[0].ground
        any_flag = any(
            ground.tiles[y][x].surface_type is SurfaceType.FLAGSTONE
            for y in range(ground.height)
            for x in range(ground.width)
            if ground.tiles[y][x].terrain is Terrain.FLOOR
        )
        assert any_flag, "temple ground floor expected FLAGSTONE tag"

    def test_town_centerpiece_uses_herringbone(self) -> None:
        from nhc.sites.town import assemble_town
        site = assemble_town("t1", random.Random(7))
        any_herringbone = any(
            site.surface.tiles[y][x].surface_type
            is SurfaceType.HERRINGBONE
            for y in range(site.surface.height)
            for x in range(site.surface.width)
        )
        assert any_herringbone, (
            "town centerpiece expected HERRINGBONE tag"
        )
