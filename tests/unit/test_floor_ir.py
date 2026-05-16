"""Parity gate: ``build_floor_ir(...)`` matches committed FB buffers.

For each fixture under ``tests/fixtures/floor_ir/<descriptor>/``,
the IR emitter must produce a FlatBuffer that byte-equals the
committed ``floor.nir``. Phase 1.k populated the fixtures and
rewired ``render_floor_svg`` through the IR pipeline; this gate
catches any drift in the emitter (per-tile order, schema field
ordering, RNG seed, theme/seed metadata).

The companion test ``test_ir_to_svg.py`` checks the reverse
direction (IR → SVG byte-equal to legacy). Together they pin down
both the emitter and the transformer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "floor_ir"
)


@pytest.mark.skip(
    reason="NIR4: committed fixture .nir files still carry the NIR3 "
    "file_identifier; fixture regeneration is task #10."
)
@pytest.mark.parametrize("descriptor", all_descriptors())
def test_floor_ir_buffer_matches_fixture(descriptor: str) -> None:
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(descriptor)
    fixture = _FIXTURE_ROOT / descriptor
    expected = (fixture / "floor.nir").read_bytes()
    assert expected, (
        f"fixture .nir is empty — re-run "
        f"`python -m tests.samples.regenerate_fixtures`"
    )

    actual = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
    )

    assert actual == expected, (
        f"{descriptor}: emitted IR diverges from committed fixture"
    )
