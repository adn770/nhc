"""Skeleton sentinel for the Phase 5.1 / 5.1.1 IR → PNG path.

Pins the FFI shape locked in ``plans/nhc_ir_migration_plan.md``:
``nhc_render.ir_to_png(ir_bytes, scale=1.0, layer=None) ->
bytes`` exists, returns valid PNG bytes, sizes the canvas to
match the legacy SVG rule (``width_tiles * cell + 2 * padding``),
honours the ``scale`` multiplier, and accepts layer names from
``ir_to_svg.py``'s ``_LAYER_OPS``. The per-primitive 5.2 / 5.3 /
5.4 commits fill in the pixmap content without changing this
sentinel.

Goes green at 5.1 and stays green through the rest of Phase 5 —
the per-layer parity gate lives in ``test_ir_png_parity.py``.
"""

from __future__ import annotations

import struct

import pytest

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


nhc_render = pytest.importorskip(
    "nhc_render",
    reason=(
        "nhc_render extension not installed — run `make rust-build` "
        "or `pip install -e crates/nhc-render` first"
    ),
)


# PNG signature: 137 80 78 71 13 10 26 10 = "\x89PNG\r\n\x1a\n".
PNG_SIG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module", params=all_descriptors())
def emitted(request):
    """Build each starter-fixture level once per module."""
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(request.param)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    return inputs, buf


def test_function_is_exposed() -> None:
    assert hasattr(nhc_render, "ir_to_png")


def test_returns_valid_png_bytes(emitted) -> None:
    _, buf = emitted
    png = nhc_render.ir_to_png(bytes(buf), 1.0, None)
    assert isinstance(png, (bytes, bytearray))
    assert png[:8] == PNG_SIG, "PNG signature missing"


def test_canvas_matches_svg_sizing_rule(emitted) -> None:
    """Canvas dims follow ``width_tiles * cell + 2 * padding``.

    PNG IHDR carries width/height as big-endian u32 at offsets
    16..24. Default cell=32 / padding=32 means a 4×3 floor lands
    at 192×160; this test asserts the rule for whatever the
    starter fixtures actually carry.
    """
    inputs, buf = emitted
    png = nhc_render.ir_to_png(bytes(buf), 1.0, None)
    w, h = struct.unpack(">II", png[16:24])
    expected_w = inputs.level.width * 32 + 2 * 32
    expected_h = inputs.level.height * 32 + 2 * 32
    assert w == expected_w
    assert h == expected_h


def test_scale_factor_multiplies_canvas(emitted) -> None:
    inputs, buf = emitted
    png = nhc_render.ir_to_png(bytes(buf), 2.0, None)
    w, h = struct.unpack(">II", png[16:24])
    assert w == 2 * (inputs.level.width * 32 + 2 * 32)
    assert h == 2 * (inputs.level.height * 32 + 2 * 32)


def test_rejects_buffer_without_identifier() -> None:
    with pytest.raises(ValueError):
        nhc_render.ir_to_png(b"\x00" * 16, 1.0, None)


@pytest.mark.parametrize("layer", [
    "shadows",
    "hatching",
    "structural",
    "terrain_tints",
    "floor_grid",
    "floor_detail",
    "thematic_detail",
    "terrain_detail",
    "stairs",
    "surface_features",
])
def test_layer_filter_accepts_known_names(emitted, layer: str) -> None:
    """Every layer name in ``ir_to_svg``'s ``_LAYER_OPS`` resolves
    without error. Catches drift between the Rust mirror and the
    Python source of truth.
    """
    _, buf = emitted
    png = nhc_render.ir_to_png(bytes(buf), 1.0, layer)
    assert png[:8] == PNG_SIG


def test_layer_filter_rejects_unknown(emitted) -> None:
    _, buf = emitted
    with pytest.raises(ValueError):
        nhc_render.ir_to_png(bytes(buf), 1.0, "not-a-layer")
