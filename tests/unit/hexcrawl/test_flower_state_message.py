"""WebSocket ``state_flower`` payload shape.

The web renderer emits one ``state_flower`` message per sub-hex
turn. The client uses the ``macro_hex`` field to detect when the
active flower has changed and invalidate its static canvas layers
(base / feature / fog). Without this field the client cannot tell
flower A from flower B and renders B's entities on top of A's
base tiles — the "always returns to the initial hexflower" bug.

These tests pin the payload contract. The fix in hex_flower.js
that reads ``state.macro_hex`` depends on it.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    FLOWER_COORDS,
    Biome,
    HexCell,
    HexFeatureType,
    HexFlower,
    HexWorld,
    SubHexCell,
)
from nhc.rendering.web_client import build_flower_state_msg


def _make_world_with_flower(
    macro: HexCoord,
    biome: Biome = Biome.GREENLANDS,
    feature: HexFeatureType = HexFeatureType.NONE,
) -> HexWorld:
    """Minimal HexWorld carrying one macro cell with a 19-sub-hex
    flower. Enough to drive ``build_flower_state_msg`` without a
    full generator run."""
    w = HexWorld(pack_id="test", seed=1, width=8, height=8)
    cell = HexCell(coord=macro, biome=biome, feature=feature)
    cell.flower = HexFlower(
        parent_coord=macro,
        cells={
            c: SubHexCell(coord=c, biome=biome)
            for c in FLOWER_COORDS
        },
    )
    w.set_cell(cell)
    w.exploring_hex = macro
    w.exploring_sub_hex = HexCoord(0, 0)
    return w


def test_state_flower_includes_macro_hex() -> None:
    """The client uses ``macro_hex`` to detect flower transitions
    and invalidate its static canvas cache. Removing this field
    silently breaks the fix in hex_flower.js that prevents
    flower A's tiles from lingering when the player enters
    flower B."""
    w = _make_world_with_flower(HexCoord(6, 7))
    msg = build_flower_state_msg(w, player_sub=HexCoord(0, 0), turn=1)
    assert "macro_hex" in msg, (
        "state_flower must carry macro_hex; the client reads it "
        "to invalidate stale canvas layers on flower transitions"
    )
    assert msg["macro_hex"] == {"q": 6, "r": 7}


def test_state_flower_macro_hex_tracks_exploring_hex() -> None:
    """Each re-enter (e.g. overland → flower) ships the *current*
    macro. Two messages with distinct macros must report distinct
    ``macro_hex`` so the client's macro-change check fires."""
    w_hub = _make_world_with_flower(
        HexCoord(6, 7), feature=HexFeatureType.CITY,
    )
    msg_hub = build_flower_state_msg(
        w_hub, player_sub=HexCoord(0, 0), turn=1,
    )

    w_nbr = _make_world_with_flower(HexCoord(6, 6))
    msg_nbr = build_flower_state_msg(
        w_nbr, player_sub=HexCoord(0, 0), turn=4,
    )

    assert msg_hub["macro_hex"] != msg_nbr["macro_hex"], (
        "distinct macros must emit distinct macro_hex values so the "
        "client can detect a flower swap"
    )
    assert msg_hub["macro_hex"] == {"q": 6, "r": 7}
    assert msg_nbr["macro_hex"] == {"q": 6, "r": 6}
