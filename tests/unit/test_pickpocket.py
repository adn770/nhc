"""Tests for the pickpocket — PickpocketAction + `thief` behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nhc.ai.behavior import decide_action
from nhc.core.actions import (
    MoveAction, PickpocketAction, player_has_stealable,
)
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Equipment,
    Errand,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    Thief,
    Weapon,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _street_level() -> Level:
    tiles = [
        [
            Tile(terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET)
            for _ in range(12)
        ]
        for _ in range(12)
    ]
    return Level(
        id="town_surface", name="Town", depth=0,
        width=12, height=12,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _make_player(
    world: World, x: int = 5, y: int = 5,
    gold: int = 100, dexterity: int = 1, wisdom: int = 1,
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Player": Player(gold=gold),
        "Stats": Stats(
            strength=1, dexterity=dexterity, constitution=1,
            intelligence=1, wisdom=wisdom, charisma=1,
        ),
        "Health": Health(current=20, maximum=20),
        "Inventory": Inventory(max_slots=11),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


def _make_thief(
    world: World, x: int, y: int, dexterity: int = 3,
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=1, dexterity=dexterity),
        "Health": Health(current=5, maximum=5),
        "AI": AI(behavior="thief", morale=5, faction="human"),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Villager"),
        "Errand": Errand(),
        "Thief": Thief(),
    })


def _give_item(
    world: World, player_id: int, registry_id: str = "sword",
) -> int:
    item_eid = world.create_entity({
        "Weapon": Weapon(damage="1d6"),
        "Description": Description(name=registry_id),
    })
    inv = world.get_component(player_id, "Inventory")
    inv.slots.append(item_eid)
    return item_eid


class TestPlayerHasStealable:
    def test_gold_counts(self):
        world = World()
        pid = _make_player(world, gold=10)
        assert player_has_stealable(world, pid)

    def test_empty_player_has_nothing(self):
        world = World()
        pid = _make_player(world, gold=0)
        assert not player_has_stealable(world, pid)

    def test_equipped_item_only_is_not_stealable(self):
        world = World()
        pid = _make_player(world, gold=0)
        item = _give_item(world, pid)
        equip = world.get_component(pid, "Equipment")
        equip.weapon = item
        assert not player_has_stealable(world, pid)

    def test_unequipped_item_is_stealable(self):
        world = World()
        pid = _make_player(world, gold=0)
        _give_item(world, pid)
        assert player_has_stealable(world, pid)


class TestPickpocketActionRolls:
    @pytest.mark.asyncio
    async def test_success_steals_gold(self):
        """theft success + any notice: gold leaves the purse."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=50, dexterity=0)
        tid = _make_thief(world, 5, 6, dexterity=5)
        action = PickpocketAction(actor=tid, target=pid)

        # Force: theft succeeds (roll 20), player notices (roll 20).
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[20, 20]):
            events = await action.execute(world, level)

        player = world.get_component(pid, "Player")
        assert player.gold < 50
        # Noticed path emits a message
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_failed_theft_leaves_gold_intact(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=50, dexterity=5)
        tid = _make_thief(world, 5, 6, dexterity=0)
        action = PickpocketAction(actor=tid, target=pid)

        # Force: theft fails (roll 1), player does not notice (roll 1).
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[1, 1]):
            events = await action.execute(world, level)

        player = world.get_component(pid, "Player")
        assert player.gold == 50
        # Unnoticed fail is silent
        assert events == []

    @pytest.mark.asyncio
    async def test_failed_theft_noticed_emits_message(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=50, dexterity=5, wisdom=5)
        tid = _make_thief(world, 5, 6, dexterity=0)
        action = PickpocketAction(actor=tid, target=pid)

        # theft fails (1), perception succeeds (20).
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[1, 20]):
            events = await action.execute(world, level)

        player = world.get_component(pid, "Player")
        assert player.gold == 50
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_silent_success_has_no_message(self):
        """theft success + miss notice: gold drops silently."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=50, dexterity=0, wisdom=0)
        tid = _make_thief(world, 5, 6, dexterity=5)
        action = PickpocketAction(actor=tid, target=pid)

        # theft succeeds (20), perception fails (1).
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[20, 1]):
            events = await action.execute(world, level)

        player = world.get_component(pid, "Player")
        assert player.gold < 50
        assert events == []


class TestPickpocketItemTheft:
    @pytest.mark.asyncio
    async def test_equipped_weapon_is_safe(self):
        """Equipped items never get stolen; only loose inventory."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=0, dexterity=0)
        weapon = _give_item(world, pid, "sword")
        equip = world.get_component(pid, "Equipment")
        equip.weapon = weapon
        tid = _make_thief(world, 5, 6, dexterity=5)
        action = PickpocketAction(actor=tid, target=pid)

        # theft succeeds, perception doesn't matter for this assertion
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[20, 1]):
            await action.execute(world, level)

        inv = world.get_component(pid, "Inventory")
        assert weapon in inv.slots
        assert equip.weapon == weapon

    @pytest.mark.asyncio
    async def test_loose_item_gets_stolen(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=0, dexterity=0)
        weapon = _give_item(world, pid, "sword")  # NOT equipped
        tid = _make_thief(world, 5, 6, dexterity=5)
        action = PickpocketAction(actor=tid, target=pid)

        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[20, 1]):
            await action.execute(world, level)

        inv = world.get_component(pid, "Inventory")
        assert weapon not in inv.slots


class TestThiefBehaviorDispatch:
    def test_thief_wanders_when_not_adjacent(self):
        """Far from the player, a thief uses the errand path."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 0, 0, gold=100)
        tid = _make_thief(world, 8, 8)

        action = decide_action(tid, world, level, pid)

        # Any non-None action that isn't a PickpocketAction
        assert not isinstance(action, PickpocketAction)

    def test_thief_attempts_when_adjacent_with_loot(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=100)
        tid = _make_thief(world, 5, 6)

        action = decide_action(tid, world, level, pid)

        assert isinstance(action, PickpocketAction)
        thief = world.get_component(tid, "Thief")
        assert thief.attempted_in_streak is True

    def test_thief_cooldown_prevents_double_attempt(self):
        """After one attempt the cooldown forces wander until the
        thief breaks adjacency again."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=100)
        tid = _make_thief(world, 5, 6)

        decide_action(tid, world, level, pid)
        second = decide_action(tid, world, level, pid)

        assert not isinstance(second, PickpocketAction)

    def test_thief_ignores_empty_target(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=0)  # empty
        tid = _make_thief(world, 5, 6)

        action = decide_action(tid, world, level, pid)

        assert not isinstance(action, PickpocketAction)
        thief = world.get_component(tid, "Thief")
        assert thief.attempted_in_streak is False

    def test_cooldown_resets_on_break(self):
        """Once the player steps away, the thief rearms for the
        next adjacency streak."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5, gold=100)
        tid = _make_thief(world, 5, 6)
        thief = world.get_component(tid, "Thief")
        thief.attempted_in_streak = True

        # Move player far away and tick once
        ppos = world.get_component(pid, "Position")
        ppos.x, ppos.y = 0, 0

        decide_action(tid, world, level, pid)

        assert thief.attempted_in_streak is False
