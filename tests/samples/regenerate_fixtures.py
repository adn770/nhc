#!/usr/bin/env python3
"""Regenerate the floor-IR parity fixtures.

The fixtures (under ``tests/fixtures/floor_ir/<descriptor>/``)
gate the IR emit + cross-rasteriser contract from
``design/map_ir.md`` §9.4. Each fixture carries:

- ``floor.nir``        — IR FlatBuffer.
- ``floor.json``       — canonicalised JSON dump of the IR.
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

Phase 2.19 retired the per-layer SVG snapshots
(``hatch.svg`` / ``floor_detail.svg`` / ``thematic_detail.svg``);
Phase 2.21 retired the whole-floor ``floor.svg`` baseline. PSNR
plus structural-sanity assertions in
``tests/unit/test_ir_png_parity.py`` now cover what those text
dumps used to gate against.

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


# ── Synthetic roof fixtures (Phase 8.1c.2) ─────────────────────
#
# Hand-built FloorIRs exercising the RoofOp dispatch in isolation.
# Each fixture carries one Site region + one Building region + one
# RoofOp; no other ops, no existing fixture contamination. Lives
# alongside the gameplay fixtures under
# tests/fixtures/floor_ir/<descriptor>/ so the regen + check flow
# is uniform. Synthetic fixtures only commit floor.nir +
# reference.png + structural.json (no floor.json — that signal
# would carry no useful roof-primitive info).


@dataclasses.dataclass(frozen=True, slots=True)
class SyntheticRoofFixture:
    """One synthetic-IR roof descriptor."""

    name: str          # "square_pyramid" / "wide_gable" / ...
    shape: str         # "rect" / "octagon" / "circle"
    rect: tuple[int, int, int, int]   # (x, y, w, h) tile coords
    seed: int = 7
    canvas_tiles: tuple[int, int] = (20, 14)

    @property
    def descriptor(self) -> str:
        return f"synthetic_roof_{self.name}"


_SYNTHETIC_ROOF_FIXTURES: tuple[SyntheticRoofFixture, ...] = (
    # Square rect → pyramid roof on a 4-vertex polygon.
    SyntheticRoofFixture(
        name="square_pyramid",
        shape="rect",
        rect=(4, 3, 6, 6),
    ),
    # Wide rect → horizontal gable.
    SyntheticRoofFixture(
        name="wide_gable",
        shape="rect",
        rect=(2, 4, 14, 5),
    ),
    # Octagon → pyramid roof on 8-vertex polygon.
    SyntheticRoofFixture(
        name="octagon",
        shape="octagon",
        rect=(4, 2, 9, 9),
    ),
    # Circle → pyramid roof on 24-vertex polygonised footprint.
    SyntheticRoofFixture(
        name="circle",
        shape="circle",
        rect=(4, 2, 10, 10),
    ),
)


@dataclasses.dataclass(frozen=True, slots=True)
class SyntheticEnclosureFixture:
    """Synthetic-IR EnclosureOp descriptor for the Phase 8.2 PSNR
    gate. Carries one Site region + one EnclosureOp."""

    name: str
    style: str          # "palisade" / "fortification"
    polygon_tiles: tuple[tuple[int, int], ...]
    gates: tuple[tuple[int, float, float], ...] = ()
    corner_style: str = "merlon"  # "merlon" | "diamond" | "tower"
    seed: int = 7
    canvas_tiles: tuple[int, int] = (22, 16)

    @property
    def descriptor(self) -> str:
        return f"synthetic_enclosure_{self.name}"


_SYNTHETIC_ENCLOSURE_FIXTURES: tuple[SyntheticEnclosureFixture, ...] = (
    # Palisade rect (no gates) — simplest case, exercises the
    # circle-step layout on every edge.
    SyntheticEnclosureFixture(
        name="palisade_rect",
        style="palisade",
        polygon_tiles=((2, 2), (20, 2), (20, 14), (2, 14)),
    ),
    # Palisade with one gate on the top edge — exercises gate
    # cutting + door rect emission + per-edge seed isolation.
    SyntheticEnclosureFixture(
        name="palisade_gated",
        style="palisade",
        polygon_tiles=((2, 2), (20, 2), (20, 14), (2, 14)),
        gates=((0, 0.5, 32.0),),
    ),
    # Fortification with merlon corners — exercises the inset
    # battlement chain on every edge plus the axis-aligned corner
    # blocks.
    SyntheticEnclosureFixture(
        name="fortification_merlon",
        style="fortification",
        polygon_tiles=((2, 2), (20, 2), (20, 14), (2, 14)),
        corner_style="merlon",
    ),
    # Fortification with diamond corners + a single gate —
    # exercises the rotate(45) corner shape and the wood gate
    # rect inside a fortification ring.
    SyntheticEnclosureFixture(
        name="fortification_diamond_gated",
        style="fortification",
        polygon_tiles=((2, 2), (20, 2), (20, 14), (2, 14)),
        gates=((0, 0.5, 32.0),),
        corner_style="diamond",
    ),
)


@dataclasses.dataclass(frozen=True, slots=True)
class SyntheticBuildingWallFixture:
    """Synthetic-IR Building wall descriptor for the Phase 8.3
    PSNR gate. Carries one Building region + one
    BuildingExteriorWallOp + one BuildingInteriorWallOp."""

    name: str
    shape: str           # "rect" / "octagon" / "circle"
    rect: tuple[int, int, int, int]
    wall_material: str = "brick"
    interior_wall_material: str = "stone"
    interior_edges: tuple[tuple[int, int, str], ...] = ()
    seed: int = 7
    canvas_tiles: tuple[int, int] = (22, 16)

    @property
    def descriptor(self) -> str:
        return f"synthetic_building_wall_{self.name}"


@dataclasses.dataclass(frozen=True, slots=True)
class SiteFixture:
    """Phase 8.4 — gameplay site-surface fixture.

    Runs ``assemble_site(kind, ..., random.Random(seed))`` to build
    a real :class:`Site` and threads ``site=site`` into
    ``build_floor_ir`` so the emit_site_overlays stage produces the
    Site region, Building regions, RoofOps, and EnclosureOp. The
    resulting ``reference.png`` is the canonical tiny-skia render
    that the PSNR > 35 dB cross-rasteriser parity gate measures
    every rasteriser against.
    """

    seed: int
    kind: str    # "town" / "keep" / "cottage" / "ruin" / "temple"
    vegetation: bool = True

    @property
    def descriptor(self) -> str:
        return f"seed{self.seed}_{self.kind}_surface"


_SITE_FIXTURES: tuple[SiteFixture, ...] = (
    # Phase 8.4 lands one starter site fixture: a seed-7 town
    # surface with palisade enclosure + per-building roofs. Future
    # sub-phases (8.5 brick-enclosure variant) and Phase 9
    # decoration ports add more.
    SiteFixture(seed=7, kind="town"),
)


@dataclasses.dataclass(frozen=True, slots=True)
class BuildingFixture:
    """Phase 8.5 — gameplay building-floor fixture.

    Builds a real :class:`Site` via ``assemble_site`` and picks
    ``site.buildings[building_index].floors[floor_index]`` as the
    level. ``build_floor_ir`` with ``site=site`` triggers the
    emit_building_overlays stage which emits the Building region
    + interior + exterior wall ops alongside the regular gameplay
    layers.
    """

    seed: int
    site_kind: str          # "town" / "keep" / ...
    building_index: int
    floor_index: int = 0
    name: str = "brick_building_floor0"

    @property
    def descriptor(self) -> str:
        return f"seed{self.seed}_{self.name}"


_BUILDING_FIXTURES: tuple[BuildingFixture, ...] = (
    # seed-7 town building 1: brick-walled rect with 2 floors;
    # ground floor (index 0) carries interior partition lines, so
    # the fixture exercises both BuildingExteriorWallOp and
    # BuildingInteriorWallOp.
    BuildingFixture(
        seed=7, site_kind="town",
        building_index=1, floor_index=0,
        name="brick_building_floor0",
    ),
)


_SYNTHETIC_BUILDING_WALL_FIXTURES: tuple[SyntheticBuildingWallFixture, ...] = (
    # Brick rect — simplest case; orthogonal masonry runs only.
    SyntheticBuildingWallFixture(
        name="brick_rect",
        shape="rect",
        rect=(4, 3, 12, 8),
    ),
    # Stone octagon — exercises the diagonal-run path on the
    # 45-degree clipped corners.
    SyntheticBuildingWallFixture(
        name="stone_octagon",
        shape="octagon",
        rect=(5, 2, 10, 10),
        wall_material="stone",
    ),
    # Brick circle — fully diagonal polygon (24-gon).
    SyntheticBuildingWallFixture(
        name="brick_circle",
        shape="circle",
        rect=(5, 2, 10, 10),
    ),
    # Brick rect with interior partition lines — exercises
    # BuildingInteriorWallOp coalescing + line painting.
    SyntheticBuildingWallFixture(
        name="brick_with_interior",
        shape="rect",
        rect=(4, 3, 12, 8),
        interior_edges=(
            (8, 5, "north"), (9, 5, "north"), (10, 5, "north"),
            (10, 6, "west"), (10, 7, "west"),
        ),
        interior_wall_material="wood",
    ),
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
    nir: bytes
    js: str
    structural: str
    reference_png: bytes


def _render_fixture(fx: Fixture) -> _RenderedFixture:
    """Build the level and return all four artefacts.

    Phase 1.k lights up ``nir`` and ``json`` — :func:`build_floor_ir`
    drives the IR pipeline that ``render_floor_svg`` now routes
    through, and the canonicalised JSON dump from
    :mod:`nhc.rendering.ir.dump` makes the buffer git-reviewable.

    Phase 8.0 pre-step (`design/map_ir.md` §9.4) adds
    ``structural.json`` (the IR-level invariants snapshot) and
    ``reference.png`` (the canonical tiny-skia rasterisation that
    the PSNR > 35 dB pixel-parity gate measures every rasteriser
    against).

    Phase 2.21 retired ``floor.svg`` from the fixture set: the
    byte-equal SVG baseline is no longer the source of truth.
    PSNR (rasterised contract) plus structural sanity (envelope
    shape) cover what the SVG dump used to gate against.
    """
    import nhc_render

    from nhc.rendering.ir.dump import dump
    from nhc.rendering.ir.structural import dump_structural
    from nhc.rendering.ir_emitter import build_floor_ir

    level = _build_level(fx)
    nir = bytes(build_floor_ir(level, seed=fx.seed))
    js = dump(nir)
    # Phase 2.19 retired the per-layer SVG snapshots
    # (hatch / floor_detail / thematic_detail) along with
    # `nhc.rendering.ir_to_svg.layer_to_svg` and the legacy
    # `test_emit_*_invariants.py` consumers; Phase 2.21 retired
    # the whole-floor `floor.svg` baseline. The remaining gate is
    # the cross-rasteriser PSNR + structural-sanity contract in
    # `tests/unit/test_ir_png_parity.py`.
    structural = dump_structural(nir)
    reference_png = bytes(nhc_render.ir_to_png_v5(nir, 1.0, None))
    return _RenderedFixture(
        nir=nir,
        js=js,
        structural=structural,
        reference_png=reference_png,
    )


def _build_synthetic_buf(fx: SyntheticRoofFixture) -> bytes:
    """Hand-build a FloorIR buf with one Building + one RoofOp."""
    from nhc.dungeon.model import (
        CircleShape, OctagonShape, Rect, RectShape,
    )
    from nhc.rendering.ir_emitter import (
        FloorIRBuilder,
        emit_building_regions,
        emit_building_roofs,
        emit_site_region,
    )

    # Stub ctx + level — only the dimensions matter at finish-time.
    @dataclasses.dataclass
    class _Level:
        width: int
        height: int

    @dataclasses.dataclass
    class _Ctx:
        level: _Level
        seed: int = 0
        theme: str = "dungeon"
        floor_kind: str = "surface"
        shadows_enabled: bool = True
        hatching_enabled: bool = True
        atmospherics_enabled: bool = True
        macabre_detail: bool = False
        vegetation_enabled: bool = True
        interior_finish: str = ""

    @dataclasses.dataclass
    class _Building:
        base_shape: object
        base_rect: Rect

    width, height = fx.canvas_tiles
    # ctx.seed mirrors fx.seed so the v5 emit_roofs path (which reads
    # builder.ctx.seed) computes the same rng_seed / tint as the v4
    # emit_building_roofs(base_seed=fx.seed) call below.
    ctx = _Ctx(level=_Level(width=width, height=height), seed=fx.seed)
    builder = FloorIRBuilder(ctx)  # type: ignore[arg-type]

    shape_map = {
        "rect": RectShape(),
        "octagon": OctagonShape(),
        "circle": CircleShape(),
    }
    shape_obj = shape_map[fx.shape]
    rx, ry, rw, rh = fx.rect
    rect = Rect(rx, ry, rw, rh)
    building = _Building(base_shape=shape_obj, base_rect=rect)

    emit_site_region(builder, (0, 0, width, height))
    emit_building_regions(builder, [building])
    emit_building_roofs(builder, [building], base_seed=fx.seed)
    return builder.finish()


def _render_synthetic_fixture(
    fx: SyntheticRoofFixture,
) -> tuple[bytes, bytes, str]:
    """Build the synthetic IR and return (nir, reference_png, structural)."""
    import nhc_render

    from nhc.rendering.ir.structural import dump_structural

    nir = _build_synthetic_buf(fx)
    reference_png = bytes(nhc_render.ir_to_png_v5(nir, 1.0, None))
    structural = dump_structural(nir)
    return nir, reference_png, structural


def _write_synthetic_fixture(
    fx: SyntheticRoofFixture, root: Path, *, regen_reference: bool,
) -> None:
    nir, reference_png, structural = _render_synthetic_fixture(fx)
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.nir").write_bytes(nir)
    (out / "structural.json").write_text(structural)
    reference_path = out / "reference.png"
    if regen_reference or not reference_path.exists():
        reference_path.write_bytes(reference_png)


def _check_synthetic_fixture(
    fx: SyntheticRoofFixture, root: Path,
) -> list[str]:
    nir, reference_png, structural = _render_synthetic_fixture(fx)
    out = root / fx.descriptor
    drifts: list[str] = []
    nir_path = out / "floor.nir"
    if not nir_path.exists():
        drifts.append(f"{fx.descriptor}: floor.nir missing")
    elif nir_path.read_bytes() != nir:
        drifts.append(f"{fx.descriptor}: floor.nir drift")
    s_path = out / "structural.json"
    if not s_path.exists():
        drifts.append(f"{fx.descriptor}: structural.json missing")
    elif s_path.read_text() != structural:
        drifts.append(f"{fx.descriptor}: structural.json drift")
    r_path = out / "reference.png"
    if not r_path.exists():
        drifts.append(f"{fx.descriptor}: reference.png missing")
    elif r_path.read_bytes() != reference_png:
        drifts.append(f"{fx.descriptor}: reference.png drift")
    return drifts


# ── Synthetic enclosure regen (Phase 8.2c) ─────────────────────


def _build_synthetic_enclosure_buf(fx: SyntheticEnclosureFixture) -> bytes:
    """Hand-build a FloorIR buf with one Site region + an enclosure ExteriorWallOp."""
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    from nhc.rendering.ir._fb.WallStyle import WallStyle
    from nhc.rendering.ir_emitter import (
        FloorIRBuilder, emit_site_enclosure, emit_site_region,
    )

    @dataclasses.dataclass
    class _Level:
        width: int
        height: int

    @dataclasses.dataclass
    class _Ctx:
        level: _Level
        seed: int = 0
        theme: str = "dungeon"
        floor_kind: str = "surface"
        shadows_enabled: bool = True
        hatching_enabled: bool = True
        atmospherics_enabled: bool = True
        macabre_detail: bool = False
        vegetation_enabled: bool = True
        interior_finish: str = ""

    width, height = fx.canvas_tiles
    level = _Level(width=width, height=height)
    # ctx.seed mirrors fx.seed so the v5 emit_strokes' enclosure
    # branch (which reads builder.ctx.seed for the rng_seed)
    # produces the same rng_seed as emit_site_enclosure(
    # base_seed=fx.seed) below.
    builder = FloorIRBuilder(_Ctx(level=level, seed=fx.seed))  # type: ignore[arg-type]

    style_map = {
        "palisade": WallStyle.Palisade,
        "fortification": WallStyle.FortificationMerlon,
    }
    corner_map = {
        "merlon": CornerStyle.Merlon,
        "diamond": CornerStyle.Diamond,
        "tower": CornerStyle.Tower,
    }

    # Phase 4.3a-tail: stub a Site so the v5 emit_strokes' enclosure
    # branch sees the (kind, polygon, gates, corner_style) needed to
    # synthesise the V5StrokeOp. The synthetic fixture's gates ride
    # in pre-projected (edge_idx, t_center, half_px) format —
    # emit_strokes detects them via the float-typed slots and bypasses
    # the (x, y, length_tiles) projection step.
    @dataclasses.dataclass
    class _StubEnclosure:
        kind: str
        polygon: list[tuple[int, int]]
        gates: list[tuple[int, float, float]]
        corner_style: int

    @dataclasses.dataclass
    class _StubSite:
        surface: object
        enclosure: object
        buildings: list = dataclasses.field(default_factory=list)

    builder.site = _StubSite(
        surface=level,
        enclosure=_StubEnclosure(
            kind=fx.style,
            polygon=list(fx.polygon_tiles),
            gates=list(fx.gates),
            corner_style=corner_map[fx.corner_style],
        ),
    )

    emit_site_region(builder, (0, 0, width, height))
    # ``emit_site_enclosure`` registers the Region(kind=Enclosure)
    # internally before emitting the ExteriorWallOp.
    emit_site_enclosure(
        builder,
        polygon_tiles=[(float(x), float(y)) for x, y in fx.polygon_tiles],
        wall_style=style_map[fx.style],
        gates=list(fx.gates),
        base_seed=fx.seed,
        corner_style=corner_map[fx.corner_style],
    )
    return builder.finish()


def _render_synthetic_enclosure_fixture(
    fx: SyntheticEnclosureFixture,
) -> tuple[bytes, bytes, str]:
    import nhc_render
    from nhc.rendering.ir.structural import dump_structural
    nir = _build_synthetic_enclosure_buf(fx)
    reference_png = bytes(nhc_render.ir_to_png_v5(nir, 1.0, None))
    structural = dump_structural(nir)
    return nir, reference_png, structural


def _write_synthetic_enclosure_fixture(
    fx: SyntheticEnclosureFixture, root: Path, *, regen_reference: bool,
) -> None:
    nir, reference_png, structural = (
        _render_synthetic_enclosure_fixture(fx)
    )
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.nir").write_bytes(nir)
    (out / "structural.json").write_text(structural)
    reference_path = out / "reference.png"
    if regen_reference or not reference_path.exists():
        reference_path.write_bytes(reference_png)


def _check_synthetic_enclosure_fixture(
    fx: SyntheticEnclosureFixture, root: Path,
) -> list[str]:
    nir, reference_png, structural = (
        _render_synthetic_enclosure_fixture(fx)
    )
    out = root / fx.descriptor
    drifts: list[str] = []
    nir_path = out / "floor.nir"
    if not nir_path.exists():
        drifts.append(f"{fx.descriptor}: floor.nir missing")
    elif nir_path.read_bytes() != nir:
        drifts.append(f"{fx.descriptor}: floor.nir drift")
    s_path = out / "structural.json"
    if not s_path.exists():
        drifts.append(f"{fx.descriptor}: structural.json missing")
    elif s_path.read_text() != structural:
        drifts.append(f"{fx.descriptor}: structural.json drift")
    r_path = out / "reference.png"
    if not r_path.exists():
        drifts.append(f"{fx.descriptor}: reference.png missing")
    elif r_path.read_bytes() != reference_png:
        drifts.append(f"{fx.descriptor}: reference.png drift")
    return drifts


# ── Site gameplay regen (Phase 8.4) ────────────────────────────


def _build_site(fx: SiteFixture):
    """Assemble a real :class:`Site` for ``fx`` via ``assemble_site``."""
    import random
    from nhc.sites._site import assemble_site
    return assemble_site(
        fx.kind, f"{fx.kind}_seed{fx.seed}", random.Random(fx.seed),
    )


def _render_site_fixture(fx: SiteFixture) -> tuple[bytes, bytes, str]:
    """Build the site IR + reference PNG + structural snapshot.

    ``floor.nir`` packs the Site / Building regions, RoofOps, and
    EnclosureOp on top of the regular gameplay stages. Reference is
    the canonical tiny-skia render. Floor.svg / per-layer snapshots
    aren't committed for site fixtures: the IR-driven SVG path
    ships in 8.4 but the legacy ``render_site_surface_svg`` is the
    SVG production source until Phase 10.3 retires it.
    """
    import nhc_render
    from nhc.rendering.ir.structural import dump_structural
    from nhc.rendering.ir_emitter import build_floor_ir

    site = _build_site(fx)
    nir = bytes(build_floor_ir(
        site.surface,
        seed=fx.seed,
        hatch_distance=2.0,
        vegetation=fx.vegetation,
        site=site,
    ))
    reference_png = bytes(nhc_render.ir_to_png_v5(nir, 1.0, None))
    structural = dump_structural(nir)
    return nir, reference_png, structural


def _write_site_fixture(
    fx: SiteFixture, root: Path, *, regen_reference: bool,
) -> None:
    nir, reference_png, structural = _render_site_fixture(fx)
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.nir").write_bytes(nir)
    (out / "structural.json").write_text(structural)
    reference_path = out / "reference.png"
    if regen_reference or not reference_path.exists():
        reference_path.write_bytes(reference_png)


def _check_site_fixture(fx: SiteFixture, root: Path) -> list[str]:
    nir, reference_png, structural = _render_site_fixture(fx)
    out = root / fx.descriptor
    drifts: list[str] = []
    nir_path = out / "floor.nir"
    if not nir_path.exists():
        drifts.append(f"{fx.descriptor}: floor.nir missing")
    elif nir_path.read_bytes() != nir:
        drifts.append(f"{fx.descriptor}: floor.nir drift")
    s_path = out / "structural.json"
    if not s_path.exists():
        drifts.append(f"{fx.descriptor}: structural.json missing")
    elif s_path.read_text() != structural:
        drifts.append(f"{fx.descriptor}: structural.json drift")
    r_path = out / "reference.png"
    if not r_path.exists():
        drifts.append(f"{fx.descriptor}: reference.png missing")
    elif r_path.read_bytes() != reference_png:
        drifts.append(f"{fx.descriptor}: reference.png drift")
    return drifts


# ── Building gameplay regen (Phase 8.5) ────────────────────────


def _build_building_inputs(
    fx: BuildingFixture,
):
    """Return ``(site, level)`` for a BuildingFixture descriptor."""
    import random
    from nhc.sites._site import assemble_site
    site = assemble_site(
        fx.site_kind, f"{fx.site_kind}_seed{fx.seed}",
        random.Random(fx.seed),
    )
    building = site.buildings[fx.building_index]
    level = building.floors[fx.floor_index]
    return site, level


def _render_building_fixture(
    fx: BuildingFixture,
) -> tuple[bytes, bytes, str]:
    """Build the building-floor IR + reference PNG + structural."""
    import nhc_render
    from nhc.rendering.ir.structural import dump_structural
    from nhc.rendering.ir_emitter import build_floor_ir

    site, level = _build_building_inputs(fx)
    nir = bytes(build_floor_ir(
        level,
        seed=fx.seed,
        hatch_distance=2.0,
        site=site,
    ))
    reference_png = bytes(nhc_render.ir_to_png_v5(nir, 1.0, None))
    structural = dump_structural(nir)
    return nir, reference_png, structural


def _write_building_fixture(
    fx: BuildingFixture, root: Path, *, regen_reference: bool,
) -> None:
    nir, reference_png, structural = _render_building_fixture(fx)
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.nir").write_bytes(nir)
    (out / "structural.json").write_text(structural)
    reference_path = out / "reference.png"
    if regen_reference or not reference_path.exists():
        reference_path.write_bytes(reference_png)


def _check_building_fixture(fx: BuildingFixture, root: Path) -> list[str]:
    nir, reference_png, structural = _render_building_fixture(fx)
    out = root / fx.descriptor
    drifts: list[str] = []
    nir_path = out / "floor.nir"
    if not nir_path.exists():
        drifts.append(f"{fx.descriptor}: floor.nir missing")
    elif nir_path.read_bytes() != nir:
        drifts.append(f"{fx.descriptor}: floor.nir drift")
    s_path = out / "structural.json"
    if not s_path.exists():
        drifts.append(f"{fx.descriptor}: structural.json missing")
    elif s_path.read_text() != structural:
        drifts.append(f"{fx.descriptor}: structural.json drift")
    r_path = out / "reference.png"
    if not r_path.exists():
        drifts.append(f"{fx.descriptor}: reference.png missing")
    elif r_path.read_bytes() != reference_png:
        drifts.append(f"{fx.descriptor}: reference.png drift")
    return drifts


# ── Synthetic Building wall regen (Phase 8.3c) ─────────────────


def _build_synthetic_building_wall_buf(
    fx: SyntheticBuildingWallFixture,
) -> bytes:
    """Hand-build a Building IR with one Building region + the
    matching exterior + interior wall ops."""
    from nhc.dungeon.model import (
        CircleShape, OctagonShape, Rect, RectShape,
    )
    from nhc.rendering.ir_emitter import (
        FloorIRBuilder, emit_building_regions, emit_building_walls,
    )

    @dataclasses.dataclass
    class _Level:
        width: int
        height: int
        interior_edges: list[tuple[int, int, str]]
        building_id: str = "b0"

        def tile_at(self, x, y):
            return None  # no door-suppression in synthetic fixtures

    @dataclasses.dataclass
    class _Ctx:
        level: _Level
        seed: int = 0
        theme: str = "dungeon"
        floor_kind: str = "building"
        shadows_enabled: bool = True
        hatching_enabled: bool = True
        atmospherics_enabled: bool = True
        macabre_detail: bool = False
        vegetation_enabled: bool = True
        interior_finish: str = ""

    @dataclasses.dataclass
    class _Building:
        id: str
        base_shape: object
        base_rect: Rect
        wall_material: str
        interior_wall_material: str

    @dataclasses.dataclass
    class _StubSite:
        surface: object
        buildings: list
        enclosure: object = None

    width, height = fx.canvas_tiles
    level = _Level(
        width=width, height=height,
        interior_edges=list(fx.interior_edges),
    )
    # ctx.seed mirrors fx.seed so the v5 emit_strokes' building-
    # floor branch (which reads builder.ctx.seed for the rng_seed)
    # produces the same rng_seed as emit_building_walls(
    # base_seed=fx.seed) below.
    builder = FloorIRBuilder(_Ctx(level=level, seed=fx.seed))  # type: ignore[arg-type]
    shape_map = {
        "rect": RectShape(),
        "octagon": OctagonShape(),
        "circle": CircleShape(),
    }
    rx, ry, rw, rh = fx.rect
    b = _Building(
        id="b0",
        base_shape=shape_map[fx.shape],
        base_rect=Rect(rx, ry, rw, rh),
        wall_material=fx.wall_material,
        interior_wall_material=fx.interior_wall_material,
    )
    # Phase 4.3a-tail: stub a Site so the v5 emit_strokes' building-
    # floor branch resolves level.building_id → site.buildings[0]
    # and ships the V5StrokeOps. surface is set to a separate
    # sentinel so the enclosure branch is skipped.
    builder.site = _StubSite(surface=object(), buildings=[b])
    emit_building_regions(builder, [b])
    emit_building_walls(
        builder, b, level, base_seed=fx.seed, building_index=0,
    )
    return builder.finish()


def _render_synthetic_building_wall_fixture(
    fx: SyntheticBuildingWallFixture,
) -> tuple[bytes, bytes, str]:
    import nhc_render
    from nhc.rendering.ir.structural import dump_structural
    nir = _build_synthetic_building_wall_buf(fx)
    reference_png = bytes(nhc_render.ir_to_png_v5(nir, 1.0, None))
    structural = dump_structural(nir)
    return nir, reference_png, structural


def _write_synthetic_building_wall_fixture(
    fx: SyntheticBuildingWallFixture, root: Path, *, regen_reference: bool,
) -> None:
    nir, reference_png, structural = (
        _render_synthetic_building_wall_fixture(fx)
    )
    out = root / fx.descriptor
    out.mkdir(parents=True, exist_ok=True)
    (out / "floor.nir").write_bytes(nir)
    (out / "structural.json").write_text(structural)
    reference_path = out / "reference.png"
    if regen_reference or not reference_path.exists():
        reference_path.write_bytes(reference_png)


def _check_synthetic_building_wall_fixture(
    fx: SyntheticBuildingWallFixture, root: Path,
) -> list[str]:
    nir, reference_png, structural = (
        _render_synthetic_building_wall_fixture(fx)
    )
    out = root / fx.descriptor
    drifts: list[str] = []
    nir_path = out / "floor.nir"
    if not nir_path.exists():
        drifts.append(f"{fx.descriptor}: floor.nir missing")
    elif nir_path.read_bytes() != nir:
        drifts.append(f"{fx.descriptor}: floor.nir drift")
    s_path = out / "structural.json"
    if not s_path.exists():
        drifts.append(f"{fx.descriptor}: structural.json missing")
    elif s_path.read_text() != structural:
        drifts.append(f"{fx.descriptor}: structural.json drift")
    r_path = out / "reference.png"
    if not r_path.exists():
        drifts.append(f"{fx.descriptor}: reference.png missing")
    elif r_path.read_bytes() != reference_png:
        drifts.append(f"{fx.descriptor}: reference.png drift")
    return drifts


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
    (out / "floor.nir").write_bytes(rendered.nir)
    (out / "floor.json").write_text(rendered.js)
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
        ("floor.json", rendered.js),
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
        sites = [
            fx for fx in _SITE_FIXTURES
            if args.filter in fx.descriptor
        ]
        buildings = [
            fx for fx in _BUILDING_FIXTURES
            if args.filter in fx.descriptor
        ]
        synthetic_roofs = [
            fx for fx in _SYNTHETIC_ROOF_FIXTURES
            if args.filter in fx.descriptor
        ]
        synthetic_encs = [
            fx for fx in _SYNTHETIC_ENCLOSURE_FIXTURES
            if args.filter in fx.descriptor
        ]
        synthetic_walls = [
            fx for fx in _SYNTHETIC_BUILDING_WALL_FIXTURES
            if args.filter in fx.descriptor
        ]
    else:
        selected = list(_FIXTURES)
        sites = list(_SITE_FIXTURES)
        buildings = list(_BUILDING_FIXTURES)
        synthetic_roofs = list(_SYNTHETIC_ROOF_FIXTURES)
        synthetic_encs = list(_SYNTHETIC_ENCLOSURE_FIXTURES)
        synthetic_walls = list(_SYNTHETIC_BUILDING_WALL_FIXTURES)

    if not (
        selected or sites or buildings or synthetic_roofs
        or synthetic_encs or synthetic_walls
    ):
        print("no fixtures matched filter", file=sys.stderr)
        return 2

    if args.check:
        all_drifts: list[str] = []
        for fx in selected:
            all_drifts.extend(_check_fixture(fx, root))
        for site_fx in sites:
            all_drifts.extend(_check_site_fixture(site_fx, root))
        for bfx in buildings:
            all_drifts.extend(_check_building_fixture(bfx, root))
        for sfx in synthetic_roofs:
            all_drifts.extend(_check_synthetic_fixture(sfx, root))
        for efx in synthetic_encs:
            all_drifts.extend(
                _check_synthetic_enclosure_fixture(efx, root)
            )
        for wfx in synthetic_walls:
            all_drifts.extend(
                _check_synthetic_building_wall_fixture(wfx, root)
            )
        if all_drifts:
            print("FIXTURE DRIFT — re-run without --check to update:",
                  file=sys.stderr)
            for line in all_drifts:
                print(f"  - {line}", file=sys.stderr)
            return 1
        total = (
            len(selected) + len(sites) + len(buildings)
            + len(synthetic_roofs) + len(synthetic_encs)
            + len(synthetic_walls)
        )
        print(f"ok ({total} fixtures match committed)")
        return 0

    for fx in selected:
        _write_fixture(fx, root, regen_reference=args.regen_reference)
        print(f"wrote {fx.descriptor}")
    for site_fx in sites:
        _write_site_fixture(
            site_fx, root, regen_reference=args.regen_reference,
        )
        print(f"wrote {site_fx.descriptor}")
    for bfx in buildings:
        _write_building_fixture(
            bfx, root, regen_reference=args.regen_reference,
        )
        print(f"wrote {bfx.descriptor}")
    for sfx in synthetic_roofs:
        _write_synthetic_fixture(
            sfx, root, regen_reference=args.regen_reference,
        )
        print(f"wrote {sfx.descriptor}")
    for efx in synthetic_encs:
        _write_synthetic_enclosure_fixture(
            efx, root, regen_reference=args.regen_reference,
        )
        print(f"wrote {efx.descriptor}")
    for wfx in synthetic_walls:
        _write_synthetic_building_wall_fixture(
            wfx, root, regen_reference=args.regen_reference,
        )
        print(f"wrote {wfx.descriptor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
