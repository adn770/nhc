"""v5 emit pipeline.

:func:`emit_all` is the canonical Phase 4.3a entry point: takes a
:class:`FloorIRBuilder` and walks its ``ctx`` / ``regions`` /
``site`` to produce ``(v5_regions, v5_ops)``. Each module under
this package owns one slice of the v5 op taxonomy (per
``design/map_ir_v5.md`` §3.5) and exports an ``emit_*`` builder
walk:

- :mod:`regions`         — Region → V5Region
- :mod:`paint`           — V5PaintOp (Material families)
- :mod:`stamp`           — V5StampOp (decorator-bit overlays)
- :mod:`path`            — V5PathOp (cart-tracks / ore-vein)
- :mod:`fixture`         — V5FixtureOp (stairs / wells / fountains /
                           trees / bushes)
- :mod:`stroke`          — V5StrokeOp (room / cave / corridor /
                           building / enclosure walls)
- :mod:`shadow`          — ShadowOp
- :mod:`hatch`           — V5HatchOp
- :mod:`roof`            — V5RoofOp
- :mod:`thematic_detail` — V5FixtureOp (Web / Skull / Bone /
                           LooseStone, gated via Rust binding)
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.emit.fixture import emit_fixtures
from nhc.rendering.emit.hatch import emit_hatches
from nhc.rendering.emit.paint import emit_paints
from nhc.rendering.emit.path import emit_paths
from nhc.rendering.emit.regions import emit_regions, translate_region
from nhc.rendering.emit.roof import emit_roofs
from nhc.rendering.emit.shadow import emit_shadows
from nhc.rendering.emit.stamp import emit_stamps
from nhc.rendering.emit.stroke import emit_strokes
from nhc.rendering.emit.thematic_detail import (
    emit_loose_stones,
    emit_thematic_details,
)

__all__ = [
    "emit_all",
    "emit_fixtures",
    "emit_hatches",
    "emit_loose_stones",
    "emit_paints",
    "emit_paths",
    "emit_regions",
    "emit_roofs",
    "emit_shadows",
    "emit_stamps",
    "emit_strokes",
    "emit_thematic_details",
    "translate_region",
]


def emit_all(builder: Any) -> tuple[list[Any], list[Any]]:
    """Build the v5 regions + ops list directly from a builder.

    Op order matches the v4 IR_STAGES sequence so the v5 stream
    stays positionally identical to the legacy translator output
    (modulo the deferred site / building branches in
    :mod:`nhc.rendering.v5_emit.stroke`).
    """
    v5_regions = emit_regions(builder)
    v5_ops: list[Any] = []
    v5_ops.extend(emit_shadows(builder))
    v5_ops.extend(emit_paints(builder))
    v5_ops.extend(emit_strokes(builder))
    v5_ops.extend(emit_roofs(builder))
    v5_ops.extend(emit_stamps(builder))
    v5_ops.extend(emit_paths(builder))
    v5_ops.extend(emit_fixtures(builder))
    v5_ops.extend(emit_thematic_details(builder))
    v5_ops.extend(emit_loose_stones(builder))
    v5_ops.extend(emit_hatches(builder))
    return v5_regions, v5_ops
