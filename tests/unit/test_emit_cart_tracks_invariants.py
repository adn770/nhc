"""Structural invariants for the cart_tracks decorator port (§8 step 11)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, SurfaceType, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


def _track_strip_level(width: int, height: int) -> Level:
    """Horizontal strip of TRACK tiles at row height // 2."""
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    yh = height // 2
    for x in range(width):
        level.tiles[yh][x] = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.TRACK,
        )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(level: Level, seed: int) -> str:
    return layer_to_svg(build_floor_ir(level, seed=seed), layer="floor_detail")


def test_cart_tracks_emit_rails_and_ties() -> None:
    svg = _layer_svg(_track_strip_level(10, 5), seed=42)
    assert 'id="cart-tracks"' in svg
    assert 'id="cart-track-ties"' in svg


def test_horizontal_strip_emits_horizontal_rails() -> None:
    """Horizontal-adjacent TRACK tiles → horizontal rails (lines
    that span x but share a single y)."""
    svg = _layer_svg(_track_strip_level(10, 5), seed=42)
    # Pull the cart-tracks group only.
    m = re.search(
        r'<g id="cart-tracks"[^>]*>(.*?)</g>', svg, re.DOTALL,
    )
    assert m is not None
    rails_block = m.group(1)
    n_lines = rails_block.count("<line")
    # 10 TRACK tiles × 2 rails each = 20 horizontal rails.
    assert n_lines == 20, f"expected 20 rails, got {n_lines}"


def test_isolated_track_emits_vertical_rails() -> None:
    """A single isolated TRACK tile (no east/west neighbours) →
    vertical rails."""
    level = Level.create_empty("t", "t", 1, 5, 5)
    for y in range(5):
        for x in range(5):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.tiles[2][2] = Tile(
        terrain=Terrain.FLOOR, surface_type=SurfaceType.TRACK,
    )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 5, 5))]
    svg = _layer_svg(level, seed=42)
    m = re.search(
        r'<g id="cart-tracks"[^>]*>(.*?)</g>', svg, re.DOTALL,
    )
    assert m is not None
    # Vertical rails: x1 == x2; horizontal: y1 == y2.
    # Pull all rail line tags and check.
    rails = re.findall(
        r'<line x1="([\d.]+)" y1="([\d.]+)" '
        r'x2="([\d.]+)" y2="([\d.]+)"',
        m.group(1),
    )
    assert len(rails) == 2
    for x1, y1, x2, y2 in rails:
        assert x1 == x2, "isolated track expected vertical rails"


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(_track_strip_level(10, 5), seed=42)
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"cart_tracks layer is not well-formed XML: {e}")
