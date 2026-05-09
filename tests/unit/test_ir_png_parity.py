"""Cross-rasteriser parity gate for the IR pipeline.

Phase 4.2c of ``plans/nhc_pure_ir_v5_migration_plan.md`` flipped the
gate from the v4 op stream to v5: the tiny-skia drift gate uses
``ir_to_png_v5`` and the cross-rasteriser-agreement gate uses
``svg_to_png(ir_to_svg_v5(buf))``. Both v5 entry points share
``dispatch_v5_ops`` internally so the cross-rasteriser PSNR floor
jumped from the v4-era 17–35 dB ceiling to 60+ dB on every fixture.

The two-layer contract from ``design/map_ir.md`` §9.4 still holds:

1. **IR-level structural validation** (rasteriser-independent).
   Op counts by type, region count, region polygon vertex count,
   and the per-layer element-count breakdown are snapshot-locked
   against ``tests/fixtures/floor_ir/<descriptor>/structural.json``.
   Catches emit-side regressions before any rasteriser runs.

2. **Pixel-level PSNR > 35 dB** vs canonical reference image. The
   reference is the tiny-skia PNG of the fixture's IR, frozen at
   ``tests/fixtures/floor_ir/<descriptor>/reference.png`` and only
   regenerated under ``--regen-reference``. Every rasteriser is
   measured against the same reference — tiny-skia itself (drift
   gate) and the v5 SVG path rendered through ``nhc_render.svg_to_png``
   (the cross-rasteriser-agreement gate). Phase 5 adds the WASM
   Canvas third side post-cut.
"""

from __future__ import annotations

import io
import json
import math
import re

from pathlib import Path

import numpy as np
import pytest

from PIL import Image

from nhc.rendering.ir.structural import compute_structural
from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


nhc_render = pytest.importorskip(
    "nhc_render",
    reason=(
        "nhc_render extension not installed — run `make rust-build` "
        "or `pip install -e crates/nhc-render` first"
    ),
)


def ir_to_svg(buf: bytes) -> str:
    """Rust ``nhc_render.ir_to_svg`` shim.

    Phase 4.2c of ``plans/nhc_pure_ir_v5_migration_plan.md`` flipped
    the parity gate from the v4 SVG path to v5. The shim keeps the
    callsite name stable so 4.3's mechanical V5* → canonical rename
    drops the ``_v5`` suffix without churning every test body.
    """
    return nhc_render.ir_to_svg(bytes(buf))


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "floor_ir"
)


# Default cross-rasteriser threshold per design/map_ir.md §9.4.
# Tightenable per-(rasteriser, fixture) pair if measurements show
# headroom; loosenable for WASM Canvas at Phase 5.6 (30 dB) where
# Cairo's anti-aliasing diverges from tiny-skia's.
#
# Phase 5 polish-ladder #9 — tightened from 35.0 → 50.0 once
# #5/#6 (per-style stone + wood layouts) shipped and the
# v5-vs-v4 PSNR drift settled. Live measurements at the cut:
# tiny-skia is inf across every fixture (the reference IS the
# tiny-skia output, so the gate is purely a wheel-drift sentinel),
# and resvg lands 64-84 dB on every fixture — lowest being
# ``synthetic_roof_circle`` at 64.08 dB. 50 dB leaves ~14 dB of
# safety margin on the tightest fixture; further tightening to
# the original ≥ 50 dB / inf split waits on the polish-ladder
# #3 sub-tile parity work (additive Anchor cx_off / cy_off
# floats; flagged for user decision).
PSNR_THRESHOLD_DB: float = 50.0


# Per-fixture relaxations.
#
# Phase 4.2c flipped both rasteriser sides to the v5 entry points
# (``ir_to_png_v5`` and ``ir_to_svg_v5``), which share
# ``dispatch_v5_ops`` internally and only differ in the concrete
# Painter (SkiaPainter vs SvgPainter). The cross-rasteriser PSNR
# jumped from the 17–35 dB v4 ceiling to 60+ dB on every measured
# fixture, so the v4-era overrides (notably the 17 dB seed99 cave
# override caused by Python ir_to_svg's GEOS buffer diverging from
# the Rust straight-skeleton) are stale and the maps reset to
# empty. Both maps stay defined so a future fixture-specific
# tightening can pin individually.
TINY_SKIA_PSNR_OVERRIDES: dict[str, float] = {}

RESVG_PSNR_OVERRIDES: dict[str, float] = {}


def _tiny_skia_threshold(descriptor: str) -> float:
    return TINY_SKIA_PSNR_OVERRIDES.get(descriptor, PSNR_THRESHOLD_DB)


def _resvg_threshold(descriptor: str) -> float:
    return RESVG_PSNR_OVERRIDES.get(descriptor, PSNR_THRESHOLD_DB)


def _decode(png_bytes: bytes) -> np.ndarray:
    """PNG bytes → (H, W, 4) RGBA array."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return np.asarray(img, dtype=np.uint8)


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    """Peak Signal-to-Noise Ratio in dB across all RGBA channels.

    Returns ``+inf`` when the inputs decode to identical pixmaps —
    the expected case for the tiny-skia self-PSNR drift gate.
    """
    assert a.shape == b.shape, f"shape mismatch: {a.shape} vs {b.shape}"
    diff = a.astype(np.float64) - b.astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse == 0.0:
        return math.inf
    return 20.0 * math.log10(255.0 / math.sqrt(mse))


@pytest.fixture(scope="module", params=all_descriptors())
def emitted(request):
    """Build each starter-fixture level once per module."""
    from nhc.rendering.ir_emitter import build_floor_ir

    inputs = descriptor_inputs(request.param)
    buf = build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )
    return inputs, bytes(buf)


# ── Layer 1: IR-level structural validation ─────────────────────


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_ir_structural_invariants(descriptor: str) -> None:
    """Op / region / per-layer element counts match the snapshot.

    Reads the committed ``floor.nir`` (rather than re-emitting via
    ``build_floor_ir``) so this test stays rasteriser-independent
    and bisects cleanly to either the emitter (``floor.nir``
    drifted) or the snapshot (``structural.json`` is stale). Re-run
    ``python -m tests.samples.regenerate_fixtures`` if the drift
    is intentional.
    """
    fixture = _FIXTURE_ROOT / descriptor
    nir = (fixture / "floor.nir").read_bytes()
    expected = json.loads((fixture / "structural.json").read_text())
    actual = compute_structural(nir)
    assert actual == expected, (
        f"{descriptor}: structural drift\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}\n"
        f"  actual:   {json.dumps(actual, sort_keys=True)}"
    )


# ── Layer 2: pixel-level PSNR vs canonical reference ────────────


def test_tiny_skia_psnr_against_reference(emitted) -> None:
    """tiny-skia PNG output: PSNR > 35 dB vs ``reference.png``.

    The reference *is* the tiny-skia output frozen at fixture
    commit time, so this is the drift gate: a rasteriser change
    that shifts pixels surfaces as a PSNR drop unless the commit
    explicitly regenerates the reference under
    ``--regen-reference``.
    """
    inputs, buf = emitted
    actual = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    reference = (
        _FIXTURE_ROOT / inputs.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    threshold = _tiny_skia_threshold(inputs.descriptor)
    assert db >= threshold, (
        f"{inputs.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {threshold:.1f} dB) — re-run with "
        f"`--regen-reference` if intentional"
    )


def test_resvg_of_ir_svg_psnr_against_reference(emitted) -> None:
    """``nhc_render.svg_to_png(ir_to_svg(buf))``: PSNR > 35 dB vs reference.

    The cross-rasteriser-agreement gate. PSNR drift here means
    the IR → SVG path and the IR → PNG path disagree on what the
    fixture should look like; bisects into either the SVG handler
    layer or the matching tiny-skia primitive.
    """
    inputs, buf = emitted
    svg = ir_to_svg(buf)
    actual = bytes(nhc_render.svg_to_png(svg))
    reference = (
        _FIXTURE_ROOT / inputs.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    threshold = _resvg_threshold(inputs.descriptor)
    assert db >= threshold, (
        f"{inputs.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {threshold:.1f} dB)"
    )


# ── Layer 3: SVG structural sanity (Phase 2.21) ─────────────────


# Background rectangle emitted by the Rust SvgPainter for resvg
# parity. Phase 2.19 added this so the resvg backend lands the same
# canvas-clear background that tiny-skia gets for free; the literal
# fragment is load-bearing for the cross-rasteriser PSNR gate.
_SVG_BG_RECT: str = (
    '<rect width="100%" height="100%" fill="#F5EDE0"/>'
)


def _svg_structural_assertions(descriptor: str, svg: str) -> None:
    """Cheap envelope-shape checks shared by every fixture flavour.

    Replaces the byte-equal ``floor.svg`` baseline that Phase 2.19
    deprecated: PSNR covers the rasterised contract, structural
    sanity covers "is this even an SVG document?". Catches truncated
    output, runaway nesting, dropped backgrounds, and similar
    envelope-level breakage that would otherwise sneak past PSNR
    when the failure mode is a fully-blank or fully-broken document.
    """
    assert svg.startswith("<?xml") or svg.startswith("<svg"), (
        f"{descriptor}: SVG must start with <?xml or <svg, "
        f"got {svg[:32]!r}"
    )
    open_svg = len(re.findall(r"<svg(?:\s|>)", svg))
    close_svg = svg.count("</svg>")
    assert open_svg == 1 and close_svg == 1, (
        f"{descriptor}: expected exactly one <svg> open and one "
        f"</svg> close, got {open_svg} / {close_svg}"
    )
    assert "viewBox=" in svg, (
        f"{descriptor}: SVG missing viewBox attribute"
    )
    assert _SVG_BG_RECT in svg, (
        f"{descriptor}: SVG missing background rect "
        f"({_SVG_BG_RECT!r}) — Phase 2.19 added this for resvg "
        f"parity; dropping it breaks the cross-rasteriser gate"
    )
    g_open = len(re.findall(r"<g(?:\s|>)", svg))
    g_close = svg.count("</g>")
    assert g_open == g_close, (
        f"{descriptor}: <g> envelope imbalance "
        f"({g_open} open vs {g_close} close)"
    )


def test_ir_svg_structural_sanity(emitted) -> None:
    """SVG envelope shape + background + balanced groups.

    Phase 2.21 retires the byte-equal ``floor.svg`` baseline; this
    test plus the PSNR gates above replace it. PSNR catches
    rasterised-pixel drift, this catches structural breakage —
    truncated output, missing background, runaway/dropped
    ``<g>`` nesting, etc.
    """
    inputs, buf = emitted
    svg = ir_to_svg(buf)
    _svg_structural_assertions(inputs.descriptor, svg)


# ── Synthetic-IR roof gate (Phase 8.1c.2) ──────────────────────


# Tighter than the cross-rasteriser default (50 dB) per the plan:
# synthetic IRs paint exactly one primitive on a clean background,
# so any per-pixel divergence is structural rather than absorbed
# in compositing noise. Phase 5 polish-ladder #9 raised this from
# 40.0 → 55.0 alongside the default bump 35.0 → 50.0; live
# measurements show the lowest synthetic-rasteriser PSNR is
# ``synthetic_roof_circle`` at 64.08 dB (curved-edge antialiasing
# divergence between resvg and tiny-skia), giving the new
# threshold ~9 dB of safety margin on the tightest fixture.
ROOF_PSNR_THRESHOLD_DB: float = 55.0


_SYNTHETIC_ROOF_DESCRIPTORS: tuple[str, ...] = (
    "synthetic_roof_square_pyramid",
    "synthetic_roof_wide_gable",
    "synthetic_roof_octagon",
    "synthetic_roof_circle",
)


@pytest.fixture(scope="module", params=_SYNTHETIC_ROOF_DESCRIPTORS)
def synthetic_roof_buf(request):
    """Hand-built FloorIR buf with one Building region + one RoofOp."""
    from tests.samples.regenerate_fixtures import (
        _SYNTHETIC_ROOF_FIXTURES, _build_synthetic_buf,
    )
    fx = next(
        f for f in _SYNTHETIC_ROOF_FIXTURES
        if f.descriptor == request.param
    )
    return fx, _build_synthetic_buf(fx)


def test_synthetic_roof_tiny_skia_psnr(synthetic_roof_buf) -> None:
    """tiny-skia output: PSNR > 40 dB vs the committed reference.

    The synthetic fixture's reference.png IS the tiny-skia output
    of the same IR — committed once via ``--regen-reference``. A
    drift here means the Rust roof handler shifted its shingle
    layout, palette, or geometry from the Phase 8.1c.2 baseline.
    """
    fx, buf = synthetic_roof_buf
    actual = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= ROOF_PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {ROOF_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_synthetic_roof_resvg_psnr(synthetic_roof_buf) -> None:
    """``nhc_render.svg_to_png(ir_to_svg(buf))``: PSNR > 40 dB vs reference.

    The cross-rasteriser-agreement gate for the roof primitive.
    The Python ``_draw_roof_from_ir`` (SVG path) and the Rust
    ``transform/png/roof.rs`` (tiny-skia path) walk the same
    splitmix64 stream seeded with ``RoofOp.rng_seed``; any drift
    in constants, RNG, palette, or layout shows up as a PSNR drop
    here.
    """
    fx, buf = synthetic_roof_buf
    svg = ir_to_svg(buf)
    actual = bytes(nhc_render.svg_to_png(svg))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= ROOF_PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {ROOF_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_synthetic_roof_structural_invariants(synthetic_roof_buf) -> None:
    """Snapshot-lock op / region counts against committed structural.json.

    Pinned alongside the rasteriser PSNR gates so an emit-side
    regression (lost RoofOp, missing Region, polygon shape drift)
    bisects independently of pixel-level concerns.
    """
    from nhc.rendering.ir.structural import compute_structural
    fx, buf = synthetic_roof_buf
    expected = json.loads(
        (_FIXTURE_ROOT / fx.descriptor / "structural.json").read_text()
    )
    actual = compute_structural(buf)
    assert actual == expected, (
        f"{fx.descriptor}: structural drift\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}\n"
        f"  actual:   {json.dumps(actual, sort_keys=True)}"
    )


# ── Synthetic-IR enclosure gate (Phase 8.2c) ───────────────────


_SYNTHETIC_ENCLOSURE_DESCRIPTORS: tuple[str, ...] = (
    "synthetic_enclosure_palisade_rect",
    "synthetic_enclosure_palisade_gated",
    "synthetic_enclosure_fortification_merlon",
    "synthetic_enclosure_fortification_diamond_gated",
)


@pytest.fixture(scope="module", params=_SYNTHETIC_ENCLOSURE_DESCRIPTORS)
def synthetic_enclosure_buf(request):
    """Hand-built FloorIR buf with one Site region + one EnclosureOp."""
    from tests.samples.regenerate_fixtures import (
        _SYNTHETIC_ENCLOSURE_FIXTURES, _build_synthetic_enclosure_buf,
    )
    fx = next(
        f for f in _SYNTHETIC_ENCLOSURE_FIXTURES
        if f.descriptor == request.param
    )
    return fx, _build_synthetic_enclosure_buf(fx)


def test_synthetic_enclosure_tiny_skia_psnr(
    synthetic_enclosure_buf,
) -> None:
    """tiny-skia output: PSNR > 40 dB vs the committed reference.

    Drift gate for `transform/png/enclosure.rs`. The reference IS
    the tiny-skia output of the same IR — committed once via
    --regen-reference. A drift here means the Rust handler shifted
    palette / dimensions / RNG / shape from the 8.2c baseline.
    """
    fx, buf = synthetic_enclosure_buf
    actual = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= ROOF_PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {ROOF_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_synthetic_enclosure_resvg_psnr(synthetic_enclosure_buf) -> None:
    """``nhc_render.svg_to_png(ir_to_svg(buf))``: PSNR > 40 dB vs reference.

    Cross-rasteriser-agreement gate for the enclosure primitive.
    Both Python `_draw_enclosure_from_ir` and Rust
    `transform/png/enclosure.rs` walk splitmix64 streams seeded
    `rng_seed + edge_idx` per palisade edge; any drift in
    constants, RNG, palette, gate-cut math, or corner geometry
    surfaces as a PSNR drop here.
    """
    fx, buf = synthetic_enclosure_buf
    svg = ir_to_svg(buf)
    actual = bytes(nhc_render.svg_to_png(svg))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= ROOF_PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {ROOF_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_synthetic_enclosure_structural_invariants(
    synthetic_enclosure_buf,
) -> None:
    """Snapshot-lock the structural shape against structural.json."""
    from nhc.rendering.ir.structural import compute_structural
    fx, buf = synthetic_enclosure_buf
    expected = json.loads(
        (_FIXTURE_ROOT / fx.descriptor / "structural.json").read_text()
    )
    actual = compute_structural(buf)
    assert actual == expected, (
        f"{fx.descriptor}: structural drift\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}\n"
        f"  actual:   {json.dumps(actual, sort_keys=True)}"
    )


# ── Synthetic-IR Building wall gate (Phase 8.3c) ───────────────


_SYNTHETIC_BUILDING_WALL_DESCRIPTORS: tuple[str, ...] = (
    "synthetic_building_wall_brick_rect",
    "synthetic_building_wall_stone_octagon",
    "synthetic_building_wall_brick_circle",
    "synthetic_building_wall_brick_with_interior",
)


@pytest.fixture(
    scope="module", params=_SYNTHETIC_BUILDING_WALL_DESCRIPTORS,
)
def synthetic_building_wall_buf(request):
    """Hand-built FloorIR with one Building region + the matching
    BuildingExteriorWallOp + BuildingInteriorWallOp."""
    from tests.samples.regenerate_fixtures import (
        _SYNTHETIC_BUILDING_WALL_FIXTURES,
        _build_synthetic_building_wall_buf,
    )
    fx = next(
        f for f in _SYNTHETIC_BUILDING_WALL_FIXTURES
        if f.descriptor == request.param
    )
    return fx, _build_synthetic_building_wall_buf(fx)


def test_synthetic_building_wall_tiny_skia_psnr(
    synthetic_building_wall_buf,
) -> None:
    """tiny-skia output: PSNR > 40 dB vs the committed reference."""
    fx, buf = synthetic_building_wall_buf
    actual = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= ROOF_PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {ROOF_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_synthetic_building_wall_resvg_psnr(
    synthetic_building_wall_buf,
) -> None:
    """``nhc_render.svg_to_png(ir_to_svg(buf))``: PSNR > 40 dB vs reference.

    Cross-rasteriser-agreement gate. Both Python
    `_draw_building_exterior_wall_from_ir` and Rust
    `transform/png/building_exterior_wall.rs` walk splitmix64
    seeded `rng_seed + edge_idx`; the rounded-rect path uses the
    same 0.5523 cubic-bezier control distance both ways.
    """
    fx, buf = synthetic_building_wall_buf
    svg = ir_to_svg(buf)
    actual = bytes(nhc_render.svg_to_png(svg))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= ROOF_PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {ROOF_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_synthetic_building_wall_structural_invariants(
    synthetic_building_wall_buf,
) -> None:
    from nhc.rendering.ir.structural import compute_structural
    fx, buf = synthetic_building_wall_buf
    expected = json.loads(
        (_FIXTURE_ROOT / fx.descriptor / "structural.json").read_text()
    )
    actual = compute_structural(buf)
    assert actual == expected, (
        f"{fx.descriptor}: structural drift\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}\n"
        f"  actual:   {json.dumps(actual, sort_keys=True)}"
    )


# ── Gameplay site-surface gate (Phase 8.4) ──────────────────────


_SITE_DESCRIPTORS: tuple[str, ...] = (
    "seed7_town_surface",
)


@pytest.fixture(scope="module", params=_SITE_DESCRIPTORS)
def site_buf(request):
    """Real :class:`Site` IR via ``assemble_site`` + the
    emit_site_overlays stage. Threads ``site=`` through
    ``build_floor_ir`` so RoofOps + EnclosureOp ship alongside
    every gameplay layer."""
    from tests.samples.regenerate_fixtures import (
        _SITE_FIXTURES, _build_site,
    )
    from nhc.rendering.ir_emitter import build_floor_ir
    fx = next(
        f for f in _SITE_FIXTURES if f.descriptor == request.param
    )
    site = _build_site(fx)
    buf = build_floor_ir(
        site.surface,
        seed=fx.seed,
        hatch_distance=2.0,
        vegetation=fx.vegetation,
        site=site,
    )
    return fx, bytes(buf)


def test_site_tiny_skia_psnr(site_buf) -> None:
    """tiny-skia output: PSNR > 35 dB vs the committed reference.

    The gameplay site fixture rasterises the full layer stack
    (gameplay shadows / hatching / floor / decorators) plus the
    Phase 8 overlays (RoofOps + EnclosureOp), so the cross-
    rasteriser threshold is the standard 35 dB rather than the
    40 dB synthetic-IR threshold (those isolate one primitive at a
    time on a clean background).
    """
    fx, buf = site_buf
    actual = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_site_resvg_psnr(site_buf) -> None:
    """``nhc_render.svg_to_png(ir_to_svg(buf))``: PSNR > 35 dB vs reference.

    The cross-rasteriser-agreement gate on a real site IR. PSNR
    drift here means the SVG side and the PNG side disagree on
    layout for one of the gameplay layers OR for the site overlays
    — bisects to the relevant op kind.
    """
    fx, buf = site_buf
    svg = ir_to_svg(buf)
    actual = bytes(nhc_render.svg_to_png(svg))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_site_structural_invariants(site_buf) -> None:
    from nhc.rendering.ir.structural import compute_structural
    fx, buf = site_buf
    expected = json.loads(
        (_FIXTURE_ROOT / fx.descriptor / "structural.json").read_text()
    )
    actual = compute_structural(buf)
    assert actual == expected, (
        f"{fx.descriptor}: structural drift\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}\n"
        f"  actual:   {json.dumps(actual, sort_keys=True)}"
    )


# ── Gameplay building-floor gate (Phase 8.5) ───────────────────


_BUILDING_DESCRIPTORS: tuple[str, ...] = (
    "seed7_brick_building_floor0",
)


@pytest.fixture(scope="module", params=_BUILDING_DESCRIPTORS)
def building_buf(request):
    """Real Building floor IR via ``assemble_site`` + the
    emit_building_overlays stage. ``site=`` flows through
    ``build_floor_ir`` so BuildingExteriorWallOp +
    BuildingInteriorWallOp ship alongside every gameplay layer."""
    from tests.samples.regenerate_fixtures import (
        _BUILDING_FIXTURES, _build_building_inputs,
    )
    from nhc.rendering.ir_emitter import build_floor_ir
    fx = next(
        f for f in _BUILDING_FIXTURES if f.descriptor == request.param
    )
    site, level = _build_building_inputs(fx)
    buf = build_floor_ir(
        level, seed=fx.seed, hatch_distance=2.0, site=site,
    )
    return fx, bytes(buf)


def test_building_tiny_skia_psnr(building_buf) -> None:
    """tiny-skia output: PSNR > 35 dB vs the committed reference."""
    fx, buf = building_buf
    actual = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_building_resvg_psnr(building_buf) -> None:
    """``nhc_render.svg_to_png(ir_to_svg(buf))``: PSNR > 35 dB vs reference."""
    fx, buf = building_buf
    svg = ir_to_svg(buf)
    actual = bytes(nhc_render.svg_to_png(svg))
    reference = (
        _FIXTURE_ROOT / fx.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= PSNR_THRESHOLD_DB, (
        f"{fx.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_building_structural_invariants(building_buf) -> None:
    from nhc.rendering.ir.structural import compute_structural
    fx, buf = building_buf
    expected = json.loads(
        (_FIXTURE_ROOT / fx.descriptor / "structural.json").read_text()
    )
    actual = compute_structural(buf)
    assert actual == expected, (
        f"{fx.descriptor}: structural drift\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}\n"
        f"  actual:   {json.dumps(actual, sort_keys=True)}"
    )
