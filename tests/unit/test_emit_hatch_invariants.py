"""Structural invariants for the hatching layer.

Per §8 of ``plans/nhc_ir_migration_plan.md`` (locked 2026-04-28),
the hatch primitive ships under a relaxed parity gate — the
byte-equal-with-legacy contract is replaced with these
structural invariants plus a snapshot lock against the new
Rust output. The byte-equal test (``test_emit_hatch_parity.py``)
is retired in the same commit that lands the Rust port.

The invariants assert that the hatching layer is visually
well-formed regardless of the underlying RNG choice:

- Stroke count within a sane range per fixture (catches
  catastrophic miscounts; not a precision test — the snapshot
  lock pins exact output).
- All coordinates inside the expected bounding box (no strokes
  flying off the canvas).
- No NaN or Inf in any coordinate (catches FP misuse in the
  Rust port's geometry path).
- Output parses as well-formed XML when wrapped in a root.
- Re-rendering the same buffer twice produces byte-equal output
  (catches RNG-seeding bugs that would let output drift
  between runs).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg

from tests.fixtures.floor_ir._inputs import (
    all_descriptors,
    descriptor_inputs,
)


# Baseline stroke counts measured against the current Python
# output on 2026-04-28 (legacy byte-equal port). The Rust port
# lands a new RNG so exact counts shift; ±35 % is wide enough to
# absorb the RNG difference but tight enough to flag a port that
# emits zero / 100× too many strokes. The snapshot lock pins the
# exact output; this range is a sanity check.
_STROKE_BASELINES = {
    "seed42_rect_dungeon_dungeon": 10527,
    "seed7_octagon_crypt_dungeon": 11349,
    "seed99_cave_cave_cave": 7574,
}

_STROKE_TOLERANCE = 0.35

_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')

# CELL = 32 (nhc.rendering._svg_helpers.CELL). Hatching iterates
# the candidate space ``range(-1, width+1)``, so coordinates can
# extend one CELL outside the level on every side. Allow 1.5×
# for Perlin wobble + cluster-anchor jitter.
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


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_stroke_count_in_range(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="hatching")
    n = len(re.findall(r"<line\s", svg))
    baseline = _STROKE_BASELINES[descriptor]
    lo = int(baseline * (1 - _STROKE_TOLERANCE))
    hi = int(baseline * (1 + _STROKE_TOLERANCE))
    assert lo <= n <= hi, (
        f"{descriptor}: hatch stroke count {n} outside "
        f"[{lo}, {hi}] (baseline {baseline} ± {_STROKE_TOLERANCE * 100:.0f}%)"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_coordinates_inside_canvas(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="hatching")
    coords = _coords(svg)
    assert coords, f"{descriptor}: hatching layer emitted no coordinates"

    w_max = inputs.level.width * _CELL + _BOUND_MARGIN
    h_max = inputs.level.height * _CELL + _BOUND_MARGIN
    lo = -_BOUND_MARGIN

    # The coordinate regex is attribute-name-agnostic so x and y
    # are pooled together. Pick the larger dimension for the upper
    # bound — the levels in the starter set are landscape (w > h)
    # so the loose bound is conservative, not lax.
    upper = max(w_max, h_max)
    out_of_range = [c for c in coords if c < lo or c > upper]
    assert not out_of_range, (
        f"{descriptor}: {len(out_of_range)} hatch coordinates "
        f"outside [{lo}, {upper}] — sample: {out_of_range[:5]}"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_no_nan_or_inf(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="hatching")
    coords = _coords(svg)
    bad = [c for c in coords if math.isnan(c) or math.isinf(c)]
    assert not bad, f"{descriptor}: NaN/Inf in hatch coords: {bad[:5]}"


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_layer_parses_as_xml(descriptor: str) -> None:
    """The layer is a sequence of fragments — wrap in a root and
    parse to assert nothing is malformed. Catches unbalanced tags,
    bad attribute quoting, and similar Rust formatting bugs."""
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="hatching")
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"{descriptor}: hatch layer is not well-formed XML: {e}")


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_deterministic(descriptor: str) -> None:
    """Two builds of the same fixture must produce byte-equal
    output. Catches RNG-seeding bugs (uninit state, time-derived
    seeds, hash-randomization leaks)."""
    inputs = descriptor_inputs(descriptor)
    svg_a = layer_to_svg(_build_buf(inputs), layer="hatching")
    svg_b = layer_to_svg(_build_buf(inputs), layer="hatching")
    assert svg_a == svg_b, (
        f"{descriptor}: hatching layer is not deterministic "
        f"(diff at byte {next((i for i, (a, b) in enumerate(zip(svg_a, svg_b)) if a != b), -1)})"
    )
