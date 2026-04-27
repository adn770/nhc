"""Per-layer parity gate for the walls + floors layer.

Layer 300. Deterministic — no RNG, no Perlin. The challenge here
isn't sequencing but data shape: ``_render_walls_and_floors``
calls ``_room_svg_outline`` and ``_outline_with_gaps`` which need
the live :class:`Room` and :class:`Level` (per-room openings,
shape-specific gap geometry). The IR carries a transitional
pair of pre-rendered fragment arrays
(``smooth_fill_svg`` / ``smooth_wall_svg``) on
:class:`WallsAndFloorsOp`; Phase 4 refactors them into structured
geometry when the Rust port lands.

Asserts ``layer_to_svg(buf, "walls_and_floors")`` byte-equals the
joined ``_walls_and_floors_paint(ctx)`` output across every
starter fixture.
"""

from __future__ import annotations

import pytest

from nhc.rendering._cave_geometry import _build_cave_wall_geometry
from nhc.rendering._dungeon_polygon import _build_dungeon_polygon
from nhc.rendering._floor_layers import _walls_and_floors_paint
from nhc.rendering._render_context import build_render_context
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_walls_and_floors_parity(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    ctx = build_render_context(
        inputs.level,
        seed=inputs.seed,
        cave_geometry_builder=_build_cave_wall_geometry,
        dungeon_polygon_builder=_build_dungeon_polygon,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    legacy = "\n".join(_walls_and_floors_paint(ctx))

    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    actual = layer_to_svg(buf, layer="walls_and_floors")

    assert actual == legacy, (
        f"{descriptor}: walls_and_floors IR fragment diverges from legacy"
    )
