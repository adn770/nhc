"""Structural invariants for the field_stone decorator port (§8 step 10)."""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, SurfaceType, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


_ELLIPSE_RE = re.compile(r"<ellipse\s")
_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')


def _field_level(width: int, height: int) -> Level:
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.GRASS,
                surface_type=SurfaceType.FIELD,
            )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(width: int, height: int, seed: int) -> str:
    level = _field_level(width, height)
    buf = build_floor_ir(level, seed=seed)
    return layer_to_svg(buf, layer="floor_detail")


def test_field_stone_appears() -> None:
    svg = _layer_svg(15, 15, seed=42)
    assert 'fill="#8A9A6A"' in svg


def test_around_10_percent_fire_rate() -> None:
    svg = _layer_svg(20, 20, seed=42)
    # Pull only ellipses with the field-stone fill (cracks /
    # stones in floor-detail-proper use a different palette).
    field_ellipses = re.findall(
        r'<ellipse[^/]*fill="#8A9A6A"', svg,
    )
    n = len(field_ellipses)
    expected = 400 * 0.10
    assert (
        expected * 0.5 <= n <= expected * 1.6
    ), f"expected ~{expected:.0f} field stones, got {n}"


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(10, 10, seed=42)
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"field_stone layer is not well-formed XML: {e}")


def test_deterministic() -> None:
    a = _layer_svg(8, 8, seed=42)
    b = _layer_svg(8, 8, seed=42)
    assert a == b
