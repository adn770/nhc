"""Parity gate: ``ir_to_svg(ir)`` matches the legacy SVG byte-for-byte.

For each fixture under ``tests/fixtures/floor_ir/<descriptor>/``,
loading the committed ``floor.nir`` and running it through the IR
→ SVG transformer must produce a string byte-equal to
``floor.svg``. This is the contract that protects every Phase
1–7 transition: the legacy ``render_floor_svg`` output is fixed,
the IR pipeline must reproduce it.

**XFAIL until Phase 1 transformer lands.** ``ir_to_svg`` does not
exist yet; the import fails, the tests xfail. When Phase 1 ships
the fixtures' .nir files become non-empty and the gate goes live.

Phase 5 introduces a parallel ``test_ir_png_parity.py`` (tiny-skia
output vs resvg of the SVG). Phase 6 introduces
``test_ir_canvas_parity.py`` (WASM Canvas vs PNG). The three
together cover the full transformer triangle.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "floor_ir"
)


def _fixture_descriptors() -> list[str]:
    if not _FIXTURE_ROOT.exists():
        return []
    return sorted(p.name for p in _FIXTURE_ROOT.iterdir() if p.is_dir())


@pytest.mark.xfail(
    reason="Phase 1 of plans/nhc_ir_migration_plan.md introduces "
           "ir_to_svg; until then the .nir fixtures are empty.",
    strict=True,
)
@pytest.mark.parametrize("descriptor", _fixture_descriptors())
def test_ir_to_svg_byte_equal_legacy(descriptor: str) -> None:
    from nhc.rendering.ir_to_svg import ir_to_svg  # type: ignore

    fixture = _FIXTURE_ROOT / descriptor
    nir = (fixture / "floor.nir").read_bytes()
    expected_svg = (fixture / "floor.svg").read_text()
    assert nir, "fixture .nir is empty — Phase 1 not landed yet"

    actual_svg = ir_to_svg(nir)

    assert actual_svg == expected_svg, (
        f"{descriptor}: IR→SVG diverges from legacy render_floor_svg"
    )
