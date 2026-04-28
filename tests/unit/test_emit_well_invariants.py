"""Byte-equality + structural invariants for the well surface
feature port (§8 step 13).

The well painter is RNG-free (deterministic
``_hash_norm`` / ``_hash_unit`` based on tile coordinates), so
the Rust port matches the legacy Python output **byte-equal**.
This test exercises both shape variants via synthetic levels
(existing dungeon / cave fixtures don't contain well tiles).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.rendering._features_svg import (
    _square_well_fragment_for_tile, _well_fragment_for_tile,
)
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


def _well_level(feature: str, *anchors: tuple[int, int]) -> Level:
    level = Level.create_empty("t", "t", 1, 10, 10)
    for y in range(10):
        for x in range(10):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    for x, y in anchors:
        level.tiles[y][x] = Tile(
            terrain=Terrain.FLOOR, feature=feature,
        )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 10, 10))]
    return level


def _layer_svg(level: Level) -> str:
    return layer_to_svg(
        build_floor_ir(level, seed=42), layer="surface_features",
    )


def test_round_well_byte_equal_legacy_painter() -> None:
    svg = _layer_svg(_well_level("well", (4, 4)))
    expected = _well_fragment_for_tile(4, 4)
    assert expected in svg, (
        "round-well Rust output should byte-match the legacy "
        "_well_fragment_for_tile painter (the painter is RNG-free)"
    )


def test_square_well_byte_equal_legacy_painter() -> None:
    svg = _layer_svg(_well_level("well_square", (5, 6)))
    expected = _square_well_fragment_for_tile(5, 6)
    assert expected in svg


def test_multiple_round_wells() -> None:
    svg = _layer_svg(_well_level("well", (1, 1), (8, 7)))
    assert _well_fragment_for_tile(1, 1) in svg
    assert _well_fragment_for_tile(8, 7) in svg


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(_well_level("well", (4, 4), (5, 5)))
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"well layer is not well-formed XML: {e}")


def test_no_wells_means_no_well_envelope() -> None:
    level = Level.create_empty("t", "t", 1, 5, 5)
    for y in range(5):
        for x in range(5):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 5, 5))]
    svg = _layer_svg(level)
    assert "well-feature" not in svg
