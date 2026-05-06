"""Builder / ctx walk → ``V5OpEntry(ShadowOp)``.

:func:`emit_shadows` walks the :class:`FloorIRBuilder`'s ``ctx``
and ``level`` directly to produce the v5 shadow op stream — no
v4-op input. Mirrors the source logic of
:func:`nhc.rendering._floor_layers._emit_shadows_ir`. ShadowOp's
payload shape is identical between v4 and v5 per
``design/map_ir_v5.md`` §3.5; only the union tag flips on the
wrapping ``V5OpEntry``.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb import ShadowKind
from nhc.rendering.ir._fb.ShadowOp import ShadowOpT
from nhc.rendering.ir._fb.TileCoord import TileCoordT
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT


def _wrap(shadow_op: ShadowOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.ShadowOp
    entry.op = shadow_op
    return entry


def emit_shadows(builder: Any) -> list[V5OpEntryT]:
    """Walk builder.ctx + level to produce V5 ShadowOp entries.

    Honours ``ctx.shadows_enabled`` (building floors disable shadows
    and skip entirely). Order matches
    :func:`_floor_layers._emit_shadows_ir`: room shadows in
    ``level.rooms`` order (gated on ``_room_region_data is not None``),
    then a single aggregated corridor shadow over corridor + door
    tiles in row-major traversal.
    """
    from nhc.dungeon.model import SurfaceType
    from nhc.rendering._svg_helpers import _is_door
    from nhc.rendering.ir_emitter import _room_region_data

    ctx = builder.ctx
    if not ctx.shadows_enabled:
        return []

    level = ctx.level
    # Synthetic fixture builders ship a stub level with only width /
    # height; gate on the canonical room / tile accessors to keep
    # those builders working until they migrate to a real level.
    rooms = getattr(level, "rooms", None)
    tiles_grid = getattr(level, "tiles", None)
    if rooms is None and tiles_grid is None:
        return []

    result: list[V5OpEntryT] = []

    for room in rooms or []:
        if _room_region_data(room) is None:
            continue
        op = ShadowOpT()
        op.kind = ShadowKind.ShadowKind.Room
        op.regionRef = room.id
        result.append(_wrap(op))

    tiles: list[TileCoordT] = []
    if tiles_grid is not None:
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if not (
                    tile.surface_type == SurfaceType.CORRIDOR
                    or _is_door(level, x, y)
                ):
                    continue
                t = TileCoordT()
                t.x = x
                t.y = y
                tiles.append(t)
    if tiles:
        op = ShadowOpT()
        op.kind = ShadowKind.ShadowKind.Corridor
        op.tiles = tiles
        result.append(_wrap(op))

    return result
