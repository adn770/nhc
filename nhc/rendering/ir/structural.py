"""Structural-invariants snapshot of a FloorIR FlatBuffer.

The IR-level layer of the cross-rasteriser parity contract per
``design/map_ir.md`` §9.4: a rasteriser-independent dict of op
counts, region counts, and per-layer element counts that catches
emit-side regressions before any rasteriser runs. Pixel-level
PSNR (``test_ir_png_parity.py``) handles the rasteriser-dependent
half.

Output is a sorted, JSON-serialisable dict — designed for
byte-equal comparison against a committed snapshot at
``tests/fixtures/floor_ir/<descriptor>/structural.json``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from nhc.rendering.ir._fb import Op
from nhc.rendering.ir._fb.FloorIR import FloorIR


_OP_TYPE_TO_NAME: dict[int, str] = {
    v: k for k, v in vars(Op.Op).items()
    if not k.startswith("_") and isinstance(v, int)
}


_LAYER_COMMENT_RE = re.compile(r"<!-- layer\.([A-Za-z0-9_]+): (\d+) elements")


def compute_structural(buf: bytes) -> dict[str, Any]:
    """Compute the structural-invariants snapshot for an IR buffer.

    Returns a dict with stable keys:

    - ``op_counts``: ``{op_type_name: count}``, sorted by name.
    - ``region_count``: total count of ``regions[]`` entries.
    - ``region_polygon_counts``: total polygon-vertex count across
      all regions (a coarse but cheap proxy for region geometry
      drift).
    - ``layer_element_counts``: ``{layer_name: int}`` parsed from
      the ``<!-- layer.X: N elements -->`` markers ``ir_to_svg``
      writes per layer.

    Cheap: a single FlatBuffer parse + a regex over the SVG output.
    """
    # Local import — `ir_to_svg` imports `_fb` siblings, so importing
    # at module level would create a cycle on first load.
    from nhc.rendering.ir_to_svg import ir_to_svg

    fir = FloorIR.GetRootAs(buf, 0)
    op_counts: dict[str, int] = {}
    for i in range(fir.OpsLength()):
        t = fir.Ops(i).OpType()
        name = _OP_TYPE_TO_NAME.get(t, f"OpType_{t}")
        op_counts[name] = op_counts.get(name, 0) + 1

    region_count = fir.RegionsLength()
    polygon_vertices = 0
    polygon_rings = 0
    for i in range(region_count):
        region = fir.Regions(i)
        outline = region.Outline()
        if outline is None:
            continue
        polygon_vertices += outline.VerticesLength()
        polygon_rings += outline.RingsLength()

    svg = ir_to_svg(buf)
    layer_counts: dict[str, int] = {}
    for m in _LAYER_COMMENT_RE.finditer(svg):
        layer_counts[m.group(1)] = int(m.group(2))

    return {
        "op_counts": dict(sorted(op_counts.items())),
        "region_count": region_count,
        "region_polygon_rings": polygon_rings,
        "region_polygon_vertices": polygon_vertices,
        "layer_element_counts": dict(sorted(layer_counts.items())),
    }


def dump_structural(buf: bytes) -> str:
    """Canonical JSON text for the structural snapshot.

    Two-space indent + sorted keys at every level so a structural
    drift produces a clean, line-oriented diff in PRs.
    """
    return json.dumps(
        compute_structural(buf), indent=2, sort_keys=True
    ) + "\n"
