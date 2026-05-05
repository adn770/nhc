"""Structural-invariants snapshot of a FloorIR FlatBuffer.

The IR-level layer of the cross-rasteriser parity contract per
``design/map_ir.md`` §9.4: a rasteriser-independent dict of op
counts and region counts that catches emit-side regressions
before any rasteriser runs. Pixel-level PSNR
(``test_ir_png_parity.py``) handles the rasteriser-dependent
half.

Output is a sorted, JSON-serialisable dict — designed for
byte-equal comparison against a committed snapshot at
``tests/fixtures/floor_ir/<descriptor>/structural.json``.

Phase 2.19 retired the ``layer_element_counts`` field along
with the Python ``ir_to_svg.py`` emitter that produced the
``<!-- layer.X: N elements -->`` comments the field parsed out
of. Per-layer geometry is now covered by the cross-rasteriser
PSNR gates and the ``op_counts`` dict; layer-element drift was
always indirect (an SVG-element count, not a structural fact).
"""

from __future__ import annotations

import json
from typing import Any

from nhc.rendering.ir._fb import V5Op
from nhc.rendering.ir._fb.FloorIR import FloorIR


_V5_OP_TYPE_TO_NAME: dict[int, str] = {
    v: k for k, v in vars(V5Op.V5Op).items()
    if not k.startswith("_") and isinstance(v, int)
}


def compute_structural(buf: bytes) -> dict[str, Any]:
    """Compute the structural-invariants snapshot for an IR buffer.

    Returns a dict with stable keys:

    - ``op_counts``: ``{v5_op_type_name: count}``, sorted by name.
      Reads the canonical v5 op stream (``v5_ops[]``) per Phase 4.1
      of plans/nhc_pure_ir_v5_migration_plan.md. The v4 ``ops[]``
      array still rides alongside until the atomic cut at 4.3, but
      Phase 4.1 retires v4-side reading from every Python consumer
      so the cut is mechanical.
    - ``region_count``: total count of ``v5_regions[]`` entries.
    - ``region_polygon_rings`` / ``region_polygon_vertices``:
      total ring + vertex counts across all regions (coarse but
      cheap proxies for region geometry drift).

    Cheap: a single FlatBuffer parse — no SVG round-trip.
    """
    fir = FloorIR.GetRootAs(buf, 0)
    op_counts: dict[str, int] = {}
    for i in range(fir.V5OpsLength()):
        t = fir.V5Ops(i).OpType()
        name = _V5_OP_TYPE_TO_NAME.get(t, f"V5OpType_{t}")
        op_counts[name] = op_counts.get(name, 0) + 1

    region_count = fir.V5RegionsLength()
    polygon_vertices = 0
    polygon_rings = 0
    for i in range(region_count):
        region = fir.V5Regions(i)
        outline = region.Outline()
        if outline is None:
            continue
        polygon_vertices += outline.VerticesLength()
        polygon_rings += outline.RingsLength()

    return {
        "op_counts": dict(sorted(op_counts.items())),
        "region_count": region_count,
        "region_polygon_rings": polygon_rings,
        "region_polygon_vertices": polygon_vertices,
    }


def dump_structural(buf: bytes) -> str:
    """Canonical JSON text for the structural snapshot.

    Two-space indent + sorted keys at every level so a structural
    drift produces a clean, line-oriented diff in PRs.
    """
    return json.dumps(
        compute_structural(buf), indent=2, sort_keys=True
    ) + "\n"
