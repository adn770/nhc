"""WebSocket ``state_hex`` payload shape.

The web renderer emits one message per overland turn carrying the
day clock, the player coord, the revealed set, and the cell
contents for each revealed hex. Tests target the pure builder so
they don't have to plumb a WebSocket.
"""

from __future__ import annotations

import pytest

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
    HexFlower,
    HexWorld,
    SubHexCell,
    SubHexEdgeSegment,
    TimeOfDay,
    FLOWER_COORDS,
)
from nhc.rendering.web_client import build_hex_state_msg


def _make_world() -> HexWorld:
    w = HexWorld(pack_id="test", seed=1, width=4, height=4)
    for q in range(4):
        for r in range(4):
            w.set_cell(
                HexCell(coord=HexCoord(q, r), biome=Biome.GREENLANDS),
            )
    # Drop a feature on one revealed hex for the rendering test.
    w.cells[HexCoord(1, 1)].feature = HexFeatureType.CITY
    w.cells[HexCoord(1, 1)].biome = Biome.DRYLANDS
    w.reveal(HexCoord(1, 1))
    return w


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_state_hex_payload_shape() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=3)
    assert msg["type"] == "state_hex"
    assert msg["turn"] == 3
    assert "player" in msg
    assert "day" in msg
    assert "time" in msg
    assert "width" in msg and "height" in msg
    assert "cells" in msg
    assert isinstance(msg["cells"], list)


def test_state_hex_player_payload() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(2, 1), turn=0)
    assert msg["player"] == {"q": 2, "r": 1}


def test_state_hex_day_and_time() -> None:
    w = _make_world()
    w.day = 5
    w.time = TimeOfDay.EVENING
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    assert msg["day"] == 5
    assert msg["time"] == "evening"


def test_state_hex_map_dimensions() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(0, 0), turn=0)
    assert msg["width"] == 4
    assert msg["height"] == 4


# ---------------------------------------------------------------------------
# Fog of war: only revealed cells are shipped
# ---------------------------------------------------------------------------


def test_state_hex_includes_all_cells() -> None:
    w = _make_world()
    # All cells are shipped, not just revealed ones.
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    coords = {(c["q"], c["r"]) for c in msg["cells"]}
    assert len(coords) == 16  # 4x4 grid


def test_state_hex_revealed_cells_carry_biome_and_feature() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    cell = by_coord[(1, 1)]
    assert cell["biome"] == "drylands"
    assert cell["feature"] == "city"


def test_state_hex_revealed_flag_true_for_revealed() -> None:
    w = _make_world()
    w.reveal(HexCoord(0, 0))
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    assert by_coord[(1, 1)]["revealed"] is True
    assert by_coord[(0, 0)]["revealed"] is True


def test_state_hex_revealed_flag_false_for_unrevealed() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    # (1,1) is revealed, (3,3) is not.
    assert by_coord[(1, 1)]["revealed"] is True
    assert by_coord[(3, 3)]["revealed"] is False


def test_state_hex_cells_without_feature_use_none_string() -> None:
    w = _make_world()
    w.cells[HexCoord(0, 2)].biome = Biome.MOUNTAIN
    w.reveal(HexCoord(0, 2))
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    # Locate the mountain cell in the payload and check feature key.
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    mtn = by_coord[(0, 2)]
    assert mtn["biome"] == "mountain"
    assert mtn["feature"] == "none"


# ---------------------------------------------------------------------------
# Edge segments in payload
# ---------------------------------------------------------------------------


def test_state_hex_cell_with_edges_includes_edges_key() -> None:
    w = _make_world()
    w.cells[HexCoord(1, 1)].edges.append(
        EdgeSegment(type="river", entry_edge=0, exit_edge=3),
    )
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    cell = by_coord[(1, 1)]
    assert "edges" in cell
    assert len(cell["edges"]) == 1
    seg = cell["edges"][0]
    assert seg["type"] == "river"
    assert seg["entry"] == 0
    assert seg["exit"] == 3


def test_state_hex_cell_without_edges_omits_key() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    cell = by_coord[(0, 0)]
    assert "edges" not in cell


def test_state_hex_edge_source_and_sink_use_null() -> None:
    w = _make_world()
    w.cells[HexCoord(1, 1)].edges.append(
        EdgeSegment(type="river", entry_edge=None, exit_edge=3),
    )
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    seg = by_coord[(1, 1)]["edges"][0]
    assert seg["entry"] is None
    assert seg["exit"] == 3


# ---------------------------------------------------------------------------
# Sub-path inclusion for roads
# ---------------------------------------------------------------------------


def test_state_hex_road_edge_includes_sub_path() -> None:
    """Road (path) edges must include sub_path waypoints when
    the flower is generated via generate_flower().

    Regression: _flowers.py created SubHexEdgeSegment with
    type="road" while macro edges use type="path", causing
    the match in build_hex_state_msg to fail silently.
    """
    from nhc.hexcrawl._flowers import generate_flower

    w = _make_world()
    cell = w.cells[HexCoord(1, 1)]
    cell.edges.append(
        EdgeSegment(type="path", entry_edge=0, exit_edge=3),
    )
    # Generate flower — this is where the bug lived: the flower
    # would create SubHexEdgeSegment(type="road") instead of
    # type="path".
    cell.flower = generate_flower(cell, w.cells, seed=42)

    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    by_coord = {(c["q"], c["r"]): c for c in msg["cells"]}
    seg = by_coord[(1, 1)]["edges"][0]
    assert "sub_path" in seg, (
        "road edge must include sub_path from flower"
    )
