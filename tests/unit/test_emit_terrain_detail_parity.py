"""Per-layer parity gate for the terrain-detail layer.

Layer 600. Per-tile water / lava / chasm decorators routed
through the unified ``walk_and_paint`` pipeline with bucketed
emission (room / corridor) and a dungeon-interior clip envelope
around the room bucket.
"""

from __future__ import annotations

import pytest

from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_layers import _terrain_detail_paint
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_terrain_detail_parity(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    ctx = build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    legacy = "\n".join(_terrain_detail_paint(ctx))

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="terrain_detail")

    assert actual == legacy, (
        f"{descriptor}: terrain-detail IR fragment diverges from legacy"
    )
