"""Structural invariants for the ore_deposit decorator port (§8 step 12)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


def _ore_level(width: int, height: int) -> Level:
    """Floor with a few ore-deposit feature tiles. Ore predicate
    fires on ``tile.feature == "ore_deposit"`` (not surface_type)."""
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    # Sprinkle ore on a few tiles.
    for x, y in [(2, 2), (4, 3), (6, 5), (8, 1), (1, 7)]:
        if x < width and y < height:
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR, feature="ore_deposit",
            )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(level: Level, seed: int) -> str:
    return layer_to_svg(build_floor_ir(level, seed=seed), layer="floor_detail")


def test_ore_group_appears() -> None:
    svg = _layer_svg(_ore_level(10, 10), seed=42)
    assert 'id="ore-deposits"' in svg
    assert 'fill="#D4B14A"' in svg


def test_one_diamond_per_ore_tile() -> None:
    svg = _layer_svg(_ore_level(10, 10), seed=42)
    m = re.search(
        r'<g id="ore-deposits"[^>]*>(.*?)</g>', svg, re.DOTALL,
    )
    assert m is not None
    n = m.group(1).count("<polygon")
    assert n == 5, f"expected 5 ore polygons, got {n}"


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(_ore_level(10, 10), seed=42)
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"ore_deposit layer is not well-formed XML: {e}")


def test_deterministic() -> None:
    a = _layer_svg(_ore_level(10, 10), seed=42)
    b = _layer_svg(_ore_level(10, 10), seed=42)
    assert a == b
