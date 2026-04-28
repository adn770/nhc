"""Structural invariants for the thematic_detail layer.

Per §8 of ``plans/nhc_ir_migration_plan.md`` (Q5 step 4, locked
2026-04-28), the thematic_detail primitive ships under a relaxed
parity gate (mirrors the step-3 floor_detail gate). The
byte-equal-with-legacy contract is replaced by these structural
invariants plus a snapshot lock at
``tests/fixtures/floor_ir/<descriptor>/thematic_detail.svg``
(lands at sub-step 4.f).

The invariants assert that the thematic_detail layer is visually
well-formed regardless of the underlying RNG choice:

- Element counts within a sane range per fixture.
- All coordinates inside the expected bounding box (no fragments
  flying off the canvas).
- No NaN or Inf in any coordinate.
- Output parses as well-formed XML when wrapped in a root.
- Re-rendering the same buffer twice produces byte-equal output.

Sub-step 4.b populates the layer (until then it was empty); this
gate baselines the post-4.b Python painter output so the
sub-step 4.e Rust port has something to drift against.
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


# Baseline element counts measured against the post-4.b Python
# painter output on 2026-04-28. The Rust port at sub-step 4.e
# uses Pcg64Mcg instead of CPython's MT19937 so exact counts
# shift; ±35 % absorbs the RNG drift but flags a port that emits
# zero / 100× too many fragments. The snapshot lock at sub-step
# 4.f pins the exact output; this range is a sanity check.
_ELEMENT_BASELINES = {
    "seed42_rect_dungeon_dungeon": 140,   # 38 lines + 76 ellipses + 26 paths
    "seed7_octagon_crypt_dungeon": 750,   # 198 lines + 396 ellipses + 156 paths
    "seed99_cave_cave_cave": 90,          # 25 lines + 50 ellipses + 15 paths
}

_ELEMENT_TOLERANCE = 0.35

_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')
_LINE_RE = re.compile(r"<line\s")
_ELLIPSE_RE = re.compile(r"<ellipse\s")
_PATH_RE = re.compile(r"<path\s")

# CELL = 32. Thematic painters operate within tile bounds with
# small margins for stroke width and the skull's translate /
# rotate transform. Allow 1.5 cells of margin.
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
    svg = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    n = _element_count(svg)
    baseline = _ELEMENT_BASELINES[descriptor]
    lo = int(baseline * (1 - _ELEMENT_TOLERANCE))
    hi = int(baseline * (1 + _ELEMENT_TOLERANCE))
    assert lo <= n <= hi, (
        f"{descriptor}: thematic_detail element count {n} outside "
        f"[{lo}, {hi}] (baseline {baseline} ± "
        f"{_ELEMENT_TOLERANCE * 100:.0f}%)"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_coordinates_inside_canvas(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    coords = _coords(svg)
    assert coords, (
        f"{descriptor}: thematic_detail layer emitted no coordinates"
    )

    w_max = inputs.level.width * _CELL + _BOUND_MARGIN
    h_max = inputs.level.height * _CELL + _BOUND_MARGIN
    lo = -_BOUND_MARGIN

    # Skull paths emit local coordinates (e.g. "-3.8" for cranium
    # half-width) that get positioned via a parent transform; raw
    # coords near zero are normal. Allow generous lower bound.
    upper = max(w_max, h_max)
    out_of_range = [c for c in coords if c < lo or c > upper]
    assert not out_of_range, (
        f"{descriptor}: {len(out_of_range)} thematic_detail "
        f"coordinates outside [{lo}, {upper}] — sample: "
        f"{out_of_range[:5]}"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_no_nan_or_inf(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    coords = _coords(svg)
    bad = [c for c in coords if math.isnan(c) or math.isinf(c)]
    assert not bad, (
        f"{descriptor}: NaN/Inf in thematic_detail coords: {bad[:5]}"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_layer_parses_as_xml(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(
            f"{descriptor}: thematic_detail layer is not "
            f"well-formed XML: {e}"
        )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_deterministic(descriptor: str) -> None:
    inputs = descriptor_inputs(descriptor)
    svg_a = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    svg_b = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    assert svg_a == svg_b, (
        f"{descriptor}: thematic_detail layer is not deterministic"
    )


@pytest.mark.parametrize("descriptor", all_descriptors())
def test_thematic_detail_snapshot_matches_fixture(
    descriptor: str,
) -> None:
    """Sub-step 4.f — byte-equal snapshot lock against the Rust port.

    Pairs with the structural invariants above: the invariants
    pin *what* the layer must produce; the snapshot pins
    *exactly* what it produces. Drift on either the emitter
    (4.b candidate walk + wall_corners bitmap) or the Rust impl
    (4.d painters) trips this gate first.

    The fixture lives at
    ``tests/fixtures/floor_ir/<descriptor>/thematic_detail.svg``
    and is refreshed via
    ``python -m tests.samples.regenerate_fixtures``.
    """
    inputs = descriptor_inputs(descriptor)
    actual = layer_to_svg(_build_buf(inputs), layer="thematic_detail")
    fixture = _FIXTURE_ROOT / descriptor / "thematic_detail.svg"
    assert fixture.exists(), (
        f"{descriptor}: thematic_detail.svg fixture missing — "
        f"re-run `python -m tests.samples.regenerate_fixtures`"
    )
    expected = fixture.read_text()
    assert actual == expected, (
        f"{descriptor}: thematic_detail layer drifts from snapshot. "
        f"If this drift is intentional, refresh fixtures via "
        f"`python -m tests.samples.regenerate_fixtures`."
    )
