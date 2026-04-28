"""Byte-equality + structural invariants for the fountain
surface-feature port (§8 step 14, all 5 shape variants).

Like wells, fountains are RNG-free (deterministic hash-based)
so the Rust port matches the Python painters byte-equal.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.rendering._features_svg import (
    _circle_fountain_3x3_fragment_for_tile,
    _circle_fountain_fragment_for_tile,
    _cross_fountain_fragment_for_tile,
    _square_fountain_3x3_fragment_for_tile,
    _square_fountain_fragment_for_tile,
)
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


_VARIANTS = [
    ("fountain", _circle_fountain_fragment_for_tile),
    ("fountain_square", _square_fountain_fragment_for_tile),
    ("fountain_large", _circle_fountain_3x3_fragment_for_tile),
    ("fountain_large_square", _square_fountain_3x3_fragment_for_tile),
    ("fountain_cross", _cross_fountain_fragment_for_tile),
]


def _fountain_level(feature: str, anchor: tuple[int, int]) -> Level:
    level = Level.create_empty("t", "t", 1, 12, 12)
    for y in range(12):
        for x in range(12):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    x, y = anchor
    level.tiles[y][x] = Tile(
        terrain=Terrain.FLOOR, feature=feature,
    )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 12, 12))]
    return level


def _layer_svg(level: Level) -> str:
    return layer_to_svg(
        build_floor_ir(level, seed=42), layer="surface_features",
    )


@pytest.mark.parametrize("feature,fn", _VARIANTS)
def test_fountain_byte_equal_legacy_painter(feature, fn) -> None:
    svg = _layer_svg(_fountain_level(feature, (3, 4)))
    expected = fn(3, 4)
    assert expected in svg, (
        f"{feature} Rust output must byte-match the legacy "
        f"painter (RNG-free)"
    )


@pytest.mark.parametrize("feature,_fn", _VARIANTS)
def test_fountain_layer_parses_as_xml(feature, _fn) -> None:
    svg = _layer_svg(_fountain_level(feature, (4, 5)))
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"{feature} layer is not well-formed XML: {e}")


def test_no_fountains_no_envelope() -> None:
    level = Level.create_empty("t", "t", 1, 5, 5)
    for y in range(5):
        for x in range(5):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 5, 5))]
    svg = _layer_svg(level)
    assert "fountain-feature" not in svg
