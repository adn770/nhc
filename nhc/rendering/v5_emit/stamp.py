"""Texture-overlay v4 ops → ``V5StampOp``.

The v4 emitter splits texture overlays across multiple op types:

- ``FloorGridOp``       — wobbly Perlin grid
- ``FloorDetailOp``     — cracks, scratches, loose stones
- ``ThematicDetailOp``  — webs, bones, skulls (scatter)
- ``DecoratorOp``       — multiple stone-pattern variants (handled
                          in :mod:`paint`) PLUS cart_tracks /
                          ore_deposit (handled in :mod:`path`)
- ``TerrainDetailOp``   — water ripples, lava cracks, chasm

v5 collapses the texture-overlay parts into ``V5StampOp`` with a
``decorator_mask`` bitfield. The thematic-detail object scatter
parts (webs / bones / skulls) ride through :mod:`fixture`
instead.

The translator emits one ``V5StampOp`` per source op, mapping the
op kind to the corresponding bit. For Phase 1.4, the per-tile
densities and seed values aren't replayed — the v5 painter
re-derives placement from the op's seed at consume time. Phase 1.5
validates the visual result.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5StampOp import V5StampOpT


# Decorator-bit registry — mirrors design/map_ir_v5.md §5 and
# the ``bit::`` constants on the Rust handler at
# ``transform/png/v5/stamp_op.rs``.
BIT_GRID_LINES = 1 << 0
BIT_CRACKS = 1 << 1
BIT_SCRATCHES = 1 << 2
BIT_RIPPLES = 1 << 3
BIT_LAVA_CRACKS = 1 << 4
BIT_MOSS = 1 << 5
BIT_BLOOD = 1 << 6
BIT_ASH = 1 << 7
BIT_PUDDLES = 1 << 8


def _wrap(stamp_op: V5StampOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5StampOp
    entry.op = stamp_op
    return entry


def _make_stamp_op(*, region_ref: str, mask: int, seed: int) -> V5StampOpT:
    op = V5StampOpT()
    op.regionRef = region_ref
    op.subtractRegionRefs = []
    op.decoratorMask = mask
    op.density = 128  # baseline
    op.seed = seed
    return op


def translate_stamp_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate texture-overlay v4 ops into ``V5StampOp`` entries."""
    result: list[V5OpEntryT] = []
    for entry in ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.FloorGridOp:
            grid = entry.op
            stamp = _make_stamp_op(
                region_ref=grid.regionRef or "",
                mask=BIT_GRID_LINES,
                seed=int(getattr(grid, "seed", 0) or 0),
            )
            result.append(_wrap(stamp))
        elif op_type == Op.FloorDetailOp:
            detail = entry.op
            stamp = _make_stamp_op(
                region_ref=detail.regionRef or "",
                mask=BIT_CRACKS | BIT_SCRATCHES,
                seed=int(getattr(detail, "seed", 0) or 0),
            )
            result.append(_wrap(stamp))
        elif op_type == Op.TerrainDetailOp:
            terrain = entry.op
            # The v4 op walks per-tile terrain kinds (water / lava
            # / chasm). The v5 scaffold ships a single op carrying
            # both ripples (water) and lava-cracks (lava); the
            # painter resolves the right bit per tile from the
            # underlying Material at paint time.
            stamp = _make_stamp_op(
                region_ref=terrain.regionRef or "",
                mask=BIT_RIPPLES | BIT_LAVA_CRACKS,
                seed=int(getattr(terrain, "seed", 0) or 0),
            )
            result.append(_wrap(stamp))
    return result
