"""Structural invariants for the tree surface-feature port
(§8 step 15, relaxed parity gate).

Trees use Shapely polygon unions for both per-tile canopy
silhouettes and for grove fusion (3+ adjacent trees union into
one canopy). Rust port uses geo crate's BooleanOps; vertex
ordering / numerical precision differs from Shapely so byte-
equal isn't achievable. Output is gated by structural
invariants only.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


def _tree_level(*anchors: tuple[int, int]) -> Level:
    level = Level.create_empty("t", "t", 1, 12, 12)
    for y in range(12):
        for x in range(12):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    for x, y in anchors:
        level.tiles[y][x] = Tile(
            terrain=Terrain.FLOOR, feature="tree",
        )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 12, 12))]
    return level


def _layer_svg(level: Level) -> str:
    return layer_to_svg(
        build_floor_ir(level, seed=42), layer="surface_features",
    )


def test_single_tree_has_trunk() -> None:
    svg = _layer_svg(_tree_level((4, 4)))
    assert 'class="tree-feature"' in svg
    assert 'class="tree-trunk"' in svg
    assert 'class="tree-canopy"' in svg


def test_pair_keeps_individual_trees() -> None:
    """Two trees adjacent → grove of size 2 → still painted as
    individual trees with trunks."""
    svg = _layer_svg(_tree_level((4, 4), (5, 4)))
    n_features = svg.count('class="tree-feature"')
    n_groves = svg.count('class="tree-grove"')
    n_trunks = svg.count('class="tree-trunk"')
    assert n_features == 2, f"expected 2 individual trees, got {n_features}"
    assert n_groves == 0, f"expected no grove, got {n_groves}"
    assert n_trunks == 2


def test_triple_fuses_into_grove() -> None:
    """Three trees in a row → grove → one fused fragment, no
    trunks."""
    svg = _layer_svg(_tree_level((4, 4), (5, 4), (6, 4)))
    n_features = svg.count('class="tree-feature"')
    n_groves = svg.count('class="tree-grove"')
    n_trunks = svg.count('class="tree-trunk"')
    assert n_features == 0, "grove must drop individual trees"
    assert n_groves == 1, f"expected 1 grove, got {n_groves}"
    assert n_trunks == 0, "grove drops trunks"


def test_disconnected_groves_emit_separately() -> None:
    """Two disconnected groves of 3 → 2 grove fragments."""
    svg = _layer_svg(_tree_level(
        (1, 1), (2, 1), (3, 1),
        (8, 8), (9, 8), (10, 8),
    ))
    assert svg.count('class="tree-grove"') == 2


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(_tree_level((4, 4), (5, 4), (5, 5)))
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"tree layer is not well-formed XML: {e}")


def test_grove_anchor_uses_min() -> None:
    """Grove id should be `tree-grove-{min_x}-{min_y}`."""
    svg = _layer_svg(_tree_level((6, 4), (5, 4), (4, 4)))
    assert 'id="tree-grove-4-4"' in svg, (
        "grove id should anchor at min(grove)"
    )


def test_deterministic() -> None:
    a = _layer_svg(_tree_level((3, 3), (4, 3), (5, 3)))
    b = _layer_svg(_tree_level((3, 3), (4, 3), (5, 3)))
    assert a == b
