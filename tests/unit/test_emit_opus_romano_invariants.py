"""Structural invariants for the opus_romano decorator port (§8 step 9)."""
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


def _opus_level(width: int, height: int) -> Level:
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.OPUS_ROMANO,
            )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(width: int, height: int, seed: int) -> str:
    level = _opus_level(width, height)
    buf = build_floor_ir(level, seed=seed)
    return layer_to_svg(buf, layer="floor_detail")


def test_opus_group_appears() -> None:
    svg = _layer_svg(4, 4, seed=42)
    assert 'stroke="#7A5A3A"' in svg


def test_four_rects_per_tile() -> None:
    svg = _layer_svg(4, 4, seed=42)
    n = len(_RECT_RE.findall(svg))
    assert n == 16 * 4, f"expected {16 * 4} opus rects, got {n}"


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(4, 4, seed=42)
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"opus_romano layer is not well-formed XML: {e}")


def test_opus_group_seed_independent() -> None:
    """The opus-romano painter is RNG-free; the layer slice
    mixes its output with the seed-dependent floor-detail-proper
    cracks / stones / scratches, so isolate the opus group by
    bucketing on its stroke colour."""
    a = _layer_svg(4, 4, seed=42)
    b = _layer_svg(4, 4, seed=999)
    # Pull the opus <g ... stroke="#7A5A3A" ...>...</g> only.
    pattern = re.compile(
        r'<g[^>]*stroke="#7A5A3A"[^>]*>.*?</g>', re.DOTALL,
    )
    assert pattern.search(a).group() == pattern.search(b).group()
