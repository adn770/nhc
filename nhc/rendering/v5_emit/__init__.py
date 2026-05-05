"""v5 emit translators (Phase 1.4 of v5 migration plan).

Translates the accumulated v4 regions / ops on a
:class:`FloorIRBuilder` into v5-shaped ``V5Region`` / ``V5OpEntry``
records. The atomic cut at Phase 1.8 drops the v4 emit path; until
then the translators run alongside, populating
``FloorIR.v5_regions`` / ``FloorIR.v5_ops`` in parallel with the
live ``regions`` / ``ops`` so v5 consumers can be exercised
without touching the live render path.

Module layout mirrors the v5 op taxonomy
(``design/map_ir_v5.md`` §3.5):

- :mod:`materials` — ``V5Material`` / ``V5WallMaterial`` factories
- :mod:`regions`   — ``Region`` → ``V5Region`` translator
- :mod:`paint`     — ``FloorOp`` (+ DecoratorOp stone variants) → ``V5PaintOp``
- :mod:`stamp`     — ``FloorGridOp`` / ``FloorDetailOp`` / etc. → ``V5StampOp``
- :mod:`path`      — ``DecoratorOp.cart_tracks`` / ``ore_deposit`` → ``V5PathOp``
- :mod:`fixture`   — ``Tree`` / ``Bush`` / ``Well`` / ``Fountain`` / ``Stairs`` /
                     thematic-detail fixtures → ``V5FixtureOp``
- :mod:`stroke`    — ``InteriorWallOp`` / ``ExteriorWallOp`` /
                     ``CorridorWallOp`` → ``V5StrokeOp``
- :mod:`roof`      — ``RoofOp`` → ``V5RoofOp``

Each translator is pure: it reads a v4 op (or list) and returns a
v5 op (or list). The wiring at :func:`translate_all` runs the
full set against a builder and returns the (regions, ops) pair.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.v5_emit.fixture import translate_fixtures
from nhc.rendering.v5_emit.hatch import emit_hatches, translate_hatch_ops
from nhc.rendering.v5_emit.paint import translate_paint_ops
from nhc.rendering.v5_emit.path import emit_paths, translate_path_ops
from nhc.rendering.v5_emit.regions import emit_regions, translate_region
from nhc.rendering.v5_emit.roof import emit_roofs, translate_roof_ops
from nhc.rendering.v5_emit.shadow import emit_shadows, translate_shadow_ops
from nhc.rendering.v5_emit.stamp import emit_stamps, translate_stamp_ops
from nhc.rendering.v5_emit.stroke import translate_stroke_ops
from nhc.rendering.v5_emit.thematic_detail import (
    translate_floor_detail_loose_stones,
    translate_thematic_detail_ops,
)

__all__ = [
    "emit_all",
    "emit_hatches",
    "emit_paths",
    "emit_regions",
    "emit_stamps",
    "emit_roofs",
    "emit_shadows",
    "translate_all",
    "translate_region",
    "translate_paint_ops",
    "translate_path_ops",
    "translate_stroke_ops",
    "translate_roof_ops",
    "translate_shadow_ops",
    "translate_hatch_ops",
    "translate_stamp_ops",
    "translate_fixtures",
    "translate_thematic_detail_ops",
    "translate_floor_detail_loose_stones",
]


def emit_all(builder: Any) -> tuple[list[Any], list[Any]]:
    """Build the v5 regions + ops list directly from a builder.

    Phase 4.3a entry point. Takes a :class:`FloorIRBuilder` and walks
    its ``ctx`` / ``regions`` / ``site`` to produce
    ``(v5_regions, v5_ops)``. Per-module sub-commits migrate each
    translator under this umbrella; modules already migrated walk
    ``builder`` directly, modules pending migration still consume
    ``builder.ops``.
    """
    v5_regions = emit_regions(builder)
    v5_ops: list[Any] = []
    v5_ops.extend(emit_shadows(builder))
    v5_ops.extend(translate_paint_ops(builder.ops))
    v5_ops.extend(translate_stroke_ops(builder.ops))
    v5_ops.extend(emit_roofs(builder))
    v5_ops.extend(emit_stamps(builder))
    v5_ops.extend(emit_paths(builder))
    v5_ops.extend(translate_fixtures(builder.ops))
    v5_ops.extend(translate_thematic_detail_ops(builder.ops))
    v5_ops.extend(translate_floor_detail_loose_stones(builder.ops))
    v5_ops.extend(emit_hatches(builder))
    return v5_regions, v5_ops


def translate_all(
    *, regions: list[Any], ops: list[Any]
) -> tuple[list[Any], list[Any]]:
    """Translate v4 regions + ops into v5 regions + ``V5OpEntry`` list.

    Pure function; does not mutate inputs. Retained for the 4.3a →
    4.3c window so individual translators can be migrated module by
    module behind :func:`emit_all`.
    """
    v5_regions = [translate_region(r) for r in regions]
    v5_ops: list[Any] = []
    v5_ops.extend(translate_shadow_ops(ops))
    v5_ops.extend(translate_paint_ops(ops))
    v5_ops.extend(translate_stroke_ops(ops))
    v5_ops.extend(translate_roof_ops(ops))
    v5_ops.extend(translate_stamp_ops(ops))
    v5_ops.extend(translate_path_ops(ops))
    v5_ops.extend(translate_fixtures(ops))
    v5_ops.extend(translate_thematic_detail_ops(ops))
    v5_ops.extend(translate_floor_detail_loose_stones(ops))
    v5_ops.extend(translate_hatch_ops(ops))
    return v5_regions, v5_ops
