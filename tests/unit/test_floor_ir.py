"""Parity gate: ``build_floor_ir(...)`` matches committed FB buffers.

This is the test that turns Phase 1 of the IR migration plan into
a measurable contract: for each fixture under
``tests/fixtures/floor_ir/<descriptor>/``, the IR emitter must
produce a FlatBuffer that byte-equals the committed ``floor.nir``.

**XFAIL until Phase 1.k lands.** Phase 1.a wires the skeleton
``build_floor_ir`` and the per-layer commits 1.b–1.j progressively
populate the IR. The fixtures' ``floor.nir`` files become non-empty
at 1.k, when ``render_floor_svg`` is rewired and the regenerator is
re-run; that is when this gate flips live.

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


@pytest.mark.xfail(
    reason="Phase 1.k of plans/nhc_ir_migration_plan.md populates "
           "the .nir fixtures; 1.a–1.j land the emitter behind "
           "the gate.",
    strict=True,
)
@pytest.mark.parametrize("descriptor", all_descriptors())
def test_floor_ir_buffer_matches_fixture(descriptor: str) -> None:
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(descriptor)
    fixture = _FIXTURE_ROOT / descriptor
    expected = (fixture / "floor.nir").read_bytes()
    assert expected, "fixture .nir is empty — Phase 1.k not landed yet"

    actual = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )

    assert actual == expected, (
        f"{descriptor}: emitted IR diverges from committed fixture"
    )
