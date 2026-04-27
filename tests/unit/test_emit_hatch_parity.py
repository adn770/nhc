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

from nhc.rendering._hatching import _render_corridor_hatching
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_corridor_parity(descriptor: str) -> None:
    """1.c.1 — corridor-hatch fragment matches legacy byte-for-byte."""
    inputs = descriptor_inputs(descriptor)

    legacy_lines: list[str] = []
    _render_corridor_hatching(legacy_lines, inputs.level, inputs.seed)
    legacy = "\n".join(legacy_lines)

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="hatching")

    assert actual == legacy, (
        f"{descriptor}: corridor-hatch IR fragment diverges from legacy"
    )
