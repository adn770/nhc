"""v5-vs-v4 pixel-PSNR cross-rasteriser parity gate.

Phase 3.1 of ``plans/nhc_pure_ir_v5_migration_plan.md``. For each
starter-fixture level, build the IR (which carries both the
canonical v4 ``ops`` / ``regions`` arrays and the additive v5
``v5_ops`` / ``v5_regions`` scaffold), render through both consumer
paths, and compare the resulting PNG pixel grids:

- v4 path: ``nhc_render.ir_to_png(buf, 1.0, None)`` walks
  ``ops[]`` through the v4 op handlers under ``transform/png/``.
- v5 path: ``nhc_render.ir_to_png_v5(buf, 1.0, None)`` walks
  ``v5_ops[]`` through the v5 op handlers under
  ``transform/png/v5/``.

The acceptance ladder follows the migration plan §3.1: the long-
term gate is PSNR ≥ 50 dB across all fixtures, lockable once the
deferred Phase 2 work (sub-pattern layouts in Wood / Stone, the 9
decorator-bit per-tile algorithms, the 4 per-treatment WallTreatment
algorithms, the 7 not-yet-lifted FixtureKinds, V5HatchOp +
V5RoofOp handlers) lands. Until then the gate runs at a relaxed
threshold (configurable via ``V5_PSNR_THRESHOLD_DB`` and the
per-fixture override map) so the test surfaces *which* fixtures
need which Phase 2 work without going red on the whole branch
mid-migration.

Each fixture's PSNR sits in :data:`V5_PSNR_OVERRIDES` so the next
deferred-work commit can tighten one fixture's threshold and
catch regressions on every other in one parametric run.
"""

from __future__ import annotations

import io
import math

from pathlib import Path

import numpy as np
import pytest

from PIL import Image

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


_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "floor_ir"


# Plan §3.1 long-term acceptance: PSNR ≥ 50 dB. The fallback
# default below is intentionally low — fixtures whose current PSNR
# is in the 12–16 dB range pin themselves through the per-fixture
# override map; the default catches "totally broken" v5 output
# (no PNG, all-magenta sentinel fills, etc.) without erroring out
# on the current Phase 2 mid-migration deficit.
V5_PSNR_THRESHOLD_DB: float = 10.0


# Per-fixture floor (dB). Set to the MEASURED PSNR at the latest
# tightening commit minus ~0.5 dB headroom so a real regression
# trips the gate, but a no-op rebuild stays green. Each Phase 2
# deferred-work commit (decorator bit, sub-pattern layout,
# WallTreatment algorithm, fixture lift) lifts one or more
# fixture's measured PSNR — bump the override here at the same
# time to pin the new floor.
#
# Current floors (measured at Phase 2.9 + V5HatchOp dispatch +
# v5_emit shadow / hatch translators):
V5_PSNR_OVERRIDES: dict[str, float] = {
    "seed42_rect_dungeon_dungeon": 17.1,
    "seed7_octagon_crypt_dungeon": 16.5,
    "seed99_cave_cave_cave": 19.0,
}


def _v5_threshold(descriptor: str) -> float:
    return V5_PSNR_OVERRIDES.get(descriptor, V5_PSNR_THRESHOLD_DB)


def _decode(png_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return np.asarray(img, dtype=np.uint8)


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
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


def test_v5_render_path_succeeds(emitted) -> None:
    """``ir_to_png_v5`` returns a valid PNG byte stream.

    The smoke gate: catches binding regressions, panics inside the
    v5 dispatch, and pixmap encoding failures separately from PSNR
    drift. PSNR-only failures can mask a totally-broken v5 path
    (zero-byte output still PSNRs at ~6 dB vs the reference).
    """
    _inputs, buf = emitted
    out = bytes(nhc_render.ir_to_png_v5(buf, 1.0, None))
    # PNG magic: 89 50 4E 47 0D 0A 1A 0A.
    assert out[:8] == b"\x89PNG\r\n\x1a\n", (
        f"v5 render did not emit a valid PNG (first 8 bytes: {out[:8]!r})"
    )


def test_v5_svg_render_path_succeeds(emitted) -> None:
    """``ir_to_svg_v5`` returns a well-formed SVG document.

    Phase 4.2a smoke gate for the new SVG entry point: catches
    binding regressions, panics inside the v5 dispatch, and SvgError
    surface failures separately from PSNR drift. The downstream
    cross-rasteriser PSNR gate (``svg_to_png(ir_to_svg_v5(buf))`` vs
    ``ir_to_png_v5(buf)``) lands at Phase 4.2c when
    ``test_ir_png_parity.py`` flips to v5; until then, this catches
    "totally broken" v5 SVG (empty string, missing envelope, parse
    error) at the binding boundary.
    """
    _inputs, buf = emitted
    svg = nhc_render.ir_to_svg_v5(buf, 1.0, None)
    assert svg.startswith("<?xml") or svg.startswith("<svg"), (
        f"v5 SVG did not emit valid envelope (first 32 bytes: {svg[:32]!r})"
    )
    assert svg.endswith("</svg>"), (
        f"v5 SVG missing closing tag (last 32 bytes: {svg[-32:]!r})"
    )
    # Real fixtures must paint at least one geometry element through
    # the SvgPainter — catches a silently-skipped op kind or a broken
    # Painter wiring inside dispatch_v5_ops.
    assert any(tag in svg for tag in (
        "<rect", "<path", "<polygon", "<polyline", "<circle", "<ellipse",
    )), "v5 SVG body has no geometry elements"


def test_v5_render_matches_v4_at_pixel_psnr(emitted) -> None:
    """``ir_to_png_v5(buf)`` ≈ ``ir_to_png(buf)`` at PSNR threshold.

    The cross-rasteriser-agreement gate. Drift here means the v5
    emit + render path diverges from the v4 reference rendering for
    this fixture. Bisects into either:

    - v5 emit (``nhc/rendering/v5_emit/``) — wrong op shape /
      missing op kind / wrong region resolution.
    - v5 op handler (``crates/nhc-render/src/transform/png/v5/``) —
      missing algorithm / wrong palette / wrong dispatch arm.
    - Painter trait — substance palette resolver picks the wrong
      colour for the (family, style, tone) tuple.
    """
    inputs, buf = emitted
    v4 = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    v5 = bytes(nhc_render.ir_to_png_v5(buf, 1.0, None))
    db = _psnr(_decode(v4), _decode(v5))
    threshold = _v5_threshold(inputs.descriptor)
    assert db >= threshold, (
        f"{inputs.descriptor}: v5-vs-v4 PSNR {db:.2f} dB "
        f"(threshold {threshold:.1f} dB)"
    )
