"""Wall ops → ``V5StrokeOp``.

Translates the v4 wall-op trio (``ExteriorWallOp``,
``InteriorWallOp``, ``CorridorWallOp``) into one ``V5StrokeOp``
each. Geometry resolution mirrors v4:
- ``ExteriorWallOp`` references geometry through ``region_ref``
  → ``Region.outline``; in v5 this becomes
  ``V5StrokeOp.region_ref``.
- ``InteriorWallOp`` carries its own ``op.outline`` (interior
  partition); in v5 it lands on ``V5StrokeOp.outline``.
- ``CorridorWallOp`` carries a tile list; v5 leaves the geometry
  derivation implicit and ships an empty stroke for the
  scaffold (a future emit pass widens this when corridor wall
  edges are pre-resolved server-side).

Cuts (door / gate openings) ride through to the v5 op:
- For ``ExteriorWallOp`` they end up on ``V5StrokeOp.cuts`` (a
  loose interpretation of design §2.6 — the canonical path is
  to push them onto the Region's cuts list, which Phase 1.6
  will do; the scaffold parks them on the op so Phase 1.5's
  parity gate can validate them).
- For ``InteriorWallOp`` they ride on the op alongside its
  outline.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5StrokeOp import V5StrokeOpT
from nhc.rendering.v5_emit.materials import wall_material_from_wall_style


def _wrap(stroke_op: V5StrokeOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5StrokeOp
    entry.op = stroke_op
    return entry


def translate_stroke_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Translate v4 wall ops into ``V5StrokeOp`` entries."""
    result: list[V5OpEntryT] = []
    for entry in ops:
        op_type = getattr(entry, "opType", None)
        if op_type == Op.ExteriorWallOp:
            ext = entry.op
            wm = wall_material_from_wall_style(
                ext.style,
                corner_style=ext.cornerStyle,
                seed=int(getattr(ext, "rngSeed", 0) or 0),
            )
            stroke = V5StrokeOpT()
            stroke.regionRef = ext.regionRef or ""
            stroke.outline = None
            stroke.wallMaterial = wm
            stroke.cuts = list(ext.cuts or [])
            result.append(_wrap(stroke))
        elif op_type == Op.InteriorWallOp:
            interior = entry.op
            wm = wall_material_from_wall_style(interior.style)
            stroke = V5StrokeOpT()
            stroke.regionRef = ""
            stroke.outline = interior.outline
            stroke.wallMaterial = wm
            stroke.cuts = list(interior.cuts or [])
            result.append(_wrap(stroke))
        elif op_type == Op.CorridorWallOp:
            corridor = entry.op
            wm = wall_material_from_wall_style(corridor.style)
            stroke = V5StrokeOpT()
            # Corridor walls are derived from tile coverage — the v5
            # scaffold ships an empty geometry; consumers handle
            # corridor-derivation separately via the corridor region.
            stroke.regionRef = "corridor"
            stroke.outline = None
            stroke.wallMaterial = wm
            stroke.cuts = []
            result.append(_wrap(stroke))
    return result
