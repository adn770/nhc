"""Per-layer PNG parity gate against ``resvg-py``.

The Phase 5 contract is that ``nhc_render.ir_to_png(buf, layer=X)``
produces a pixmap within ≤ 0.5 % of the reference rendering
``resvg-py`` produces from ``layer_to_svg_full(buf, layer=X)``.
The harness is parametrised over (descriptor × layer); each
per-primitive 5.2 / 5.3 / 5.4 commit removes its layer from
``XFAIL_LAYERS`` once its handler ships.

Phase 5.1.1 lands the harness with all nine renderable layers
in ``XFAIL_LAYERS`` (the BG-only output diverges from the
resvg-py baseline whenever the layer carries content). The
strict-XFAIL discipline catches the unexpected-pass case for
fixtures whose layer is empty — those (descriptor × layer) pairs
get the ``EMPTY_LAYER_FIXTURES`` exemption so the strict gate
stays green throughout the build-out.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from PIL import Image

from nhc.rendering.ir_to_svg import ir_to_svg, layer_to_svg_full

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
    reason="resvg-py is the parity baseline; required for Phase 5",
)


# Layers in `_LAYER_OPS` order — matches `_LAYER_ORDER` in
# `ir_to_svg.py`. Per-primitive commits drop their layer from
# ``XFAIL_LAYERS`` once the parity gate goes green.
LAYER_NAMES: tuple[str, ...] = (
    "shadows",
    "hatching",
    "walls_and_floors",
    "terrain_tints",
    "floor_grid",
    "floor_detail",
    "thematic_detail",
    "terrain_detail",
    "stairs",
    "surface_features",
)


# Layers without a tiny-skia handler yet — diff is expected to
# exceed the 0.5 % gate. Per-primitive commits drop entries as
# their handler lands. Tracked at (descriptor, layer) granularity
# because some primitives ship in more than one commit (e.g.
# walls_and_floors lands rect/corridor branches in 5.2.2 and the
# cave + smooth-room SVG passthroughs in 5.5).
DESCRIPTORS = tuple(d for d in all_descriptors())

# Per-primitive shipping log:
#   5.2.1 — shadows (every fixture).
#   5.2.2 — walls_and_floors (rect dungeon only — the cave +
#           smooth-room + wall_extensions_d SVG passthroughs
#           wait for 5.5 to land).
#   5.2.3 — terrain_tints (every fixture).
#   5.2.4 — floor_grid (every fixture).
#   5.2.5 — stairs (every fixture).
#   5.3.1 — hatching (every fixture).
#   5.3.2 — floor_detail (every fixture).
#   5.3.3 — thematic_detail (every fixture).
#   5.5   — walls_and_floors smooth + cave + wall_extensions
#           passthroughs (seed7 octagon + seed99 cave); plus
#           the terrain_detail / surface_features passthroughs
#           via the new TerrainDetailOp + GenericProceduralOp
#           handlers.
#   5.10  — offscreen-buffer compositing + SVG attr inheritance
#           for `<g opacity>` wrappers + the multi-entry group
#           shape (open-tag / children / close-tag). Drops the
#           last (seed99, terrain_detail) XFAIL — the cave
#           fixture's dense grass cluster lands at ~0.013 % vs
#           the 0.5 % gate.
LANDED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    (descriptor, layer)
    for descriptor in DESCRIPTORS
    for layer in LAYER_NAMES
)

XFAIL_PAIRS: frozenset[tuple[str, str]] = frozenset()


# ≤ 0.5 % per the Phase 5 success criteria.
PARITY_THRESHOLD: float = 0.005

# Per-pixel tolerance for "pixels differ" — soaks up subpixel
# antialiasing variance between resvg and tiny-skia. A pixel
# counts as "different" when any RGBA channel differs by more
# than this many levels (out of 255).
CHANNEL_TOLERANCE: int = 8


def _decode(png_bytes: bytes) -> np.ndarray:
    """PNG bytes → (H, W, 4) RGBA array."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return np.asarray(img, dtype=np.int16)


def _diff_fraction(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of pixels where any channel differs by more than
    ``CHANNEL_TOLERANCE`` levels. The plan's "pixel-diff" metric.
    """
    assert a.shape == b.shape, f"shape mismatch: {a.shape} vs {b.shape}"
    delta = np.abs(a - b)
    differs = (delta > CHANNEL_TOLERANCE).any(axis=-1)
    return float(differs.mean())


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


@pytest.mark.parametrize("layer", LAYER_NAMES)
def test_layer_parity(emitted, layer: str, request) -> None:
    inputs, buf = emitted
    if (inputs.descriptor, layer) in XFAIL_PAIRS:
        request.applymarker(
            pytest.mark.xfail(
                strict=False,
                reason=(
                    f"{inputs.descriptor}/{layer} not yet ported to "
                    f"tiny-skia (Phase 5 per-primitive commit drops "
                    f"the marker)"
                ),
            )
        )
    actual = nhc_render.ir_to_png(buf, 1.0, layer)
    baseline_svg = layer_to_svg_full(buf, layer=layer)
    baseline = bytes(resvg_py.svg_to_bytes(svg_string=baseline_svg))
    diff = _diff_fraction(_decode(actual), _decode(baseline))
    assert diff <= PARITY_THRESHOLD, (
        f"{inputs.descriptor} / {layer}: {diff:.4%} differs "
        f"(threshold {PARITY_THRESHOLD:.2%})"
    )


# Whole-floor threshold sits a touch above the per-layer 0.5 %
# gate to absorb the natural accumulation of subpixel
# antialiasing variance across the stack. Phase 5.10 closed the
# SVG group-opacity / per-element-alpha gap that had kept this
# gate at 1.0 %; the residual variance comes from per-layer
# stroke / fill anti-alias differences (hatching at ~0.33 % and
# thematic_detail at ~0.29 % on seed7 alone, additive across
# the stack). Empirical fixture diffs at HEAD: seed42 ~0.41 %,
# seed7 ~0.62 %, seed99 ~0.23 %. 0.7 % keeps the headroom
# without admitting visual divergence.
WHOLE_FLOOR_THRESHOLD: float = 0.007


def test_whole_floor_parity(emitted) -> None:
    """Phase 5.7 — full ir_to_png output vs resvg-py rendering of
    the same buffer's full composition. Caps the per-layer gates
    at the floor level so a regression in any single layer
    bisects to the layer-specific test, while drift in the
    layer-stacking order surfaces only here.
    """
    inputs, buf = emitted
    actual = nhc_render.ir_to_png(buf, 1.0, None)
    baseline_svg = ir_to_svg(buf)
    baseline = bytes(resvg_py.svg_to_bytes(svg_string=baseline_svg))
    diff = _diff_fraction(_decode(actual), _decode(baseline))
    assert diff <= WHOLE_FLOOR_THRESHOLD, (
        f"{inputs.descriptor}: whole-floor diff {diff:.4%} "
        f"(threshold {WHOLE_FLOOR_THRESHOLD:.2%})"
    )
