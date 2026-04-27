"""Parity gate: ``ir_to_svg(ir)`` matches the legacy SVG byte-for-byte.

For each fixture under ``tests/fixtures/floor_ir/<descriptor>/``,
loading the committed ``floor.nir`` and running it through the IR
→ SVG transformer must produce a string byte-equal to
``floor.svg``. This is the contract that protects every Phase
1–7 transition: the legacy ``render_floor_svg`` output is fixed,
the IR pipeline must reproduce it.

**XFAIL until Phase 1.k lands.** Phase 1.a wires the skeleton
``ir_to_svg`` (and the per-layer commits 1.b–1.j register
``_OP_HANDLERS`` one layer at a time). The fixtures' ``floor.nir``
files become non-empty at 1.k, when ``render_floor_svg`` is rewired
and the regenerator is re-run; that is when this gate flips live.

Phase 5 introduces a parallel ``test_ir_png_parity.py`` (tiny-skia
output vs resvg of the SVG). Phase 6 introduces
``test_ir_canvas_parity.py`` (WASM Canvas vs PNG). The three
together cover the full transformer triangle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.floor_ir._inputs import all_descriptors


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "floor_ir"
)


@pytest.mark.xfail(
    reason="Phase 1.k of plans/nhc_ir_migration_plan.md populates "
           "the .nir fixtures; 1.a–1.j land the transformer "
           "handlers behind the gate.",
    strict=True,
)
@pytest.mark.parametrize("descriptor", all_descriptors())
def test_ir_to_svg_byte_equal_legacy(descriptor: str) -> None:
    from nhc.rendering.ir_to_svg import ir_to_svg

    fixture = _FIXTURE_ROOT / descriptor
    nir = (fixture / "floor.nir").read_bytes()
    expected_svg = (fixture / "floor.svg").read_text()
    assert nir, "fixture .nir is empty — Phase 1.k not landed yet"

    actual_svg = ir_to_svg(nir)

    assert actual_svg == expected_svg, (
        f"{descriptor}: IR→SVG diverges from legacy render_floor_svg"
    )
