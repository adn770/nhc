"""Builder / level walk → ``V5OpEntry(V5PathOp)``.

:func:`emit_paths` walks the level's per-tile classification
(via the same ``_is_track_tile`` / ``_is_ore_tile`` predicates the
v4 emit pipeline uses) to derive cart-tracks and ore-deposit
networks, and ships one ``V5PathOp`` per non-empty network.
Mirrors the source logic of the DecoratorOp emit branch in
:func:`nhc.rendering._floor_layers._emit_floor_detail_ir`.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5PathOp import V5PathOpT
from nhc.rendering.ir._fb.V5PathStyle import V5PathStyle


def _wrap(path_op: V5PathOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5PathOp
    entry.op = path_op
    return entry


def _make_path_op(
    *, region_ref: str, tiles: list[Any], style: int, seed: int
) -> V5PathOpT:
    op = V5PathOpT()
    op.regionRef = region_ref
    op.tiles = list(tiles)
    op.style = style
    op.seed = seed
    return op


def emit_paths(builder: Any) -> list[V5OpEntryT]:
    """Walk the level for cart-tracks / ore-deposit candidate tiles
    and emit one V5PathOp per non-empty network.

    Gated on the same ``interior_finish == "wood"`` short-circuit
    that v4 emit honours: building floors with wood interior finish
    skip the decorator pass entirely.
    """
    from nhc.rendering._floor_detail import _is_ore_tile, _is_track_tile
    from nhc.rendering.ir._fb.TileCoord import TileCoordT

    ctx = builder.ctx
    if getattr(ctx, "interior_finish", "") == "wood":
        return []

    level = ctx.level
    tiles_grid = getattr(level, "tiles", None)
    if tiles_grid is None:
        return []

    track_coords: list[tuple[int, int]] = []
    ore_coords: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            if _is_track_tile(level, x, y):
                track_coords.append((x, y))
            if _is_ore_tile(level, x, y):
                ore_coords.append((x, y))

    if not (track_coords or ore_coords):
        return []

    seed = ctx.seed + 333
    result: list[V5OpEntryT] = []
    if track_coords:
        result.append(_wrap(_make_path_op(
            region_ref="",
            tiles=[TileCoordT(x=x, y=y) for x, y in track_coords],
            style=V5PathStyle.CartTracks,
            seed=seed,
        )))
    if ore_coords:
        result.append(_wrap(_make_path_op(
            region_ref="",
            tiles=[TileCoordT(x=x, y=y) for x, y in ore_coords],
            style=V5PathStyle.OreVein,
            seed=seed,
        )))
    return result
