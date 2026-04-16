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
    HexCell,
    HexFeatureType,
    HexWorld,
    TimeOfDay,
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


def test_state_hex_includes_revealed_only() -> None:
    w = _make_world()
    # Only (1,1) is revealed in the fixture.
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    coords = {(c["q"], c["r"]) for c in msg["cells"]}
    assert coords == {(1, 1)}


def test_state_hex_revealed_cells_carry_biome_and_feature() -> None:
    w = _make_world()
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    (cell,) = msg["cells"]
    assert cell["q"] == 1
    assert cell["r"] == 1
    assert cell["biome"] == "drylands"
    assert cell["feature"] == "city"


def test_state_hex_additional_reveals_are_included() -> None:
    w = _make_world()
    w.reveal(HexCoord(0, 0))
    w.reveal(HexCoord(3, 3))
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    coords = {(c["q"], c["r"]) for c in msg["cells"]}
    assert coords == {(0, 0), (1, 1), (3, 3)}


def test_state_hex_unrevealed_hexes_absent() -> None:
    w = _make_world()
    # Only (1,1) revealed; other coords have cells but aren't
    # revealed -- they must not appear in the payload.
    msg = build_hex_state_msg(w, player_coord=HexCoord(1, 1), turn=0)
    shipped = {(c["q"], c["r"]) for c in msg["cells"]}
    for q in range(4):
        for r in range(4):
            if (q, r) != (1, 1):
                assert (q, r) not in shipped


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
