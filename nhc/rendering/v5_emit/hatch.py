"""``HatchOp`` → ``V5HatchOp`` translator.

The v4 ``HatchOp`` carries (kind, region_in, region_out, tiles,
extent_tiles, seed, stride, hatch_underlay_color, is_outer). The
v5 ``V5HatchOp`` adopts the anti-geometry convention from
design/map_ir_v5.md §2.4: the v4 (region_in, region_out) pair
becomes (region_ref, subtract_region_refs[]). Other fields carry
over byte-for-byte; ``stride`` is dropped (the painter derives
stride from extent_tiles).
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5HatchOp import V5HatchOpT
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT


def translate_hatch_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate every v4 ``HatchOp`` into a ``V5HatchOp`` wrapped
    in a ``V5OpEntry``.

    Region anti-geometry: v4 names the hatched-region geometry via
    ``region_in`` (the area to hatch) and ``region_out`` (the
    subtracted area, e.g. the dungeon polygon for HatchKind.Hole).
    v5 collapses this into ``region_ref`` + ``subtract_region_refs``
    (single-entry list) for symmetry with PaintOp / StampOp.
    """
    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.HatchOp:
            continue
        h = entry.op
        v5 = V5HatchOpT()
        v5.kind = h.kind
        v5.regionRef = h.regionIn or ""
        v5.subtractRegionRefs = (
            [h.regionOut] if h.regionOut else []
        )
        v5.tiles = list(h.tiles or [])
        v5.isOuter = list(h.isOuter or [])
        v5.extentTiles = h.extentTiles
        v5.seed = h.seed
        v5.hatchUnderlayColor = h.hatchUnderlayColor or ""

        wrapped = V5OpEntryT()
        wrapped.opType = V5Op.V5HatchOp
        wrapped.op = v5
        result.append(wrapped)
    return result
