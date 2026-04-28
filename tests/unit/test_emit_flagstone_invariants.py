"""Structural invariants for the flagstone decorator port (§8 step 8)."""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, SurfaceType, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


_POLYGON_RE = re.compile(r"<polygon\s")
_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')


def _flagstone_level(width: int, height: int) -> Level:
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.FLAGSTONE,
            )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(width: int, height: int, seed: int) -> str:
    level = _flagstone_level(width, height)
    buf = build_floor_ir(level, seed=seed)
    return layer_to_svg(buf, layer="floor_detail")


def test_flagstone_group_appears() -> None:
    svg = _layer_svg(5, 5, seed=42)
    assert 'stroke="#6A6055"' in svg


def test_four_polygons_per_tile() -> None:
    svg = _layer_svg(5, 5, seed=42)
    n = len(_POLYGON_RE.findall(svg))
    assert n == 25 * 4, f"expected {25 * 4} polygons, got {n}"


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
        pytest.fail(f"flagstone layer is not well-formed XML: {e}")


def test_deterministic() -> None:
    a = _layer_svg(4, 4, seed=42)
    b = _layer_svg(4, 4, seed=42)
    assert a == b
