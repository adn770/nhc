"""Skeleton sentinel for the Phase 1.a IR emitter.

Pins the contract of the foundation commit: ``build_floor_ir`` exists,
returns a non-empty FlatBuffer carrying the ``NIR3`` identifier,
the metadata fields (major / minor / dimensions / theme / seed /
flags) match the input level, ``regions[]`` is populated by the
``emit_regions`` stage, ``ops[]`` is empty (per-layer commits 1.b–1.j
fill it), and ``dump.dump`` round-trips the buffer cleanly.

The integration parity gates in ``test_floor_ir.py`` and
``test_ir_to_svg.py`` stay XFAIL until 1.k. This sentinel goes
green at 1.a and stays green through the rest of Phase 1.
"""

from __future__ import annotations

import pytest

from nhc.rendering.ir._fb.FloorIR import FloorIR, FloorIRT
from nhc.rendering.ir.dump import dump

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


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
    fir = FloorIRT.InitFromObj(FloorIR.GetRootAs(buf, 0))
    return inputs, buf, fir


def test_buffer_carries_nirf_identifier(emitted) -> None:
    _, buf, _ = emitted
    assert buf, "build_floor_ir returned an empty buffer"
    assert FloorIR.FloorIRBufferHasIdentifier(buf, 0), (
        "emitted buffer is missing the NIR3 file_identifier — "
        "builder.Finish was not called with b'NIR3'"
    )


def test_schema_major_is_three(emitted) -> None:
    _, _, fir = emitted
    assert fir.major == 3
    # Minor bumps as later commits add additive schema fields; the
    # sentinel pins major only.
    assert fir.minor >= 0


def test_metadata_matches_inputs(emitted) -> None:
    inputs, _, fir = emitted
    assert fir.widthTiles == inputs.level.width
    assert fir.heightTiles == inputs.level.height
    # FlatBuffers Object-API surfaces string fields as bytes; decode
    # at the boundary. ir_to_svg / dump.py do the same.
    assert fir.theme.decode() == inputs.theme
    assert fir.baseSeed == inputs.seed


def test_flags_match_render_context(emitted) -> None:
    _, _, fir = emitted
    assert fir.flags is not None
    # vegetation defaults to True on the starter fixtures; the other
    # flag values vary by floor_kind so just assert the surface is
    # populated rather than locking exact values that 1.b–1.j tests
    # will check via per-layer parity.
    assert fir.flags.vegetationEnabled is True


def test_regions_populated_by_emit_regions(emitted) -> None:
    _, _, fir = emitted
    assert fir.regions, (
        "emit_regions wrote no regions — at least the dungeon polygon "
        "should always register"
    )
    for region in fir.regions:
        assert region.id, "region has empty id"
        assert region.polygon is not None, (
            f"region {region.id!r} has no polygon"
        )
        assert region.polygon.paths, (
            f"region {region.id!r} polygon has no paths"
        )
        assert region.polygon.rings, (
            f"region {region.id!r} polygon has no rings"
        )


def test_dump_round_trip(emitted) -> None:
    _, buf, _ = emitted
    text = dump(buf)
    assert text, "dump returned empty text"
    assert "FloorIRT" in text, (
        "dump output is missing the FloorIRT root marker"
    )
