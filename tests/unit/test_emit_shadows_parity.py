"""Per-layer parity gate for the shadows layer.

The integration parity gate in :mod:`tests.unit.test_ir_to_svg`
compares the full SVG output, but only after Phase 1.k rewires
``render_floor_svg``. This per-layer gate runs earlier — it slices
the IR to the shadows-layer ops and compares the rendered fragment
against the legacy ``_render_corridor_shadows`` /
``_render_room_shadows`` output for the same :class:`RenderContext`.
A regression bisects to a single layer commit, not to "something
broke between 1.b and 1.j".

Phase 1.b.1 adds :func:`test_corridor_parity` (corridors-only,
covers all three starter fixtures). Phase 1.b.2 adds
``test_full_layer_parity`` (full shadows layer, including the
per-shape room dispatch).
"""

from __future__ import annotations

import pytest

from nhc.rendering._floor_layers import _shadows_paint
from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._render_context import build_render_context
from nhc.rendering._shadows import _render_corridor_shadows
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


def _build_buf(inputs):
    return build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )


def _build_ctx(inputs):
    return build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_corridor_parity(descriptor: str) -> None:
    """1.b.1 regression test — corridor-only fragment matches legacy."""
    inputs = descriptor_inputs(descriptor)

    legacy_lines: list[str] = []
    _render_corridor_shadows(legacy_lines, inputs.level)
    legacy = "\n".join(legacy_lines)

    actual = layer_to_svg(_build_buf(inputs), layer="shadows")
    if not legacy_lines:
        # Cave fixture has zero corridor tiles; the IR must surface
        # nothing-from-corridor too, but the room-shadow ops will
        # populate the layer fragment in 1.b.2.
        assert legacy == ""
        return

    # When the level has corridors, the corridor-rect lines are the
    # *tail* of layer_to_svg's output (ShadowOp(Corridor) is emitted
    # after every ShadowOp(Room) per _emit_shadows_ir). Slice them
    # off and compare.
    corridor_count = len(legacy_lines)
    actual_lines = actual.split("\n")
    assert actual_lines[-corridor_count:] == legacy_lines, (
        f"{descriptor}: corridor-shadow tail diverges from legacy"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_full_layer_parity(descriptor: str) -> None:
    """1.b.2 — whole shadows-layer fragment byte-equals legacy."""
    inputs = descriptor_inputs(descriptor)
    ctx = _build_ctx(inputs)

    legacy = "\n".join(_shadows_paint(ctx))
    actual = layer_to_svg(_build_buf(inputs), layer="shadows")

    assert actual == legacy, (
        f"{descriptor}: shadows-layer IR fragment diverges from legacy"
    )
