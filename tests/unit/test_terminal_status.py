"""Tests for terminal renderer status bar: ring display in line 2."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from nhc.i18n import init as i18n_init


@dataclass
class _Health:
    current: int = 10
    maximum: int = 10


@dataclass
class _Stats:
    strength: int = 1
    dexterity: int = 1
    constitution: int = 1
    intelligence: int = 1
    wisdom: int = 1
    charisma: int = 1


@dataclass
class _Equipment:
    weapon: int | None = None
    armor: int | None = None
    shield: int | None = None
    helmet: int | None = None
    ring_left: int | None = None
    ring_right: int | None = None


@dataclass
class _Player:
    level: int = 1
    xp: int = 0
    xp_to_next: int = 1000
    gold: int = 0


@dataclass
class _Desc:
    name: str = "?"
    short: str = ""


@dataclass
class _Inventory:
    slots: list = None

    def __post_init__(self):
        if self.slots is None:
            self.slots = []
    max_slots: int = 12


@dataclass
class _Weapon:
    damage: str = "1d6"
    type: str = "melee"
    slots: int = 1
    magic_bonus: int = 0


@dataclass
class _Armor:
    slot: str = "body"
    defense: int = 10
    slots: int = 1
    magic_bonus: int = 0


@dataclass
class _Ring:
    effect: str = "mending"


def _mock_world(components_by_eid):
    world = MagicMock()
    world._entities = []

    def get_component(eid, name):
        return components_by_eid.get(eid, {}).get(name)

    def has_component(eid, name):
        return name in components_by_eid.get(eid, {})

    world.get_component = MagicMock(side_effect=get_component)
    world.has_component = MagicMock(side_effect=has_component)
    return world


def _player_comps(**overrides):
    comps = {
        "Health": _Health(),
        "Stats": _Stats(),
        "Equipment": _Equipment(),
        "Player": _Player(),
        "Description": _Desc(name="Hero", short="warrior"),
        "Inventory": _Inventory(),
    }
    comps.update(overrides)
    return comps


def _mock_level():
    level = MagicMock()
    level.name = "Test"
    level.depth = 1
    return level


def _make_renderer():
    from nhc.rendering.terminal.renderer import TerminalRenderer
    tr = TerminalRenderer.__new__(TerminalRenderer)
    return tr


class TestTerminalRingNames:
    """Equipped rings should appear in _gather_stats for line 2."""

    def test_ring_names_in_stats(self):
        i18n_init("en")
        pc = _player_comps()
        pc["Equipment"].ring_left = 20
        pc["Equipment"].ring_right = 21
        pc["Inventory"].slots = [20, 21]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring(effect="mending")},
            21: {"Description": _Desc(name="Ring of Evasion"),
                 "Ring": _Ring(effect="evasion")},
        })
        tr = _make_renderer()
        stats = tr._gather_stats(world, 1, 0, _mock_level())
        assert stats["ring_left_name"] == "Ring of Mending"
        assert stats["ring_right_name"] == "Ring of Evasion"

    def test_no_rings_empty_names(self):
        i18n_init("en")
        world = _mock_world({1: _player_comps()})
        tr = _make_renderer()
        stats = tr._gather_stats(world, 1, 0, _mock_level())
        assert stats["ring_left_name"] == ""
        assert stats["ring_right_name"] == ""

    def test_single_ring_equipped(self):
        i18n_init("en")
        pc = _player_comps()
        pc["Equipment"].ring_left = 20
        pc["Inventory"].slots = [20]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Protection"),
                 "Ring": _Ring(effect="protection")},
        })
        tr = _make_renderer()
        stats = tr._gather_stats(world, 1, 0, _mock_level())
        assert stats["ring_left_name"] == "Ring of Protection"
        assert stats["ring_right_name"] == ""


class TestTerminalRingExcludedFromInventory:
    """Equipped rings should not appear in backpack list (line 3)."""

    def test_equipped_ring_not_in_backpack(self):
        i18n_init("en")
        pc = _player_comps()
        pc["Equipment"].ring_left = 20
        pc["Inventory"].slots = [20, 11]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring()},
            11: {"Description": _Desc(name="Potion")},
        })
        tr = _make_renderer()
        stats = tr._gather_stats(world, 1, 0, _mock_level())
        names, _, _ = tr._gather_inventory(
            world, 1, stats["_equipped_ids"],
        )
        assert "Ring of Mending" not in names
        assert "Potion" in names

    def test_unequipped_ring_in_backpack(self):
        i18n_init("en")
        pc = _player_comps()
        pc["Inventory"].slots = [20]
        world = _mock_world({
            1: pc,
            20: {"Description": _Desc(name="Ring of Mending"),
                 "Ring": _Ring()},
        })
        tr = _make_renderer()
        stats = tr._gather_stats(world, 1, 0, _mock_level())
        names, _, _ = tr._gather_inventory(
            world, 1, stats["_equipped_ids"],
        )
        assert "Ring of Mending" in names
