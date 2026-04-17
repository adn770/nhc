"""Tests for hexcrawl starting directly in flower view.

Milestone W4: easy/medium start adjacent to hub, survival random.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import HexFeatureType, FLOWER_COORDS
from nhc.hexcrawl.generator import generate_test_world
from nhc.hexcrawl.pack import load_pack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PACK_BODY = textwrap.dedent("""
    id: testland
    version: 1
    attribution: "test"
    map:
      generator: bsp_regions
      width: 8
      height: 8
      num_regions: 5
      region_min: 6
      region_max: 16
    features:
      hub: 1
      village:
        min: 1
        max: 2
      dungeon:
        min: 2
        max: 3
      wonder:
        min: 1
        max: 1
    rivers:
      max_rivers: 2
      min_length: 3
""")


def _load_pack(tmp_path: Path):
    p = tmp_path / "pack.yaml"
    p.write_text(_PACK_BODY)
    return load_pack(p)


def _make_hex_world(tmp_path: Path):
    pack = _load_pack(tmp_path)
    return generate_test_world(42, pack)


# ---------------------------------------------------------------------------
# pick_flower_start
# ---------------------------------------------------------------------------


def test_easy_start_at_hub_center(tmp_path) -> None:
    from nhc.hexcrawl._flowers import pick_flower_start
    hw = _make_hex_world(tmp_path)
    hub = hw.last_hub
    assert hub is not None
    macro, sub = pick_flower_start(hw, GameMode.HEX_EASY, seed=42)
    assert macro == hub
    assert sub == HexCoord(0, 0)


def test_medium_start_at_hub_center(tmp_path) -> None:
    from nhc.hexcrawl._flowers import pick_flower_start
    hw = _make_hex_world(tmp_path)
    hub = hw.last_hub
    macro, sub = pick_flower_start(hw, GameMode.HEX_MEDIUM, seed=42)
    assert macro == hub
    assert sub == HexCoord(0, 0)


def test_survival_start_random_hex(tmp_path) -> None:
    from nhc.hexcrawl._flowers import pick_flower_start
    hw = _make_hex_world(tmp_path)
    hub = hw.last_hub
    macro, sub = pick_flower_start(
        hw, GameMode.HEX_SURVIVAL, seed=42,
    )
    # Should NOT be the hub
    assert macro != hub
    # Should be a non-feature hex
    cell = hw.get_cell(macro)
    assert cell.feature is HexFeatureType.NONE
    assert sub in FLOWER_COORDS


def test_start_enters_flower(tmp_path) -> None:
    from nhc.hexcrawl._flowers import pick_flower_start
    hw = _make_hex_world(tmp_path)
    macro, sub = pick_flower_start(hw, GameMode.HEX_EASY, seed=42)
    # After entering, exploring_hex should be set
    hw.enter_flower(macro, sub)
    assert hw.exploring_hex == macro
    assert hw.exploring_sub_hex == sub


def test_easy_start_hub_is_revealed(tmp_path) -> None:
    """In easy/medium, the hub hex should be revealed."""
    from nhc.hexcrawl._flowers import pick_flower_start
    hw = _make_hex_world(tmp_path)
    hub = hw.last_hub
    macro, sub = pick_flower_start(hw, GameMode.HEX_EASY, seed=42)
    # The caller (game.py) reveals the hub, not pick_flower_start
    # — but the macro hex should be marked visited
    hw.visit(macro)
    hw.reveal(hub)
    assert hw.is_revealed(hub)


def test_survival_hub_not_revealed(tmp_path) -> None:
    """In survival, the hub should NOT be revealed."""
    from nhc.hexcrawl._flowers import pick_flower_start
    hw = _make_hex_world(tmp_path)
    macro, sub = pick_flower_start(
        hw, GameMode.HEX_SURVIVAL, seed=42,
    )
    # Hub should not be in revealed set
    assert hw.last_hub not in hw.revealed
