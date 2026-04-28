"""Structural invariants for the bush surface-feature port
(§8 step 16, relaxed parity gate).

The bush painter uses Shapely polygon unions for the multi-lobe
canopy + shadow silhouettes; the Rust port uses ``geo`` crate's
BooleanOps which approximates circles slightly differently and
produces different vertex orderings, so byte-equal vs the legacy
painter is not achievable. Output is gated by structural
invariants only; town golden re-baselines on this commit.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


def _bush_level(*anchors: tuple[int, int]) -> Level:
    level = Level.create_empty("t", "t", 1, 10, 10)
    for y in range(10):
        for x in range(10):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    for x, y in anchors:
        level.tiles[y][x] = Tile(
            terrain=Terrain.FLOOR, feature="bush",
        )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 10, 10))]
    return level


def _layer_svg(level: Level) -> str:
    return layer_to_svg(
        build_floor_ir(level, seed=42), layer="surface_features",
    )


def test_bush_feature_envelope_appears() -> None:
    svg = _layer_svg(_bush_level((4, 4)))
    assert 'class="bush-feature"' in svg
    assert 'class="bush-canopy"' in svg
    assert 'class="bush-canopy-shadow"' in svg


def test_each_bush_emits_one_envelope() -> None:
    svg = _layer_svg(_bush_level((1, 1), (5, 5), (8, 7)))
    n = svg.count('class="bush-feature"')
    assert n == 3, f"expected 3 bush envelopes, got {n}"


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(_bush_level((4, 4), (5, 5)))
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"bush layer is not well-formed XML: {e}")


def test_canopy_path_well_formed() -> None:
    svg = _layer_svg(_bush_level((4, 4)))
    # Pull out the bush-canopy path d-string.
    m = re.search(r'class="bush-canopy" d="([^"]+)"', svg)
    assert m is not None
    d = m.group(1)
    # Basic shape: starts with M, has L commands, ends with Z.
    assert d.startswith("M")
    assert "L" in d
    assert d.rstrip().endswith("Z")


def test_deterministic() -> None:
    a = _layer_svg(_bush_level((3, 3), (4, 5)))
    b = _layer_svg(_bush_level((3, 3), (4, 5)))
    assert a == b


def test_no_bushes_means_no_envelope() -> None:
    level = Level.create_empty("t", "t", 1, 5, 5)
    for y in range(5):
        for x in range(5):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 5, 5))]
    svg = _layer_svg(level)
    assert "bush-feature" not in svg
