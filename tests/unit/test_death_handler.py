"""Tests for the DeathHandler helper class.

Verifies that death handling, cheat-death, and dungeon cheat-death
work correctly when delegated from Game to DeathHandler.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nhc.core.death import DeathHandler
from nhc.core.ecs import World
from nhc.entities.components import (
    Description,
    Health,
    Inventory,
    Player,
    Renderable,
)
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.i18n import init as i18n_init


@pytest.fixture(autouse=True)
def _setup():
    i18n_init("en")


def _make_game_stub(world, player_id, mode=GameMode.HEX_EASY):
    game = MagicMock()
    game.world = world
    game.player_id = player_id
    game.world_mode = mode
    game.renderer = MagicMock()
    game.hex_world = None
    game.hex_player_position = None
    return game


def _make_player(world, gold=100):
    return world.create_entity({
        "Player": Player(gold=gold),
        "Health": Health(current=0, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Description": Description(name="You"),
        "Renderable": Renderable(glyph="@"),
    })


# ── DeathHandler instantiation ────────────────────────────────────


class TestDeathHandlerInit:
    def test_creates_with_game_reference(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid)
        dh = DeathHandler(game)
        assert dh.game is game


# ── allows_cheat_death_now ────────────────────────────────────────


class TestAllowsCheatDeath:
    def test_hex_easy_allows(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.HEX_EASY)
        dh = DeathHandler(game)
        assert dh.allows_cheat_death_now() is True

    def test_hex_survival_denies(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.HEX_SURVIVAL)
        dh = DeathHandler(game)
        assert dh.allows_cheat_death_now() is False

    def test_dungeon_denies(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.DUNGEON)
        dh = DeathHandler(game)
        assert dh.allows_cheat_death_now() is False


# ── cheat_death_dungeon ───────────────────────────────────────────


class TestCheatDeathDungeon:
    def test_resets_gold_and_hp(self):
        world = World()
        pid = _make_player(world, gold=50)
        game = _make_game_stub(world, pid, GameMode.DUNGEON_EASY)
        dh = DeathHandler(game)

        dh.cheat_death_dungeon()

        player = world.get_component(pid, "Player")
        health = world.get_component(pid, "Health")
        assert player.gold == 0
        assert health.current == health.maximum

    def test_strips_inventory(self):
        world = World()
        pid = _make_player(world, gold=50)
        item = world.create_entity({
            "Description": Description(name="Sword"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item)
        game = _make_game_stub(world, pid, GameMode.DUNGEON_EASY)
        dh = DeathHandler(game)

        dh.cheat_death_dungeon()

        assert len(inv.slots) == 0

    def test_raises_in_wrong_mode(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.DUNGEON)
        dh = DeathHandler(game)

        with pytest.raises(RuntimeError):
            dh.cheat_death_dungeon()


# ── handle_player_death ───────────────────────────────────────────


class TestHandlePlayerDeath:
    def test_returns_false_when_no_cheat_death(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.DUNGEON)
        dh = DeathHandler(game)

        assert dh.handle_player_death() is False

    def test_returns_false_when_no_menu(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.HEX_EASY)
        # Remove show_selection_menu to simulate headless
        del game.renderer.show_selection_menu
        dh = DeathHandler(game)

        assert dh.handle_player_death() is False

    def test_returns_false_on_permadeath_choice(self):
        world = World()
        pid = _make_player(world)
        game = _make_game_stub(world, pid, GameMode.HEX_EASY)
        game.renderer.show_selection_menu.return_value = 0
        dh = DeathHandler(game)

        assert dh.handle_player_death() is False
