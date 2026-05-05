"""``DecoratorOp.cart_tracks`` / ``ore_deposit`` → ``V5PathOp``.

v4 packs cart-tracks and ore-deposit as variants on the
``DecoratorOp`` parallel-vectors layout. v5 promotes them to a
dedicated ``V5PathOp`` per network with a stable ``style`` enum.

Cart-tracks already ship the per-tile open-sides bitmask in v4
(``CartTracksVariant.open_sides``) — the v5 painter re-derives
the topology from the unordered tile set, so the open-sides
bitmask is dropped on the v5 side. Ore-deposit ships only tiles.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
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


def translate_path_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Walk every ``DecoratorOp`` and emit one ``V5PathOp`` per
    non-empty cart-tracks / ore-deposit network."""
    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.DecoratorOp:
            continue
        deco = entry.op
        rr = deco.regionRef or ""
        seed = int(getattr(deco, "seed", 0) or 0)

        for variant in deco.cartTracks or []:
            if not variant.tiles:
                continue
            path_op = _make_path_op(
                region_ref=rr,
                tiles=variant.tiles,
                style=V5PathStyle.CartTracks,
                seed=seed,
            )
            result.append(_wrap(path_op))

        for variant in deco.oreDeposit or []:
            if not variant.tiles:
                continue
            path_op = _make_path_op(
                region_ref=rr,
                tiles=variant.tiles,
                style=V5PathStyle.OreVein,
                seed=seed,
            )
            result.append(_wrap(path_op))
    return result
