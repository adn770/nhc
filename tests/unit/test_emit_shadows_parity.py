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

from nhc.rendering._shadows import _render_corridor_shadows
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_corridor_parity(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)

    legacy_lines: list[str] = []
    _render_corridor_shadows(legacy_lines, inputs.level)
    legacy = "\n".join(legacy_lines)

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="shadows")

    assert actual == legacy, (
        f"{descriptor}: corridor-shadow IR fragment diverges from legacy"
    )
