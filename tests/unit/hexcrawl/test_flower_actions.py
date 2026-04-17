"""Tests for sub-hex actions: search, forage, rest, interact.

Milestone M12.
"""

from __future__ import annotations

import random

from nhc.core.ecs import World
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
    HexWorld,
    MinorFeatureType,
    SubHexCell,
    FLOWER_COORDS,
)
from nhc.hexcrawl._flowers import generate_flower
from nhc.core.actions._sub_hex_actions import (
    SearchSubHexAction,
    ForageSubHexAction,
    RestSubHexAction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup() -> tuple[HexWorld, HexCoord]:
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    cell = HexCell(
        coord=HexCoord(2, 2),
        biome=Biome.FOREST,
        elevation=0.3,
    )
    cell.flower = generate_flower(
        cell, {cell.coord: cell}, seed=42,
    )
    hw.set_cell(cell)
    hw.enter_flower(HexCoord(2, 2), HexCoord(0, 0))
    return hw, HexCoord(2, 2)


def _make_ecs_with_health(hp: int = 10) -> tuple[World, int]:
    w = World()
    from nhc.entities.components import Health
    pid = w.create_entity({"Health": Health(current=5, maximum=hp)})
    return w, pid


# ---------------------------------------------------------------------------
# SearchSubHexAction
# ---------------------------------------------------------------------------


def test_search_marks_searched() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    action = SearchSubHexAction(actor=pid, hex_world=hw)
    assert action.validate_sync()
    result = action.execute_sync()
    sub = hw.exploring_sub_hex
    cell = hw.get_cell(macro)
    assert cell.flower.cells[sub].searched is True


def test_search_advances_clock() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    old_min = hw.hour * 60 + hw.minute
    action = SearchSubHexAction(actor=pid, hex_world=hw)
    action.execute_sync()
    new_min = hw.hour * 60 + hw.minute + (hw.day - 1) * 24 * 60
    assert new_min > old_min


def test_search_cannot_search_twice() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    cell = hw.get_cell(macro)
    cell.flower.cells[HexCoord(0, 0)].searched = True
    action = SearchSubHexAction(actor=pid, hex_world=hw)
    assert not action.validate_sync()


# ---------------------------------------------------------------------------
# ForageSubHexAction
# ---------------------------------------------------------------------------


def test_forage_advances_clock() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    old_min = hw.hour * 60 + hw.minute
    action = ForageSubHexAction(actor=pid, hex_world=hw)
    assert action.validate_sync()
    action.execute_sync()
    new_min = hw.hour * 60 + hw.minute + (hw.day - 1) * 24 * 60
    assert new_min > old_min


def test_forage_returns_items() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    action = ForageSubHexAction(
        actor=pid, hex_world=hw, rng=random.Random(42),
    )
    result = action.execute_sync()
    # Result should be a list of events or items found
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# RestSubHexAction
# ---------------------------------------------------------------------------


def test_rest_heals_hp() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health(hp=10)
    health = w.get_component(pid, "Health")
    health.current = 5
    action = RestSubHexAction(actor=pid, hex_world=hw, ecs_world=w)
    action.execute_sync()
    assert health.current > 5


def test_rest_advances_30_minutes() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    old_min = hw.hour * 60 + hw.minute
    action = RestSubHexAction(actor=pid, hex_world=hw, ecs_world=w)
    action.execute_sync()
    new_min = hw.hour * 60 + hw.minute + (hw.day - 1) * 24 * 60
    # 30 minutes = 0.5 hours
    assert new_min - old_min == 30


def test_rest_always_valid() -> None:
    hw, macro = _setup()
    w, pid = _make_ecs_with_health()
    action = RestSubHexAction(actor=pid, hex_world=hw, ecs_world=w)
    assert action.validate_sync()
