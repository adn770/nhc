"""Tests for dungeon-mode cheat death (respawn in place).

Milestone W3.
"""

from __future__ import annotations

import pytest

from nhc.core.death import DeathHandler
from nhc.core.ecs import World
from nhc.entities.components import Health, Inventory, Player
from nhc.hexcrawl.mode import GameMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(mode: GameMode) -> "Game":
    """Create a minimal Game with a player for cheat death testing."""
    from nhc.core.game import Game
    game = Game.__new__(Game)
    game.world = World()
    game.player_id = game.world.create_entity({
        "Health": Health(current=0, maximum=10),
        "Player": Player(gold=50),
        "Inventory": Inventory(slots=[]),
    })
    game.world_mode = mode
    game.hex_world = None
    game.hex_player_position = None
    game.level = None  # dungeon mode
    game._death = DeathHandler(game)
    return game


# ---------------------------------------------------------------------------
# allows_cheat_death_now
# ---------------------------------------------------------------------------


def test_dungeon_easy_allows_cheat_death() -> None:
    game = _make_game(GameMode.DUNGEON_EASY)
    assert game.allows_cheat_death_now() is True


def test_dungeon_medium_no_cheat_death() -> None:
    game = _make_game(GameMode.DUNGEON_MEDIUM)
    assert game.allows_cheat_death_now() is False


def test_dungeon_survival_no_cheat_death() -> None:
    game = _make_game(GameMode.DUNGEON_SURVIVAL)
    assert game.allows_cheat_death_now() is False


def test_hex_easy_allows_cheat_death() -> None:
    game = _make_game(GameMode.HEX_EASY)
    assert game.allows_cheat_death_now() is True


# ---------------------------------------------------------------------------
# cheat_death_dungeon
# ---------------------------------------------------------------------------


def test_dungeon_cheat_death_restores_hp() -> None:
    game = _make_game(GameMode.DUNGEON_EASY)
    health = game.world.get_component(game.player_id, "Health")
    assert health.current == 0
    game.cheat_death_dungeon()
    assert health.current == health.maximum


def test_dungeon_cheat_death_strips_gold() -> None:
    game = _make_game(GameMode.DUNGEON_EASY)
    player = game.world.get_component(game.player_id, "Player")
    assert player.gold == 50
    game.cheat_death_dungeon()
    assert player.gold == 0


def test_dungeon_cheat_death_strips_inventory() -> None:
    game = _make_game(GameMode.DUNGEON_EASY)
    # Add some items to inventory
    item1 = game.world.create_entity({})
    item2 = game.world.create_entity({})
    inv = game.world.get_component(game.player_id, "Inventory")
    inv.slots = [item1, item2]
    game.cheat_death_dungeon()
    assert inv.slots == []


def test_dungeon_cheat_death_rejects_non_easy() -> None:
    game = _make_game(GameMode.DUNGEON_MEDIUM)
    with pytest.raises(RuntimeError):
        game.cheat_death_dungeon()
