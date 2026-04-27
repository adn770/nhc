"""Per-layer parity gate for the floor-grid layer.

Layer 400 — Perlin-displaced "wobbly grid" line overlay.
``_render_floor_grid`` uses a fixed ``random.Random(41)`` seed
(one of the documented code/design discrepancies in
``design/ir_primitives.md``; Phase 1 honours legacy behaviour for
byte-equal parity). Per-tile right + bottom edges feed
``_wobbly_grid_seg`` which consumes 2 RNG calls per edge plus
Perlin lookups (base=20 for right edges, base=24 for bottom).
"""

from __future__ import annotations

import pytest

from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_layers import _floor_grid_paint
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_floor_grid_parity(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    ctx = build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    legacy = "\n".join(_floor_grid_paint(ctx))

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="floor_grid")

    assert actual == legacy, (
        f"{descriptor}: floor-grid IR fragment diverges from legacy"
    )
