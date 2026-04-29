"""Cross-rasteriser parity gate for the IR pipeline.

Phase 8.0 pre-step (per ``plans/nhc_ir_migration_plan.md``):
the harness pivots from the per-layer / whole-floor pixel-diff
regime that Phase 5 lived on to the two-layer parity contract
codified in ``design/map_ir.md`` §9.4:

1. **IR-level structural validation** (rasteriser-independent).
   Op counts by type, region count, region polygon vertex count,
   and the per-layer element-count breakdown
   (``<!-- layer.X: N elements -->`` markers from ``ir_to_svg``)
   are snapshot-locked against
   ``tests/fixtures/floor_ir/<descriptor>/structural.json``.
   Catches emit-side regressions before any rasteriser runs.

2. **Pixel-level PSNR > 35 dB** vs canonical reference image. The
   reference is the tiny-skia PNG of the fixture's IR, frozen at
   ``tests/fixtures/floor_ir/<descriptor>/reference.png`` and only
   regenerated under ``--regen-reference``. Every rasteriser is
   measured against the same reference — currently tiny-skia
   itself (drift gate) and ``ir_to_svg`` rendered through
   ``resvg-py`` (the cross-rasteriser-agreement gate). Phase 11
   adds the WASM Canvas third side.
"""

from __future__ import annotations

import io
import json
import math

from pathlib import Path

import numpy as np
import pytest

from PIL import Image

from nhc.rendering.ir.structural import compute_structural
from nhc.rendering.ir_to_svg import ir_to_svg

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
resvg_py = pytest.importorskip(
    "resvg_py",
    reason=(
        "resvg-py is the cross-rasteriser parity baseline; install "
        "with `.venv/bin/pip install -e .[dev]`"
    ),
)


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "floor_ir"
)


# Default cross-rasteriser threshold per design/map_ir.md §9.4.
# Tightenable per-(rasteriser, fixture) pair if measurements show
# headroom; loosenable for WASM Canvas at Phase 11 (~30 dB).
PSNR_THRESHOLD_DB: float = 35.0


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
    assert db >= PSNR_THRESHOLD_DB, (
        f"{inputs.descriptor}: tiny-skia PSNR {db:.2f} dB "
        f"(threshold {PSNR_THRESHOLD_DB:.1f} dB) — re-run with "
        f"`--regen-reference` if intentional"
    )


def test_resvg_of_ir_svg_psnr_against_reference(emitted) -> None:
    """``resvg-py(ir_to_svg(buf))``: PSNR > 35 dB vs reference.

    The cross-rasteriser-agreement gate. PSNR drift here means
    the IR → SVG path and the IR → PNG path disagree on what the
    fixture should look like; bisects into either the SVG handler
    layer or the matching tiny-skia primitive.
    """
    inputs, buf = emitted
    svg = ir_to_svg(buf)
    actual = bytes(resvg_py.svg_to_bytes(svg_string=svg))
    reference = (
        _FIXTURE_ROOT / inputs.descriptor / "reference.png"
    ).read_bytes()
    db = _psnr(_decode(actual), _decode(reference))
    assert db >= PSNR_THRESHOLD_DB, (
        f"{inputs.descriptor}: resvg-of-ir-svg PSNR {db:.2f} dB "
        f"(threshold {PSNR_THRESHOLD_DB:.1f} dB)"
    )
