"""Skeleton sentinel for the Phase 5.1 IR → PNG stub.

Pins the FFI shape locked in
``plans/nhc_ir_migration_plan.md`` Phase 5.1: the
``nhc_render.ir_to_png(ir_bytes, scale=1.0) -> bytes`` function
exists, returns valid PNG bytes (magic header), sizes the canvas
to match the legacy SVG sizing rule
(``width_tiles * cell + 2 * padding``), and honours the ``scale``
multiplier. The pixmap content is intentionally empty
(transparent) at this commit; later Phase 5 sub-commits populate
it primitive-by-primitive without changing this sentinel.

Goes green at 5.1 and stays green through the rest of Phase 5 —
the parity gate (Phase 5.7) lives in its own file.
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
    png = nhc_render.ir_to_png(bytes(buf), 1.0)
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
    png = nhc_render.ir_to_png(bytes(buf), 1.0)
    w, h = struct.unpack(">II", png[16:24])
    expected_w = inputs.level.width * 32 + 2 * 32
    expected_h = inputs.level.height * 32 + 2 * 32
    assert w == expected_w
    assert h == expected_h


def test_scale_factor_multiplies_canvas(emitted) -> None:
    inputs, buf = emitted
    png = nhc_render.ir_to_png(bytes(buf), 2.0)
    w, h = struct.unpack(">II", png[16:24])
    assert w == 2 * (inputs.level.width * 32 + 2 * 32)
    assert h == 2 * (inputs.level.height * 32 + 2 * 32)


def test_rejects_buffer_without_identifier() -> None:
    with pytest.raises(ValueError):
        nhc_render.ir_to_png(b"\x00" * 16, 1.0)
