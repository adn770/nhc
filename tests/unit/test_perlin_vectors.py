"""Cross-language Perlin determinism contract.

The committed fixture
``tests/fixtures/perlin/pnoise2_vectors.json`` is the canonical
source of truth for the Perlin output every emitter expects.
Two layers of assertion:

1. Python — the vendored shim
   (``nhc.rendering._perlin.pnoise2``) reproduces every value in
   the fixture today. If this goes red, the shim drifted from the
   committed fixture and either the shim or the fixture is wrong;
   investigate before regenerating.

2. Rust — ``nhc_render.perlin2`` must produce the same values
   once the Phase 3 port lands. **XFAIL until then.** When the
   port ships, remove the ``importorskip`` / ``xfail`` markers
   and the cross-language gate goes live.

Together these tests are what protects the Phase 4 byte-equal
parity gates: any procedural primitive that uses Perlin reads
through this contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhc.rendering._perlin import pnoise2


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "perlin"
    / "pnoise2_vectors.json"
)


def _vectors() -> list[dict]:
    return json.loads(_FIXTURE_PATH.read_text())["vectors"]


def test_python_perlin_shim_matches_fixture() -> None:
    drifts: list[str] = []
    for entry in _vectors():
        got = pnoise2(entry["x"], entry["y"], entry["base"])
        if got != entry["value"]:
            drifts.append(
                f"x={entry['x']} y={entry['y']} base={entry['base']}: "
                f"got {got!r}, want {entry['value']!r}"
            )
    assert not drifts, (
        "Python Perlin shim drifted from the committed fixture. "
        "If this is intentional, regenerate with "
        "`python -m tests.samples.regenerate_perlin_vectors` and "
        "commit the JSON. Drifts:\n"
        + "\n".join(f"  - {d}" for d in drifts[:5])
        + (f"\n  ... and {len(drifts) - 5} more" if len(drifts) > 5 else "")
    )


@pytest.mark.xfail(
    reason="Phase 3 of plans/nhc_ir_migration_plan.md ports "
           "perlin to Rust; until then nhc_render.perlin2 is "
           "an `unimplemented!` skeleton.",
    strict=True,
)
def test_rust_perlin_matches_fixture() -> None:
    nhc_render = pytest.importorskip("nhc_render")
    drifts: list[str] = []
    for entry in _vectors():
        got = nhc_render.perlin2(entry["x"], entry["y"], entry["base"])
        # Allow ulp-tolerant equality once the Rust port lands;
        # for now, exact match is the contract.
        if got != entry["value"]:
            drifts.append(
                f"x={entry['x']} y={entry['y']} base={entry['base']}: "
                f"rust={got!r}, fixture={entry['value']!r}"
            )
    assert not drifts, "\n".join(drifts[:10])
