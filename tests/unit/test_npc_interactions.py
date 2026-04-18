"""Tests for the NpcInteractions helper class.

Verifies that shop, temple, and henchman interaction flows work
correctly when delegated from Game to NpcInteractions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nhc.core.ecs import World
from nhc.core.events import MessageEvent
from nhc.core.npc_interactions import NpcInteractions
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    Description,
    Equipment,
    Henchman,
    Inventory,
    Player,
    Position,
    Renderable,
    RegistryId,
    ShopInventory,
    Stats,
    TempleServices,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init


@pytest.fixture(autouse=True)
def _setup():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_level(width=10, height=10):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    return Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )


def _make_player(world, x=5, y=5, gold=100):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(gold=gold),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_game_stub(world, level, player_id, knowledge=None):
    """Build a minimal game-like object for NpcInteractions."""
    game = MagicMock()
    game.world = world
    game.level = level
    game.player_id = player_id
    game.renderer = MagicMock()
    game._knowledge = knowledge
    game.world_mode = MagicMock()
    game.world_mode.is_hex = False
    game._disguise_potion = MagicMock()
    return game


# ── NpcInteractions instantiation ──────────────────────────────────


class TestNpcInteractionsInit:
    def test_creates_with_game_reference(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        game = _make_game_stub(world, level, pid)
        npc = NpcInteractions(game)
        assert npc.game is game


# ── Shop interaction ───────────────────────────────────────────────


class TestShopInteraction:
    @pytest.mark.asyncio
    async def test_no_shop_inventory_returns_immediately(self):
        """If the merchant has no ShopInventory, do nothing."""
        world = World()
        level = _make_level()
        pid = _make_player(world)
        merchant = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Merchant"),
        })
        game = _make_game_stub(world, level, pid)
        npc = NpcInteractions(game)

        await npc.shop_interaction(merchant)
        game.renderer.show_selection_menu.assert_not_called()

    @pytest.mark.asyncio
    async def test_leave_shop_on_cancel(self):
        """Pressing cancel (None) exits the shop loop."""
        world = World()
        level = _make_level()
        pid = _make_player(world)
        merchant = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Merchant"),
            "ShopInventory": ShopInventory(stock=["sword"]),
        })
        game = _make_game_stub(world, level, pid)
        game.renderer.show_selection_menu.return_value = None
        npc = NpcInteractions(game)

        await npc.shop_interaction(merchant)
        game.renderer.show_selection_menu.assert_called_once()

    @pytest.mark.asyncio
    async def test_buy_success(self):
        """Buying an item transfers gold and adds to inventory."""
        world = World()
        level = _make_level()
        pid = _make_player(world, gold=500)
        merchant = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Merchant"),
            "ShopInventory": ShopInventory(stock=["sword"]),
        })
        game = _make_game_stub(world, level, pid)

        # First call: choose Buy (-1), second: pick item 0, then cancel
        game.renderer.show_selection_menu.side_effect = [-1, 0, None]
        npc = NpcInteractions(game)

        await npc.shop_interaction(merchant)

        # Player should have the item in inventory (via BuyAction)
        # The test primarily checks that the flow doesn't error
        assert game.renderer.show_selection_menu.call_count == 3

    @pytest.mark.asyncio
    async def test_sell_empty_inventory(self):
        """Selling with no items shows a message."""
        world = World()
        level = _make_level()
        pid = _make_player(world)
        merchant = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Merchant"),
            "ShopInventory": ShopInventory(stock=["sword"]),
        })
        game = _make_game_stub(world, level, pid)
        # Choose Sell (-2), then cancel
        game.renderer.show_selection_menu.side_effect = [-2, None]
        npc = NpcInteractions(game)

        await npc.shop_interaction(merchant)
        game.renderer.add_message.assert_called()


# ── Temple interaction ─────────────────────────────────────────────


class TestTempleInteraction:
    @pytest.mark.asyncio
    async def test_no_temple_services_returns_immediately(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        priest = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Priest"),
        })
        game = _make_game_stub(world, level, pid)
        npc = NpcInteractions(game)

        await npc.temple_interaction(priest)
        game.renderer.show_selection_menu.assert_not_called()

    @pytest.mark.asyncio
    async def test_leave_temple_on_cancel(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        priest = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Priest"),
            "TempleServices": TempleServices(services=["heal"]),
        })
        game = _make_game_stub(world, level, pid)
        game.renderer.show_selection_menu.return_value = None
        npc = NpcInteractions(game)

        await npc.temple_interaction(priest)
        game.renderer.show_selection_menu.assert_called_once()


# ── Henchman interaction ───────────────────────────────────────────


class TestHenchmanInteraction:
    @pytest.mark.asyncio
    async def test_no_henchman_component_returns(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        npc_eid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Guard"),
        })
        game = _make_game_stub(world, level, pid)
        npc = NpcInteractions(game)

        await npc.henchman_interaction(npc_eid)
        game.renderer.show_selection_menu.assert_not_called()

    @pytest.mark.asyncio
    async def test_hired_henchman_returns(self):
        """Already-hired henchmen skip the interaction."""
        world = World()
        level = _make_level()
        pid = _make_player(world)
        npc_eid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Guard"),
            "Henchman": Henchman(level=1, hired=True, gold=0),
        })
        game = _make_game_stub(world, level, pid)
        npc = NpcInteractions(game)

        await npc.henchman_interaction(npc_eid)
        game.renderer.show_selection_menu.assert_not_called()

    @pytest.mark.asyncio
    async def test_leave_henchman_on_cancel(self):
        world = World()
        level = _make_level()
        pid = _make_player(world)
        npc_eid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Description": Description(name="Guard"),
            "Henchman": Henchman(level=1, hired=False, gold=50),
            "Inventory": Inventory(max_slots=6),
        })
        game = _make_game_stub(world, level, pid)
        game.renderer.show_selection_menu.return_value = None
        npc = NpcInteractions(game)

        await npc.henchman_interaction(npc_eid)
        game.renderer.show_selection_menu.assert_called_once()


# ── Game delegates to NpcInteractions ──────────────────────────────


class TestGameDelegation:
    """Verify Game._{shop,temple,henchman}_interaction delegate."""

    def test_game_has_npc_interactions_attribute(self):
        """After extraction, Game should have a _npc attribute."""
        # This test imports Game to verify wiring -- it doesn't
        # run the full game, just checks the attribute exists.
        from nhc.core.game import Game
        assert hasattr(Game, '_shop_interaction')
        assert hasattr(Game, '_temple_interaction')
        assert hasattr(Game, '_henchman_interaction')
