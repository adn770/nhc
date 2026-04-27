#!/usr/bin/env python3
"""Regenerate the floor-IR parity fixtures.

The fixtures (under ``tests/fixtures/floor_ir/<descriptor>/``)
are the byte-equal parity gate that protects every transition in
the IR migration plan up to Phase 7. Each fixture carries:

- ``floor.svg``  — current legacy ``render_floor_svg`` output;
                   bit-for-bit reference.
- ``floor.nir``  — IR FlatBuffer (empty until Phase 1 emitter).
- ``floor.json`` — canonicalised JSON dump of the IR (empty
                   until Phase 1; produced by
                   ``nhc.rendering.ir.dump.dump``).

The descriptor encodes the level construction tuple as
``<seed>_<shape>_<theme>_<floor_kind>`` so a regression bisects
to a specific (shape × theme × floor_kind) cell.

Usage:
    python -m tests.samples.regenerate_fixtures           # write all
    python -m tests.samples.regenerate_fixtures --check   # CI guard
    python -m tests.samples.regenerate_fixtures -k seed42 # filter

The starter fixture set is intentionally small — three entries
covering rect dungeon, octagon-shaped dungeon, and a cave —
because the harness is what Phase 0.5 ships. New fixtures land
phase-by-phase as later primitives gain coverage; ~30–45 entries
across (shape × theme × floor_kind) is the Phase 4 target.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.pipeline import generate_level
from nhc.rendering.level_svg import render_level_svg


@dataclasses.dataclass(frozen=True, slots=True)
class Fixture:
    seed: int
    shape: str        # "rect" | "octagon" | "cave" | "circle" | "hybrid" | "pill"
    theme: str        # "dungeon" | "crypt" | "cave" | "sewer" | "castle" | …
    floor_kind: str   # "dungeon" | "cave" | "building" | "surface"
    width: int = 60
    height: int = 40

    @property
    def descriptor(self) -> str:
        return f"seed{self.seed}_{self.shape}_{self.theme}_{self.floor_kind}"


# ── Starter fixture set ─────────────────────────────────────────
#
# Picked for diversity, not coverage. New fixtures join this list
# as later phases of the IR migration touch new primitives. The
# Phase 4 target is ~30–45.

_FIXTURES: tuple[Fixture, ...] = (
    Fixture(seed=42, shape="rect", theme="dungeon", floor_kind="dungeon"),
    Fixture(seed=7, shape="octagon", theme="crypt", floor_kind="dungeon"),
    Fixture(seed=99, shape="cave", theme="cave", floor_kind="cave"),
)


_SHAPE_VARIETY: dict[str, float] = {
    "rect": 0.0,
    "octagon": 0.7,
    "circle": 0.7,
    "pill": 0.5,
    "hybrid": 1.0,
    "cave": 0.0,   # caves don't use shape variety
}


def _build_level(fx: Fixture):
    """Construct a Level for the given fixture descriptor."""
    if fx.floor_kind == "cave":
        params = GenerationParams(
            width=fx.width,
            height=fx.height,
            depth=1,
            seed=fx.seed,
            theme=fx.theme,
            template="procedural:cave",
            shape_variety=0.0,
        )
    else:
        params = GenerationParams(
            width=fx.width,
            height=fx.height,
            depth=1,
            seed=fx.seed,
            theme=fx.theme,
            shape_variety=_SHAPE_VARIETY.get(fx.shape, 0.3),
            preferred_shapes=(
                None if fx.shape == "rect" else [fx.shape]
            ),
        )
    return generate_level(params)


def _render_fixture(fx: Fixture) -> tuple[str, bytes, str]:
    """Build the level and return (svg, nir, json) tuple.

    Today only ``svg`` is real. ``nir`` is empty bytes; ``json`` is
    an empty string. Phase 1 lands the emitter and populates them.
    """
    level = _build_level(fx)
    svg = render_level_svg(level, seed=fx.seed)
    return svg, b"", ""


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "floor_ir"


def _write_fixture(fx: Fixture, root: Path) -> None:
    svg, nir, js = _render_fixture(fx)
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.svg").write_text(svg)
    (out / "floor.nir").write_bytes(nir)
    (out / "floor.json").write_text(js)


def _check_fixture(fx: Fixture, root: Path) -> list[str]:
    """Return a list of diff messages for any drift; empty if clean."""
    svg, nir, js = _render_fixture(fx)
    out = root / fx.descriptor
    drifts: list[str] = []
    svg_path = out / "floor.svg"
    if not svg_path.exists():
        drifts.append(f"{fx.descriptor}: floor.svg missing")
    elif svg_path.read_text() != svg:
        drifts.append(f"{fx.descriptor}: floor.svg drift")
    nir_path = out / "floor.nir"
    if not nir_path.exists():
        drifts.append(f"{fx.descriptor}: floor.nir missing")
    elif nir_path.read_bytes() != nir:
        drifts.append(f"{fx.descriptor}: floor.nir drift")
    js_path = out / "floor.json"
    if not js_path.exists():
        drifts.append(f"{fx.descriptor}: floor.json missing")
    elif js_path.read_text() != js:
        drifts.append(f"{fx.descriptor}: floor.json drift")
    return drifts


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed fixtures match a fresh regeneration; "
             "exit non-zero on drift. Used by CI.",
    )
    parser.add_argument(
        "-k",
        dest="filter",
        default=None,
        help="Substring filter on the fixture descriptor",
    )
    args = parser.parse_args(argv[1:])

    root = _root_dir()
    root.mkdir(parents=True, exist_ok=True)

    if args.filter:
        selected = [fx for fx in _FIXTURES if args.filter in fx.descriptor]
    else:
        selected = list(_FIXTURES)

    if not selected:
        print("no fixtures matched filter", file=sys.stderr)
        return 2

    if args.check:
        all_drifts: list[str] = []
        for fx in selected:
            all_drifts.extend(_check_fixture(fx, root))
        if all_drifts:
            print("FIXTURE DRIFT — re-run without --check to update:",
                  file=sys.stderr)
            for line in all_drifts:
                print(f"  - {line}", file=sys.stderr)
            return 1
        print(f"ok ({len(selected)} fixtures match committed)")
        return 0

    for fx in selected:
        _write_fixture(fx, root)
        print(f"wrote {fx.descriptor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
