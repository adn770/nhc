"""Biome-dependent step costs and the HexWorld day clock.

HexWorld.advance_clock itself is covered in test_model.py. These
tests target the biome -> segments lookup added in M-1.4 and the
convenience helper on HexWorld that performs a biome-derived step.
"""

from __future__ import annotations

import pytest

from nhc.hexcrawl.clock import cost_for
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexWorld,
    TimeOfDay,
)
from nhc.hexcrawl.pack import DEFAULT_BIOME_COSTS, PackMeta, load_pack


# ---------------------------------------------------------------------------
# cost_for() -- plain biome lookup
# ---------------------------------------------------------------------------


def test_cost_for_default_greenlands() -> None:
    assert cost_for(Biome.GREENLANDS) == 1


def test_cost_for_default_drylands() -> None:
    assert cost_for(Biome.DRYLANDS) == 1


def test_cost_for_default_forest_and_hills_midrange() -> None:
    assert cost_for(Biome.FOREST) == 2
    assert cost_for(Biome.SANDLANDS) == 2
    assert cost_for(Biome.ICELANDS) == 2
    assert cost_for(Biome.DEADLANDS) == 2


def test_cost_for_default_mountain_expensive() -> None:
    assert cost_for(Biome.MOUNTAIN) == 4


def test_cost_for_defaults_match_design_doc_table() -> None:
    # The mapping captured in design/overland_hexcrawl.md §5. Keeping
    # this test explicit makes the default table hard to silently
    # drift. Hills / marsh / swamp entries landed with M-G.1.
    assert dict(DEFAULT_BIOME_COSTS) == {
        Biome.GREENLANDS: 1,
        Biome.DRYLANDS: 1,
        Biome.SANDLANDS: 2,
        Biome.ICELANDS: 2,
        Biome.FOREST: 2,
        Biome.MOUNTAIN: 4,
        Biome.DEADLANDS: 2,
        Biome.HILLS: 2,
        Biome.MARSH: 3,
        Biome.SWAMP: 3,
        Biome.WATER: 99,
    }


def test_cost_for_override_via_costs_dict() -> None:
    override = {b: 5 for b in Biome}
    assert cost_for(Biome.MOUNTAIN, costs=override) == 5
    # Unmentioned biome falls through to defaults.
    partial = {Biome.GREENLANDS: 7}
    assert cost_for(Biome.GREENLANDS, costs=partial) == 7
    assert cost_for(Biome.MOUNTAIN, costs=partial) == 4


# ---------------------------------------------------------------------------
# HexWorld.advance_clock_for_cell
# ---------------------------------------------------------------------------


def _make_world() -> HexWorld:
    return HexWorld(pack_id="testland", seed=1, width=4, height=4)


def test_advance_clock_for_cell_greenlands_one_segment() -> None:
    w = _make_world()
    from nhc.hexcrawl.coords import HexCoord
    cell = HexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
    w.advance_clock_for_cell(cell)
    assert w.day == 1
    assert w.time is TimeOfDay.MIDDAY


def test_advance_clock_for_cell_mountain_four_segments() -> None:
    w = _make_world()
    from nhc.hexcrawl.coords import HexCoord
    cell = HexCell(coord=HexCoord(0, 0), biome=Biome.MOUNTAIN)
    w.advance_clock_for_cell(cell)
    # 4 segments from morning wraps one full day; we land on the
    # next day's morning.
    assert w.day == 2
    assert w.time is TimeOfDay.MORNING


def test_advance_clock_for_cell_uses_world_biome_costs() -> None:
    w = _make_world()
    w.biome_costs = {Biome.GREENLANDS: 3}
    from nhc.hexcrawl.coords import HexCoord
    cell = HexCell(coord=HexCoord(0, 0), biome=Biome.GREENLANDS)
    w.advance_clock_for_cell(cell)
    assert w.time is TimeOfDay.NIGHT   # 3 segments ahead of MORNING


# ---------------------------------------------------------------------------
# Pack override wiring through the loader
# ---------------------------------------------------------------------------


def test_cost_for_with_pack_biome_costs(tmp_path) -> None:
    body = """
id: override_pack
version: 1
map:
  generator: bsp_regions
  width: 4
  height: 4
biome_costs:
  mountain: 6
  forest: 3
"""
    p = tmp_path / "pack.yaml"
    p.write_text(body)
    pack: PackMeta = load_pack(p)
    # Overrides applied.
    assert cost_for(Biome.MOUNTAIN, costs=pack.biome_costs) == 6
    assert cost_for(Biome.FOREST, costs=pack.biome_costs) == 3
    # Unmentioned biome still uses the packaged default.
    assert cost_for(Biome.GREENLANDS, costs=pack.biome_costs) == 1


def test_generator_populates_hexworld_biome_costs(tmp_path) -> None:
    # When the generator builds a world from a pack, the world's
    # biome_costs mirror the pack -- so MoveHexAction etc. can
    # consult world.biome_costs without needing a pack reference.
    from nhc.hexcrawl.generator import generate_test_world
    body = """
id: override_pack
version: 1
map:
  generator: bsp_regions
  width: 8
  height: 8
biome_costs:
  mountain: 6
"""
    p = tmp_path / "pack.yaml"
    p.write_text(body)
    pack = load_pack(p)
    world = generate_test_world(seed=1, pack=pack)
    assert world.biome_costs[Biome.MOUNTAIN] == 6
    assert world.biome_costs[Biome.GREENLANDS] == 1
