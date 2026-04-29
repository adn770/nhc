#!/usr/bin/env python3
"""Regenerate the floor-IR parity fixtures.

The fixtures (under ``tests/fixtures/floor_ir/<descriptor>/``)
are the byte-equal parity gate that protects every transition in
the IR migration plan up to Phase 7, plus the cross-rasteriser
parity contract from Phase 8 onward (``design/map_ir.md`` §9.4).
Each fixture carries:

- ``floor.svg``        — IR-driven SVG output; bit-for-bit
                         reference.
- ``floor.nir``        — IR FlatBuffer.
- ``floor.json``       — canonicalised JSON dump of the IR.
- ``hatch.svg``        — per-layer relaxed-gate snapshot lock.
- ``floor_detail.svg`` — per-layer relaxed-gate snapshot lock.
- ``thematic_detail.svg`` — per-layer relaxed-gate snapshot lock.
- ``structural.json``  — IR-level structural-invariants snapshot
                         (op counts, region counts, layer element
                         counts) that ``test_ir_png_parity.py``
                         byte-equal checks.
- ``reference.png``    — canonical tiny-skia rasterisation of the
                         IR. Frozen reference for the PSNR > 35 dB
                         pixel-parity gate. **Only regenerated
                         under ``--regen-reference``** so an
                         accidental tiny-skia drift surfaces in
                         CI as a parity failure, not a quietly
                         updated fixture.

The descriptor encodes the level construction tuple as
``<seed>_<shape>_<theme>_<floor_kind>`` so a regression bisects
to a specific (shape × theme × floor_kind) cell.

Usage:
    python -m tests.samples.regenerate_fixtures           # all but reference.png
    python -m tests.samples.regenerate_fixtures --regen-reference
                                                          # also rewrite reference.png
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


@dataclasses.dataclass(frozen=True, slots=True)
class _RenderedFixture:
    svg: str
    nir: bytes
    js: str
    hatch_svg: str
    floor_detail_svg: str
    thematic_detail_svg: str
    structural: str
    reference_png: bytes


def _render_fixture(fx: Fixture) -> _RenderedFixture:
    """Build the level and return all six artefacts.

    Phase 1.k lights up ``nir`` and ``json`` — :func:`build_floor_ir`
    drives the IR pipeline that ``render_floor_svg`` now routes
    through, and the canonicalised JSON dump from
    :mod:`nhc.rendering.ir.dump` makes the buffer git-reviewable.

    Phase 4 sub-step 1.f adds the per-layer ``hatch.svg`` snapshot
    — the relaxed parity gate replaces byte-equal-with-legacy with
    structural invariants + a byte-equal snapshot lock against the
    Rust output. Sub-step 3.f extends the same shape to
    ``floor_detail.svg``; sub-step 4.f to ``thematic_detail.svg``.

    Phase 8.0 pre-step (`design/map_ir.md` §9.4) adds
    ``structural.json`` (the IR-level invariants snapshot) and
    ``reference.png`` (the canonical tiny-skia rasterisation that
    the PSNR > 35 dB pixel-parity gate measures every rasteriser
    against).
    """
    import nhc_render

    from nhc.rendering.ir.dump import dump
    from nhc.rendering.ir.structural import dump_structural
    from nhc.rendering.ir_emitter import build_floor_ir
    from nhc.rendering.ir_to_svg import layer_to_svg

    level = _build_level(fx)
    svg = render_level_svg(level, seed=fx.seed)
    nir = bytes(build_floor_ir(level, seed=fx.seed))
    js = dump(nir)
    hatch_svg = layer_to_svg(nir, layer="hatching")
    floor_detail_svg = layer_to_svg(nir, layer="floor_detail")
    thematic_detail_svg = layer_to_svg(nir, layer="thematic_detail")
    structural = dump_structural(nir)
    reference_png = bytes(nhc_render.ir_to_png(nir, 1.0, None))
    return _RenderedFixture(
        svg=svg,
        nir=nir,
        js=js,
        hatch_svg=hatch_svg,
        floor_detail_svg=floor_detail_svg,
        thematic_detail_svg=thematic_detail_svg,
        structural=structural,
        reference_png=reference_png,
    )


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "floor_ir"


def _write_fixture(
    fx: Fixture, root: Path, *, regen_reference: bool,
) -> None:
    """Write every fixture artefact for ``fx`` to its directory.

    ``reference.png`` is rewritten only when ``regen_reference`` is
    True or when the file is missing — its drift is the rasteriser
    drift the PSNR gate watches, so silent overwriting would defeat
    the gate.
    """
    rendered = _render_fixture(fx)
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.svg").write_text(rendered.svg)
    (out / "floor.nir").write_bytes(rendered.nir)
    (out / "floor.json").write_text(rendered.js)
    (out / "hatch.svg").write_text(rendered.hatch_svg)
    (out / "floor_detail.svg").write_text(rendered.floor_detail_svg)
    (out / "thematic_detail.svg").write_text(rendered.thematic_detail_svg)
    (out / "structural.json").write_text(rendered.structural)
    reference_path = out / "reference.png"
    if regen_reference or not reference_path.exists():
        reference_path.write_bytes(rendered.reference_png)


def _check_fixture(fx: Fixture, root: Path) -> list[str]:
    """Return a list of diff messages for any drift; empty if clean."""
    rendered = _render_fixture(fx)
    out = root / fx.descriptor
    drifts: list[str] = []
    text_artefacts: list[tuple[str, str]] = [
        ("floor.svg", rendered.svg),
        ("floor.json", rendered.js),
        ("hatch.svg", rendered.hatch_svg),
        ("floor_detail.svg", rendered.floor_detail_svg),
        ("thematic_detail.svg", rendered.thematic_detail_svg),
        ("structural.json", rendered.structural),
    ]
    for name, expected in text_artefacts:
        path = out / name
        if not path.exists():
            drifts.append(f"{fx.descriptor}: {name} missing")
        elif path.read_text() != expected:
            drifts.append(f"{fx.descriptor}: {name} drift")
    binary_artefacts: list[tuple[str, bytes]] = [
        ("floor.nir", rendered.nir),
        ("reference.png", rendered.reference_png),
    ]
    for name, expected_bytes in binary_artefacts:
        path = out / name
        if not path.exists():
            drifts.append(f"{fx.descriptor}: {name} missing")
        elif path.read_bytes() != expected_bytes:
            drifts.append(f"{fx.descriptor}: {name} drift")
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
        "--regen-reference",
        action="store_true",
        help="Force regeneration of reference.png. Default behaviour "
             "writes reference.png only when missing, so an "
             "accidental tiny-skia drift surfaces as a PSNR gate "
             "failure rather than a quietly updated fixture.",
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
        _write_fixture(fx, root, regen_reference=args.regen_reference)
        print(f"wrote {fx.descriptor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
