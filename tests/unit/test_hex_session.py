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
    game.world_type = mode.world_type
    game.difficulty = mode.difficulty
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

    @pytest.mark.asyncio
    async def test_enter_site_message_emitted_before_enter_site_runs(
        self, monkeypatch,
    ):
        """``hex.msg.enter_feature`` must reach the WebSocket before
        ``Game.enter_site`` begins executing — so that the spot-creature
        announcements that ``_update_fov`` emits inside ``enter_site``
        cannot reorder ahead of the entry line on the client.
        """
        from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
        from nhc.sites._types import SiteTier

        world = World()
        pid = world.create_entity({"Player": Player(gold=0)})
        game = _make_game_stub(world, pid)

        macro = HexCoord(0, 0)
        sub = HexCoord(0, 0)
        sub_cell = MagicMock()
        sub_cell.minor_feature = MinorFeatureType.NONE
        sub_cell.major_feature = HexFeatureType.CITY
        sub_cell.biome = "greenlands"
        cell = MagicMock()
        cell.feature = HexFeatureType.CITY
        cell.flower = MagicMock()
        cell.flower.cells = {sub: sub_cell}

        game.hex_world.exploring_hex = macro
        game.hex_world.exploring_sub_hex = sub
        game.hex_world.get_cell = MagicMock(return_value=cell)
        game.renderer.get_input = AsyncMock(
            return_value=("hex_enter", None),
        )

        # Capture the messages already emitted at the moment
        # enter_site is awaited.
        seen_at_enter_site = []

        async def fake_enter_site(*args, **kwargs):
            seen_at_enter_site.extend(
                call.args[0]
                for call in game.renderer.add_message.call_args_list
            )
            return True

        game.enter_site = fake_enter_site

        monkeypatch.setattr(
            "nhc.core.sub_hex_entry.resolve_sub_hex_entry",
            lambda c: ("site", "town", SiteTier.MEDIUM),
        )

        hs = HexSession(game)
        await hs._process_flower_turn()

        # The entry line must have landed in add_message calls
        # before enter_site started running.
        assert any(
            "enter the" in m or m.startswith("You enter")
            for m in seen_at_enter_site
        ), (
            "enter_feature message should be emitted BEFORE "
            f"enter_site runs; saw only: {seen_at_enter_site!r}"
        )


# ── Game delegates to HexSession ──────────────────────────────────


class TestGameDelegation:
    def test_game_has_hex_session_attribute(self):
        from nhc.core.game import Game
        assert hasattr(Game, 'apply_hex_step')
        assert hasattr(Game, '_process_hex_turn')
        assert hasattr(Game, '_process_flower_turn')
        assert hasattr(Game, '_init_hex_world')
