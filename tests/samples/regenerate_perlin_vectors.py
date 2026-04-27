#!/usr/bin/env python3
"""Regenerate the Perlin parity-vector fixture.

Output: ``tests/fixtures/perlin/pnoise2_vectors.json`` — ~1100
entries covering every Perlin base value the rendering code uses
(1, 2, 10–13, 20, 24, 50, 77), plus base 0 for completeness.
Sample points cover lattice-aligned, half-lattice (fade-curve
midpoint), and pseudo-random sub-lattice coordinates within the
spatial range typical emitters feed to ``pnoise2``.

Vectors are the determinism contract for the Phase 3 Rust port:
``crates/nhc-render/src/perlin.rs`` must reproduce every
``value`` here byte-for-byte (or to within float-rounding noise).

Usage:
    python -m tests.samples.regenerate_perlin_vectors
    python -m tests.samples.regenerate_perlin_vectors --check

The Python side is the canonical reference today (the vendored
shim under ``nhc/rendering/_perlin.py`` replaced the abandoned
``noise`` PyPI package). Adding a new base value to the rendering
code: bump ``_BASES`` here, regenerate, commit the new fixture
file. The pytest sentinel (``test_perlin_vectors.py``) re-checks
the file in the dev loop.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from nhc.rendering._perlin import pnoise2


# Every base-value the production rendering code passes to
# ``pnoise2`` today. New emitters must add their bases here so
# the parity vectors cover them.
_BASES: tuple[int, ...] = (0, 1, 2, 10, 11, 12, 13, 20, 24, 50, 77)


def _sample_points(seed: int) -> list[tuple[float, float]]:
    """Return 100 (x, y) sample points exercising the noise function.

    Layout: 25 lattice-aligned (output is exactly 0), 25 half-
    lattice (fade-curve midpoint, exercises the C2 smoothing),
    and 50 pseudo-random sub-lattice points.
    """
    rng = random.Random(seed)
    points: list[tuple[float, float]] = []
    # Lattice-aligned (5 × 5 grid).
    for i in range(-2, 3):
        for j in range(-2, 3):
            points.append((float(i), float(j)))
    # Half-lattice (5 × 5 grid).
    for i in range(-2, 3):
        for j in range(-2, 3):
            points.append((i + 0.5, j + 0.5))
    # Random sub-lattice within the spatial range that hatching +
    # grid emitters reach (a 60-tile floor at 0.5 scale ≈ ±50).
    for _ in range(50):
        points.append(
            (rng.uniform(-50.0, 50.0), rng.uniform(-50.0, 50.0))
        )
    return points


def _build_vectors() -> dict:
    vectors: list[dict] = []
    for base in _BASES:
        for x, y in _sample_points(seed=base):
            vectors.append(
                {"x": x, "y": y, "base": base, "value": pnoise2(x, y, base)}
            )
    return {
        "schema_version": 1,
        "source": "nhc.rendering._perlin.pnoise2",
        "bases": list(_BASES),
        "vectors": vectors,
    }


def _fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "tests" / "fixtures" / "perlin" / "pnoise2_vectors.json"
    )


def _serialise(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed fixture matches a fresh "
             "regeneration; exit non-zero on drift.",
    )
    args = parser.parse_args(argv[1:])

    fixture = _fixture_path()
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fresh = _serialise(_build_vectors())

    if args.check:
        if not fixture.exists():
            print(f"missing: {fixture}", file=sys.stderr)
            return 1
        committed = fixture.read_text()
        if committed != fresh:
            print(
                "PERLIN VECTOR DRIFT — re-run without --check to "
                "update the fixture, but only after confirming the "
                "Perlin shim change was intentional.",
                file=sys.stderr,
            )
            return 1
        print(f"ok ({len(json.loads(fresh)['vectors'])} vectors match)")
        return 0

    fixture.write_text(fresh)
    print(f"wrote {fixture} ({len(json.loads(fresh)['vectors'])} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
