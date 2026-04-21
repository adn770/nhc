"""Tests for the blend-vs-flee reaction after a noticed pickpocket."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nhc.ai.behavior import decide_action
from nhc.core.actions import MoveAction, PickpocketAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Errand,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    Thief,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _street_level(width: int = 12, height: int = 12) -> Level:
    tiles = [
        [
            Tile(terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET)
            for _ in range(width)
        ]
        for _ in range(height)
    ]
    return Level(
        id="town_surface", name="Town", depth=0,
        width=width, height=height,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _make_player(
    world: World, x: int = 5, y: int = 5,
    gold: int = 100, dexterity: int = 0, wisdom: int = 10,
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


def _make_villager(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=0, dexterity=1),
        "Health": Health(current=4, maximum=4),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Villager"),
        "Errand": Errand(),
    })


class TestBlendReaction:
    @pytest.mark.asyncio
    async def test_blend_with_two_nearby_humanoids(self):
        """Two villagers within blend radius → thief becomes a
        villager in-place: behavior flips to 'errand' and the
        Thief component is stripped."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        tid = _make_thief(world, 5, 6)
        _make_villager(world, 5, 7)
        _make_villager(world, 6, 6)

        action = PickpocketAction(actor=tid, target=pid)
        # Force notice success.
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[1, 20]):
            await action.execute(world, level)

        ai = world.get_component(tid, "AI")
        assert ai.behavior == "errand"
        assert not world.has_component(tid, "Thief")

    @pytest.mark.asyncio
    async def test_unnoticed_attempt_does_not_trigger_reaction(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        tid = _make_thief(world, 5, 6)
        _make_villager(world, 5, 7)
        _make_villager(world, 6, 6)

        action = PickpocketAction(actor=tid, target=pid)
        # Notice fails.
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[20, 1]):
            await action.execute(world, level)

        ai = world.get_component(tid, "AI")
        assert ai.behavior == "thief"
        assert world.has_component(tid, "Thief")


class TestFleeReaction:
    @pytest.mark.asyncio
    async def test_flee_set_when_no_crowd(self):
        """Alone on the street, a noticed thief switches to fleeing
        with a flee target on the level perimeter."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        tid = _make_thief(world, 5, 6)

        action = PickpocketAction(actor=tid, target=pid)
        with patch("nhc.core.actions._pickpocket.d20",
                   side_effect=[1, 20]):
            await action.execute(world, level)

        thief = world.get_component(tid, "Thief")
        assert thief is not None
        assert thief.fleeing is True
        assert thief.flee_target_x is not None
        assert thief.flee_target_y is not None
        # Target sits on the level perimeter.
        tx, ty = thief.flee_target_x, thief.flee_target_y
        w, h = level.width, level.height
        assert tx in (0, w - 1) or ty in (0, h - 1)

    def test_fleeing_thief_moves_toward_edge(self):
        """A fleeing thief paths one step toward the flee target."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        tid = _make_thief(world, 5, 6)
        thief = world.get_component(tid, "Thief")
        thief.fleeing = True
        thief.flee_target_x = 0
        thief.flee_target_y = 0

        action = decide_action(tid, world, level, pid)

        assert isinstance(action, MoveAction)
        pos = world.get_component(tid, "Position")
        nx, ny = pos.x + action.dx, pos.y + action.dy
        before = max(abs(pos.x - 0), abs(pos.y - 0))
        after = max(abs(nx - 0), abs(ny - 0))
        assert after < before

    def test_fleeing_thief_despawns_at_edge(self):
        """Reaching the flee target destroys the thief entity."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        tid = _make_thief(world, 0, 0)
        thief = world.get_component(tid, "Thief")
        thief.fleeing = True
        thief.flee_target_x = 0
        thief.flee_target_y = 0

        decide_action(tid, world, level, pid)

        assert tid not in world._entities

    def test_fleeing_ignores_adjacent_player(self):
        """Once fleeing, a thief doesn't stop to pickpocket again."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 0, 0)
        tid = _make_thief(world, 1, 0)
        thief = world.get_component(tid, "Thief")
        thief.fleeing = True
        thief.flee_target_x = 11
        thief.flee_target_y = 0

        action = decide_action(tid, world, level, pid)

        assert not isinstance(action, PickpocketAction)
