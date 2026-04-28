"""Structural invariants for the brick decorator port.

Per §8 step 7 of ``plans/nhc_ir_migration_plan.md``. Existing
fixtures don't contain BRICK tiles; coverage rides on a
synthetic level mirroring step 6's cobblestone gate.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, SurfaceType, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


_RECT_RE = re.compile(r"<rect\s")
_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')


def _brick_level(width: int, height: int) -> Level:
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.BRICK,
            )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(width: int, height: int, seed: int) -> str:
    level = _brick_level(width, height)
    buf = build_floor_ir(level, seed=seed)
    return layer_to_svg(buf, layer="floor_detail")


def test_brick_group_appears_with_brick_tiles() -> None:
    svg = _layer_svg(5, 5, seed=42)
    assert 'stroke="#A05530"' in svg


def test_brick_rect_count_in_range() -> None:
    svg = _layer_svg(5, 5, seed=42)
    n_rects = len(_RECT_RE.findall(svg))
    # Per tile: 4 rows × 2 bricks (even) + 4 rows × 3 bricks (odd
    # offset) ÷ 2 ≈ 10 rects; jitter rejects some.
    expected = 25 * 10
    assert (
        expected - 100 <= n_rects <= expected + 50
    ), f"expected ~{expected} brick rects, got {n_rects}"


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(5, 5, seed=42)
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"brick layer is not well-formed XML: {e}")


def test_no_nan_or_inf() -> None:
    svg = _layer_svg(5, 5, seed=42)
    coords = [float(m) for m in _COORD_RE.findall(svg)]
    bad = [c for c in coords if math.isnan(c) or math.isinf(c)]
    assert not bad


def test_deterministic() -> None:
    a = _layer_svg(5, 5, seed=42)
    b = _layer_svg(5, 5, seed=42)
    assert a == b
