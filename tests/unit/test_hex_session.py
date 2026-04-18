"""Tests for the HexSession helper class.

Verifies that hex overland and flower turn processing work
correctly when delegated from Game to HexSession.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nhc.core.hex_session import HexSession
from nhc.core.ecs import World
from nhc.entities.components import (
    Description,
    Equipment,
    Health,
    Hunger,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
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
    game.hex_world = MagicMock()
    game.hex_player_position = HexCoord(0, 0)
    game.pending_encounter = None
    game.encounter_rate = 0.15
    game._default_encounter_rate = 0.15
    game._encounter_rng = None
    game.encounters_disabled = False
    game.save_dir = None
    game.seed = 42
    game._knowledge = None
    game._character = None
    return game


# ── HexSession instantiation ──────────────────────────────────────


class TestHexSessionInit:
    def test_creates_with_game_reference(self):
        world = World()
        pid = world.create_entity({
            "Player": Player(gold=100),
        })
        game = _make_game_stub(world, pid)
        hs = HexSession(game)
        assert hs.game is game


# ── _maybe_stage_encounter ────────────────────────────────────────


class TestMaybeStageEncounter:
    def test_skips_when_encounters_disabled(self):
        world = World()
        pid = world.create_entity({"Player": Player(gold=0)})
        game = _make_game_stub(world, pid)
        game.encounters_disabled = True
        hs = HexSession(game)

        hs._maybe_stage_encounter(HexCoord(1, 0))
        assert game.pending_encounter is None

    def test_skips_when_encounter_already_pending(self):
        world = World()
        pid = world.create_entity({"Player": Player(gold=0)})
        game = _make_game_stub(world, pid)
        game.pending_encounter = "existing"
        hs = HexSession(game)

        hs._maybe_stage_encounter(HexCoord(1, 0))
        assert game.pending_encounter == "existing"

    def test_skips_when_no_hex_world(self):
        world = World()
        pid = world.create_entity({"Player": Player(gold=0)})
        game = _make_game_stub(world, pid)
        game.hex_world = None
        hs = HexSession(game)

        hs._maybe_stage_encounter(HexCoord(1, 0))
        assert game.pending_encounter is None


# ── _process_hex_turn ─────────────────────────────────────────────


class TestProcessHexTurn:
    @pytest.mark.asyncio
    async def test_disconnect_returns_disconnect(self):
        world = World()
        pid = world.create_entity({
            "Player": Player(gold=0),
            "Health": Health(current=10, maximum=10),
            "Hunger": Hunger(),
        })
        game = _make_game_stub(world, pid)
        game.renderer.get_input = AsyncMock(
            return_value=("disconnect", None),
        )
        hs = HexSession(game)

        result = await hs._process_hex_turn()
        assert result == "disconnect"


# ── _process_flower_turn ──────────────────────────────────────────


class TestProcessFlowerTurn:
    @pytest.mark.asyncio
    async def test_disconnect_returns_disconnect(self):
        world = World()
        pid = world.create_entity({
            "Player": Player(gold=0),
        })
        game = _make_game_stub(world, pid)
        game.renderer.get_input = AsyncMock(
            return_value=("disconnect", None),
        )
        hs = HexSession(game)

        result = await hs._process_flower_turn()
        assert result == "disconnect"


# ── Game delegates to HexSession ──────────────────────────────────


class TestGameDelegation:
    def test_game_has_hex_session_attribute(self):
        from nhc.core.game import Game
        assert hasattr(Game, 'apply_hex_step')
        assert hasattr(Game, '_process_hex_turn')
        assert hasattr(Game, '_process_flower_turn')
        assert hasattr(Game, '_init_hex_world')
