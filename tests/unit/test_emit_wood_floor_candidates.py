"""Phase 9.2a — emitter shape gate for the wood-floor structured fields.

Per plan §9.2, ``FloorDetailOp`` grows three structured fields the
upcoming wood-floor Rust port (Phase 9.2c) consumes:

* ``wood_tiles[]`` — every FLOOR tile in row-major order. Drives
  the per-tile rect fill the rect-shape building floor relies on
  (octagon / circle floors instead use the building polygon and
  leave this field unread).
* ``wood_building_polygon[]`` — the chamfer / curved-wall outer
  outline for octagon / circle floors. Empty for rect floors.
* ``wood_rooms[]`` — per-room rects that drive the parquet plank +
  grain generators.

The contract is enforced against an independent re-derivation: a
small synthetic building level with a wood interior. The legacy
``wood_floor_groups`` passthrough stays populated through the 9.2a
cycle (9.2b retires it) so the existing PSNR + structural gates on
the building fixture stay green.
"""
from __future__ import annotations

from nhc.dungeon.model import (
    Level, Rect, Room, RectShape, Terrain, Tile,
)
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorDetailOp import (
    FloorDetailOp as FloorDetailOpReader,
)
from nhc.rendering.ir._fb.FloorIR import FloorIR
from nhc.rendering.ir_emitter import build_floor_ir


def _wood_level(width: int = 6, height: int = 5) -> Level:
    """Synthetic wood-floor level: one rect room of ``FLOOR``
    tiles, every tile included so the row-major walk covers the
    full canvas. ``interior_floor`` flips the wood-floor short-
    circuit on at the IR emit layer."""
    level = Level.create_empty("L", "L", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [
        Room(id="r1", rect=Rect(0, 0, width, height), shape=RectShape()),
    ]
    level.interior_floor = "wood"
    return level


def _build_buf(level: Level) -> bytes:
    return build_floor_ir(level, seed=42)


def _floor_detail_op(buf: bytes):
    fir = FloorIR.GetRootAs(buf, 0)
    for i in range(fir.OpsLength()):
        entry = fir.Ops(i)
        if entry.OpType() != Op.Op.FloorDetailOp:
            continue
        op = FloorDetailOpReader()
        op.Init(entry.Op().Bytes, entry.Op().Pos)
        return op
    return None


def test_wood_tiles_match_floor_walk() -> None:
    level = _wood_level()
    op = _floor_detail_op(_build_buf(level))
    assert op is not None, "emitter produced no FloorDetailOp"
    actual = [
        (op.WoodTiles(i).X(), op.WoodTiles(i).Y())
        for i in range(op.WoodTilesLength())
    ]
    expected = [
        (x, y)
        for y in range(level.height)
        for x in range(level.width)
        if level.tiles[y][x].terrain is Terrain.FLOOR
    ]
    assert actual == expected, (
        f"wood_tiles[] {actual!r} does not match the row-major "
        f"FLOOR walk {expected!r}"
    )


def test_wood_rooms_carry_room_rects() -> None:
    level = _wood_level()
    op = _floor_detail_op(_build_buf(level))
    assert op is not None
    rooms = [
        (
            op.WoodRooms(i).X(),
            op.WoodRooms(i).Y(),
            op.WoodRooms(i).W(),
            op.WoodRooms(i).H(),
        )
        for i in range(op.WoodRoomsLength())
    ]
    assert rooms == [(0, 0, level.width, level.height)], (
        f"wood_rooms[] does not match the level's rooms: {rooms!r}"
    )


def test_wood_building_polygon_empty_for_rect_floor() -> None:
    """Rect-shape buildings leave the polygon field unset; the
    per-tile fill from ``wood_tiles`` covers the whole footprint."""
    level = _wood_level()
    op = _floor_detail_op(_build_buf(level))
    assert op is not None
    assert op.WoodBuildingPolygonLength() == 0, (
        "wood_building_polygon[] should be empty when no "
        "ctx.building_polygon is set"
    )
