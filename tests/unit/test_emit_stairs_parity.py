"""Per-layer parity gate for the stairs layer.

Layer 700. Deterministic — no RNG, no Perlin. Per-tile up/down
stair markers (tapering wedges with parallel step lines, plus a
bright fill polygon in cave fixtures).
"""

from __future__ import annotations

import pytest

from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_layers import _stairs_paint
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_stairs_parity(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    ctx = build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    legacy = "\n".join(_stairs_paint(ctx))

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="stairs")

    assert actual == legacy, (
        f"{descriptor}: stairs IR fragment diverges from legacy"
    )
