"""Phase 9.2b — byte-equal SVG parity gate for the wood-floor short-circuit.

The legacy ``_render_wood_floor`` walk_and_paint pipeline (still
the source of truth for the ``.svg`` endpoint and the legacy
passthrough strings) must produce the same SVG as the new
``_draw_wood_floor_from_ir`` painter that consumes structured
``wood_tiles`` / ``wood_rooms`` / ``wood_building_polygon`` fields.

Covers two fixtures:

* a synthetic rect-room building floor (per-tile rect path).
* a synthetic octagon building floor (building-polygon path).

Both walk through the IR emitter so the structured fields ship and
the new from-IR painter consumes them; the legacy SVG comes from
calling ``_terrain_detail_paint``-style ``_floor_detail_paint`` on
the same render context.
"""
from __future__ import annotations

import random

from nhc.dungeon.model import (
    Level, OctagonShape, Rect, Room, RectShape, Terrain, Tile,
)
from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_detail import _render_wood_floor
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


def _wood_rect_level(width: int = 6, height: int = 5) -> Level:
    level = Level.create_empty("L", "L", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [
        Room(id="r1", rect=Rect(0, 0, width, height), shape=RectShape()),
    ]
    level.interior_floor = "wood"
    return level


def _wood_octagon_level(side: int = 8) -> Level:
    level = Level.create_empty("L", "L", 1, side, side)
    for y in range(side):
        for x in range(side):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [
        Room(id="r1", rect=Rect(0, 0, side, side), shape=OctagonShape()),
    ]
    level.interior_floor = "wood"
    return level


def _legacy_paint(level: Level, seed: int) -> str:
    ctx = build_render_context(
        level, seed=seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
    )
    out: list[str] = []
    building_polygon = (
        list(ctx.building_polygon)
        if ctx.building_polygon is not None
        else None
    )
    _render_wood_floor(
        out, ctx.level, random.Random(seed + 99),
        ctx.dungeon_poly,
        building_polygon=building_polygon,
        ctx=ctx,
    )
    return "\n".join(out)


def _from_ir_paint(level: Level, seed: int) -> str:
    buf = build_floor_ir(level, seed=seed)
    return layer_to_svg(buf, layer="floor_detail")


def test_wood_rect_floor_byte_equal() -> None:
    level = _wood_rect_level()
    legacy = _legacy_paint(level, seed=42)
    actual = _from_ir_paint(level, seed=42)
    assert actual == legacy, (
        "wood-floor (rect) IR fragment diverges from legacy"
    )


def test_wood_octagon_floor_byte_equal() -> None:
    level = _wood_octagon_level()
    legacy = _legacy_paint(level, seed=42)
    actual = _from_ir_paint(level, seed=42)
    assert actual == legacy, (
        "wood-floor (octagon) IR fragment diverges from legacy"
    )
