"""Structural invariants for the floor_detail layer.

Per §8 of ``plans/nhc_ir_migration_plan.md`` (locked 2026-04-28),
the floor_detail primitive ships under a relaxed parity gate (Q5
step 3) — the byte-equal-with-legacy contract is replaced with
these structural invariants plus a snapshot lock against the new
Rust output. The byte-equal whole-SVG fixture stays green by
re-baselining ``floor.svg`` in the bundle commit (3.e–3.h); this
file pins the layer-slice contract.

The invariants assert that the floor_detail layer is visually
well-formed regardless of the underlying RNG choice:

- Element counts within a sane range per fixture (catches
  catastrophic miscounts; not a precision test — the snapshot
  lock pins exact output).
- All coordinates inside the expected bounding box (no fragments
  flying off the canvas).
- No NaN or Inf in any coordinate (catches FP misuse in the
  Rust port's geometry path).
- Output parses as well-formed XML when wrapped in a root.
- Re-rendering the same buffer twice produces byte-equal output
  (catches RNG-seeding bugs that would let output drift
  between runs).

Note: the floor_detail layer carries three sub-streams today —
floor-detail proper (cracks / scratches / stones), thematic
detail (webs / bones / skulls — ports at step 4) and the
decorator pipeline (cobblestone / brick / etc. — ports at steps
5–12). The structural-invariants gate covers all three because
they all ride one ``random.Random(seed + 99)`` stream until step
3 splits floor-detail off; the RNG drift affects every sub-stream
even though step 3 only ports the painter for floor-detail
proper.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "floor_ir"
)


# Baseline element counts measured against the current Python
# output on 2026-04-28 (legacy shared-RNG path). The Rust port
# splits the RNG so exact counts shift; ±35 % is wide enough to
# absorb the RNG drift but tight enough to flag a port that emits
# zero or 100× too many fragments. The snapshot lock at sub-step
# 3.f pins the exact output; this range is a sanity check.
#
# Counts are pooled across all element kinds the layer emits
# (lines + ellipses + paths). Pooling avoids over-tightening on
# the per-kind splits, which shift differently when the
# floor-detail / thematic-detail RNGs separate.
_ELEMENT_BASELINES = {
    "seed42_rect_dungeon_dungeon": 403,   # 113 lines + 219 ellipses + 71 paths
    "seed7_octagon_crypt_dungeon": 977,   # 269 lines + 524 ellipses + 184 paths
    "seed99_cave_cave_cave": 426,         # 204 lines + 203 ellipses + 19 paths
}

_ELEMENT_TOLERANCE = 0.35

_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')
_LINE_RE = re.compile(r"<line\s")
_ELLIPSE_RE = re.compile(r"<ellipse\s")
_PATH_RE = re.compile(r"<path\s")

# CELL = 32 (nhc.rendering._svg_helpers.CELL). The floor_detail
# painters operate within tile bounds (px ∈ [x*CELL, (x+1)*CELL])
# so coordinates stay inside [0, level_w_px]. Allow a small margin
# for stroke-width and decorator overhang at the dungeon-interior
# clipPath envelope.
_CELL = 32
_BOUND_MARGIN = _CELL * 1.5


def _build_buf(inputs):
    return build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    )


def _coords(svg: str) -> list[float]:
    return [float(m) for m in _COORD_RE.findall(svg)]


def _element_count(svg: str) -> int:
    return (
        len(_LINE_RE.findall(svg))
        + len(_ELLIPSE_RE.findall(svg))
        + len(_PATH_RE.findall(svg))
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_element_count_in_range(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="floor_detail")
    n = _element_count(svg)
    baseline = _ELEMENT_BASELINES[descriptor]
    lo = int(baseline * (1 - _ELEMENT_TOLERANCE))
    hi = int(baseline * (1 + _ELEMENT_TOLERANCE))
    assert lo <= n <= hi, (
        f"{descriptor}: floor_detail element count {n} outside "
        f"[{lo}, {hi}] (baseline {baseline} ± "
        f"{_ELEMENT_TOLERANCE * 100:.0f}%)"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_coordinates_inside_canvas(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="floor_detail")
    coords = _coords(svg)
    assert coords, (
        f"{descriptor}: floor_detail layer emitted no coordinates"
    )

    w_max = inputs.level.width * _CELL + _BOUND_MARGIN
    h_max = inputs.level.height * _CELL + _BOUND_MARGIN
    lo = -_BOUND_MARGIN

    upper = max(w_max, h_max)
    out_of_range = [c for c in coords if c < lo or c > upper]
    assert not out_of_range, (
        f"{descriptor}: {len(out_of_range)} floor_detail "
        f"coordinates outside [{lo}, {upper}] — sample: "
        f"{out_of_range[:5]}"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_no_nan_or_inf(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="floor_detail")
    coords = _coords(svg)
    bad = [c for c in coords if math.isnan(c) or math.isinf(c)]
    assert not bad, (
        f"{descriptor}: NaN/Inf in floor_detail coords: {bad[:5]}"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_layer_parses_as_xml(descriptor: str) -> None:
    """The layer is a sequence of fragments — wrap in a root and
    parse to assert nothing is malformed. Catches unbalanced tags,
    bad attribute quoting, and similar Rust formatting bugs."""
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="floor_detail")
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(
            f"{descriptor}: floor_detail layer is not "
            f"well-formed XML: {e}"
        )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_deterministic(descriptor: str) -> None:
    """Two builds of the same fixture must produce byte-equal
    output. Catches RNG-seeding bugs (uninit state, time-derived
    seeds, hash-randomization leaks)."""
    inputs = descriptor_inputs(descriptor)
    svg_a = layer_to_svg(_build_buf(inputs), layer="floor_detail")
    svg_b = layer_to_svg(_build_buf(inputs), layer="floor_detail")
    assert svg_a == svg_b, (
        f"{descriptor}: floor_detail layer is not deterministic "
        f"(diff at byte {next((i for i, (a, b) in enumerate(zip(svg_a, svg_b)) if a != b), -1)})"
    )
