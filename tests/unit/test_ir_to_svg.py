"""Parity gate: ``ir_to_svg(ir)`` matches the legacy SVG byte-for-byte.

For each fixture under ``tests/fixtures/floor_ir/<descriptor>/``,
loading the committed ``floor.nir`` and running it through the IR
→ SVG transformer must produce a string byte-equal to
``floor.svg``. This is the contract that protects every Phase
1–7 transition: the ``render_floor_svg`` output is fixed, the IR
pipeline must reproduce it. Phase 1.k rewired ``render_floor_svg``
to drive through the IR — both sides of the parity check now flow
through the same code path, so any drift in handler-side
formatting or layer ordering breaks this gate.

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


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_ir_to_svg_byte_equal_legacy(descriptor: str) -> None:
    from nhc.rendering.ir_to_svg import ir_to_svg

    fixture = _FIXTURE_ROOT / descriptor
    nir = (fixture / "floor.nir").read_bytes()
    expected_svg = (fixture / "floor.svg").read_text()
    assert nir, (
        f"fixture .nir is empty — re-run "
        f"`python -m tests.samples.regenerate_fixtures`"
    )

    actual_svg = ir_to_svg(nir)

    assert actual_svg == expected_svg, (
        f"{descriptor}: IR→SVG diverges from legacy render_floor_svg"
    )
