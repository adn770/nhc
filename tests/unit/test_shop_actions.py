"""Tests for shop buy/sell actions and bump resolution."""

from __future__ import annotations

import random

import pytest

from nhc.core.actions import BumpAction
from nhc.core.actions._shop import BuyAction, SellAction, ShopInteractAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent, ShopMenuEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    RegistryId,
    ShopInventory,
    Stats,
    Weapon,
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
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(gold=gold),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_merchant(world, x=6, y=5, stock=None):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="idle", morale=4, faction="human"),
        "Health": Health(current=9, maximum=9),
        "Description": Description(name="Merchant"),
        "ShopInventory": ShopInventory(stock=stock or ["sword", "healing_potion"]),
        "Renderable": Renderable(glyph="@"),
    })


# ── ShopInteractAction ──────────────────────────────────────────────

class TestShopInteractAction:
    @pytest.mark.asyncio
    async def test_opens_shop_menu(self):
        world = World()
        level = _make_level()
        player = _make_player(world)
        merchant = _make_merchant(world)

        action = ShopInteractAction(actor=player, merchant=merchant)
        assert await action.validate(world, level)
        events = await action.execute(world, level)
        assert len(events) == 1
        assert isinstance(events[0], ShopMenuEvent)
        assert events[0].merchant == merchant

    @pytest.mark.asyncio
    async def test_fails_when_not_adjacent(self):
        world = World()
        level = _make_level()
        player = _make_player(world, x=1, y=1)
        merchant = _make_merchant(world, x=8, y=8)

        action = ShopInteractAction(actor=player, merchant=merchant)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_fails_without_shop_inventory(self):
        world = World()
        level = _make_level()
        player = _make_player(world)
        # Merchant without ShopInventory
        merchant = world.create_entity({
            "Position": Position(x=6, y=5),
            "BlocksMovement": BlocksMovement(),
        })
        action = ShopInteractAction(actor=player, merchant=merchant)
        assert not await action.validate(world, level)


# ── BuyAction ────────────────────────────────────────────────────────

class TestBuyAction:
    @pytest.mark.asyncio
    async def test_buy_success(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=100)
        merchant = _make_merchant(world, stock=["sword"])

        action = BuyAction(actor=player, merchant=merchant, item_id="sword")
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Gold deducted
        p = world.get_component(player, "Player")
        assert p.gold == 90  # sword costs 10

        # Item in inventory
        inv = world.get_component(player, "Inventory")
        assert len(inv.slots) == 1

        # Stock decremented
        si = world.get_component(merchant, "ShopInventory")
        assert "sword" not in si.stock

        # Message event emitted
        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)

    @pytest.mark.asyncio
    async def test_buy_insufficient_gold(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=5)
        merchant = _make_merchant(world, stock=["chain_mail"])

        action = BuyAction(actor=player, merchant=merchant, item_id="chain_mail")
        assert not await action.validate(world, level)
        assert action.fail_reason == "cannot_afford"

    @pytest.mark.asyncio
    async def test_buy_full_inventory(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=1000)
        # Fill inventory to max
        inv = world.get_component(player, "Inventory")
        inv.max_slots = 2
        # Add 2 items taking 1 slot each
        for _ in range(2):
            item = world.create_entity({
                "Description": Description(name="junk"),
            })
            inv.slots.append(item)

        merchant = _make_merchant(world, stock=["dagger"])
        action = BuyAction(actor=player, merchant=merchant, item_id="dagger")
        assert not await action.validate(world, level)
        assert action.fail_reason == "inventory_full"

    @pytest.mark.asyncio
    async def test_buy_item_not_in_stock(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=1000)
        merchant = _make_merchant(world, stock=["sword"])

        action = BuyAction(actor=player, merchant=merchant, item_id="halberd")
        assert not await action.validate(world, level)
        assert action.fail_reason == "not_in_stock"


# ── SellAction ───────────────────────────────────────────────────────

class TestSellAction:
    @pytest.mark.asyncio
    async def test_sell_success(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=0)
        merchant = _make_merchant(world)

        # Add an item to the player's inventory
        item = world.create_entity({
            "Description": Description(name="Sword"),
            "RegistryId": RegistryId(item_id="sword"),
            "Weapon": Weapon(damage="1d8", type="melee", slots=2),
        })
        inv = world.get_component(player, "Inventory")
        inv.slots.append(item)

        action = SellAction(actor=player, merchant=merchant, item_entity=item)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Gold added (sword sell price = 10 // 2 = 5)
        p = world.get_component(player, "Player")
        assert p.gold == 5

        # Item removed from inventory
        assert item not in inv.slots

        # Message event
        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)

    @pytest.mark.asyncio
    async def test_sell_equipped_item_fails(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=0)
        merchant = _make_merchant(world)

        item = world.create_entity({
            "Description": Description(name="Sword"),
            "RegistryId": RegistryId(item_id="sword"),
            "Weapon": Weapon(damage="1d8", type="melee", slots=2),
        })
        inv = world.get_component(player, "Inventory")
        inv.slots.append(item)
        equip = world.get_component(player, "Equipment")
        equip.weapon = item

        action = SellAction(actor=player, merchant=merchant, item_entity=item)
        assert not await action.validate(world, level)
        assert action.fail_reason == "equipped"

    @pytest.mark.asyncio
    async def test_sell_item_not_in_inventory_fails(self):
        world = World()
        level = _make_level()
        player = _make_player(world, gold=0)
        merchant = _make_merchant(world)

        item = world.create_entity({
            "Description": Description(name="Sword"),
        })

        action = SellAction(actor=player, merchant=merchant, item_entity=item)
        assert not await action.validate(world, level)
        assert action.fail_reason == "not_in_inventory"


# ── Bump resolution ──────────────────────────────────────────────────

class TestBumpMerchant:
    @pytest.mark.asyncio
    async def test_bump_merchant_opens_shop(self):
        world = World()
        level = _make_level()
        player = _make_player(world, x=5, y=5)
        merchant = _make_merchant(world, x=6, y=5)

        action = BumpAction(actor=player, dx=1, dy=0)
        events = await action.execute(world, level)

        shop_events = [e for e in events if isinstance(e, ShopMenuEvent)]
        assert len(shop_events) == 1
        assert shop_events[0].merchant == merchant

    @pytest.mark.asyncio
    async def test_bump_creature_without_shop_attacks(self):
        """A creature without ShopInventory should trigger attack."""
        world = World()
        level = _make_level()
        player = _make_player(world, x=5, y=5)
        creature = world.create_entity({
            "Position": Position(x=6, y=5),
            "BlocksMovement": BlocksMovement(),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=10, maximum=10),
            "AI": AI(behavior="aggressive_melee", morale=8, faction="goblinoid"),
            "Description": Description(name="Goblin"),
            "Renderable": Renderable(glyph="g"),
        })

        action = BumpAction(actor=player, dx=1, dy=0)
        events = await action.execute(world, level)

        from nhc.core.events import CreatureAttacked
        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1


# ── Identification integration ───────────────────────────────────────

class TestShopIdentification:
    """Unidentified items should show appearance names in the shop."""

    def test_display_name_uses_appearance_for_unidentified(self):
        """ItemKnowledge.display_name should return appearance, not real."""
        from nhc.rules.identification import ItemKnowledge
        knowledge = ItemKnowledge(rng=random.Random(42))
        # healing_potion is identifiable and not yet identified
        name = knowledge.display_name("healing_potion")
        assert "Healing Potion" not in name
        assert "potion" in name.lower() or "Potion" in name

    def test_display_name_uses_real_for_identified(self):
        from nhc.rules.identification import ItemKnowledge
        knowledge = ItemKnowledge(rng=random.Random(42))
        knowledge.identify("healing_potion")
        name = knowledge.display_name("healing_potion")
        assert name == "Healing Potion"

    @pytest.mark.asyncio
    async def test_bought_potion_is_disguised(self):
        """After buying, unidentified potion should have appearance name."""
        from nhc.core.game import Game
        from nhc.rules.identification import ItemKnowledge

        world = World()
        level = _make_level()
        player = _make_player(world, gold=200)
        merchant = _make_merchant(world, stock=["healing_potion"])

        # Buy the potion
        action = BuyAction(actor=player, merchant=merchant,
                           item_id="healing_potion")
        assert await action.validate(world, level)
        await action.execute(world, level)

        inv = world.get_component(player, "Inventory")
        assert len(inv.slots) == 1
        item_eid = inv.slots[0]

        # Simulate what _shop_interaction does after buy
        knowledge = ItemKnowledge(rng=random.Random(42))
        # Build a components dict like _shop_interaction does
        comps = {
            "Description": world.get_component(item_eid, "Description"),
            "Renderable": world.get_component(item_eid, "Renderable"),
        }
        # Reuse the disguise logic
        if (knowledge.is_identifiable("healing_potion")
                and not knowledge.is_identified("healing_potion")):
            desc = comps["Description"]
            desc.name = knowledge.display_name("healing_potion")
            desc.short = knowledge.display_short("healing_potion")

        desc = world.get_component(item_eid, "Description")
        assert "Healing Potion" not in desc.name
        assert "potion" in desc.name.lower() or "Potion" in desc.name
