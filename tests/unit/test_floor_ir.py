"""Parity gate: ``build_floor_ir(...)`` matches committed FB buffers.

This is the test that turns Phase 1 of the IR migration plan into
a measurable contract: for each fixture under
``tests/fixtures/floor_ir/<descriptor>/``, the IR emitter must
produce a FlatBuffer that byte-equals the committed ``floor.nir``.

**XFAIL until Phase 1 emitter lands.** ``build_floor_ir`` does not
exist yet; the import fails, the tests xfail with
``ModuleNotFoundError``. When Phase 1 ships and populates
``floor.nir`` per fixture, remove the ``pytest.importorskip`` /
``xfail`` markers and the gate goes live.

The companion test ``test_ir_to_svg.py`` checks the reverse
direction (IR → SVG byte-equal to legacy). Together they pin down
both the emitter and the transformer.
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
           "build_floor_ir; until then the .nir fixtures are empty.",
    strict=True,
)
@pytest.mark.parametrize("descriptor", _fixture_descriptors())
def test_floor_ir_buffer_matches_fixture(descriptor: str) -> None:
    from nhc.rendering.ir_emitter import build_floor_ir  # type: ignore

    fixture = _FIXTURE_ROOT / descriptor
    expected = (fixture / "floor.nir").read_bytes()
    assert expected, "fixture .nir is empty — Phase 1 not landed yet"

    # The IR emitter API surface lands in Phase 1; this call shape
    # is the placeholder contract. Update it when the emitter ships.
    actual = build_floor_ir(descriptor=descriptor)

    assert actual == expected, (
        f"{descriptor}: emitted IR diverges from committed fixture"
    )
