"""Per-layer parity gate for the hatching layer.

The hatching layer is the most RNG-sensitive port in Phase 1: a
single off-by-one in the per-tile call sequence breaks parity
across the whole fixture's hatch fragment. The contract this gate
enforces is the determinism spec in ``design/ir_primitives.md``
§7.2 — see that doc for the canonical RNG and Perlin call order.

Phase 1.c.1 ships :func:`test_corridor_parity` (corridor halo
only, ``_render_corridor_hatching`` byte-for-byte). Phase 1.c.2
adds ``test_full_layer_parity`` once the room-perimeter halo
lands.
"""

from __future__ import annotations

import pytest

from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_layers import _hatching_paint
from nhc.rendering._hatching import _render_corridor_hatching
from nhc.rendering._render_context import build_render_context
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
    """1.c.1 regression — corridor-only fragment matches legacy.

    Once 1.c.2 lands the room halo, ``layer_to_svg(buf, "hatching")``
    streams Room-op output before Corridor-op output (matching
    ``_hatching_paint`` order). Slice off the corridor tail to keep
    this test focused on the corridor port.
    """
    inputs = descriptor_inputs(descriptor)

    legacy_lines: list[str] = []
    _render_corridor_hatching(legacy_lines, inputs.level, inputs.seed)
    legacy = "\n".join(legacy_lines)

    actual = layer_to_svg(_build_buf(inputs), layer="hatching")
    if not legacy_lines:
        # No corridor tiles in this fixture; nothing to assert here —
        # test_full_layer_parity covers any room-halo output.
        return

    actual_lines = actual.split("\n")
    corridor_count = len(legacy_lines)
    assert actual_lines[-corridor_count:] == legacy_lines, (
        f"{descriptor}: corridor-hatch tail diverges from legacy"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_full_layer_parity(descriptor: str) -> None:
    """1.c.2 — full hatching-layer fragment byte-equals legacy."""
    inputs = descriptor_inputs(descriptor)
    ctx = _build_ctx(inputs)

    legacy = "\n".join(_hatching_paint(ctx))
    actual = layer_to_svg(_build_buf(inputs), layer="hatching")

    assert actual == legacy, (
        f"{descriptor}: hatching-layer IR fragment diverges from legacy"
    )
