"""Per-layer parity gate for the surface-features layer.

Layer 800 — wells, fountains, trees, bushes routed through the
unified ``TileWalkLayer`` pipeline. The starter fixtures (rect
dungeon, octagon crypt, cave) have no surface fixtures or
vegetation, so the legacy output is empty for all three. This
test pins the empty-equality contract — when a future fixture
exercises the layer, the test catches divergence and the emit /
handler can grow then.
"""

from __future__ import annotations

import pytest

from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_layers import _surface_features_paint
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_surface_features_parity(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    ctx = build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    legacy = "\n".join(_surface_features_paint(ctx))

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="surface_features")

    assert actual == legacy, (
        f"{descriptor}: surface-features IR fragment diverges from legacy"
    )
