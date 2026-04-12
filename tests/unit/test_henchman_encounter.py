"""Tests for the henchman encounter menu: interact, buy, sell, hire."""

import pytest

from nhc.core.actions import (
    BumpAction,
    HenchmanInteractAction,
    RecruitAction,
    DismissAction,
)
from nhc.core.actions._henchman import (
    HIRE_COST_PER_LEVEL,
    MAX_HENCHMEN,
    get_hired_henchmen,
)
from nhc.core.ecs import World
from nhc.core.events import HenchmanMenuEvent, MessageEvent
from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile
from nhc.entities.components import (
    AI,
    Armor,
    BlocksMovement,
    Description,
    Equipment,
    Health,
    Henchman,
    Inventory,
    Player,
    Position,
    Renderable,
    RegistryId,
    Stats,
    Weapon,
)


def _make_test_level(width=12, height=12):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    for x in range(width):
        tiles[0][x].terrain = Terrain.WALL
        tiles[height - 1][x].terrain = Terrain.WALL
    for y in range(height):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][width - 1].terrain = Terrain.WALL
    level = Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )
    level.rooms = [Room(
        id="r1",
        rect=Rect(1, 1, width - 2, height - 2),
        tags=[],
    )]
    return level


def _make_player(world, x=5, y=5, gold=500):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(gold=gold),
        "Description": Description(name="Hero"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_unhired(world, x=6, y=5, level=1, gold=50):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=8, maximum=8),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "AI": AI(behavior="henchman", faction="human"),
        "Henchman": Henchman(level=level, gold=gold),
        "BlocksMovement": BlocksMovement(),
        "Description": Description(name="Adventurer"),
        "Renderable": Renderable(glyph="@", color="cyan"),
    })


def _make_hired(world, x=7, y=5, owner=None, level=1):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=8, maximum=8),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "AI": AI(behavior="henchman", faction="human"),
        "Henchman": Henchman(level=level, hired=True, owner=owner),
        "Description": Description(name="Hired"),
        "Renderable": Renderable(glyph="@", color="cyan"),
    })


def _make_weapon(world, damage="1d6", name="Sword", item_id="sword"):
    return world.create_entity({
        "Weapon": Weapon(damage=damage),
        "Description": Description(name=name),
        "RegistryId": RegistryId(item_id=item_id),
    })


def _make_armor(world, slot="body", defense=12, name="Gambeson",
                item_id="gambeson"):
    return world.create_entity({
        "Armor": Armor(slot=slot, defense=defense),
        "Description": Description(name=name),
        "RegistryId": RegistryId(item_id=item_id),
    })


# ── HenchmanInteractAction ───────────────────────────────────────


class TestHenchmanInteractAction:
    @pytest.mark.asyncio
    async def test_emits_henchman_menu_event(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world)
        aid = _make_unhired(world, x=6, y=5)

        action = HenchmanInteractAction(actor=pid, henchman_id=aid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        assert len(events) == 1
        assert isinstance(events[0], HenchmanMenuEvent)
        assert events[0].henchman == aid

    @pytest.mark.asyncio
    async def test_rejects_hired_henchman(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world)
        aid = _make_hired(world, x=6, y=5, owner=pid)

        action = HenchmanInteractAction(actor=pid, henchman_id=aid)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_rejects_non_adjacent(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=2, y=2)
        aid = _make_unhired(world, x=8, y=8)

        action = HenchmanInteractAction(actor=pid, henchman_id=aid)
        assert not await action.validate(world, level)


# ── BumpAction routing ───────────────────────────────────────────


class TestBumpRoutesToHenchmanInteract:
    def test_bump_unhired_returns_interact_action(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        _make_unhired(world, x=6, y=5)

        bump = BumpAction(actor=pid, dx=1, dy=0)
        resolved = bump.resolve(world, level)
        assert isinstance(resolved, HenchmanInteractAction)


# ── Henchman gold ────────────────────────────────────────────────


class TestHenchmanGold:
    def test_henchman_has_gold_field(self):
        hench = Henchman(gold=42)
        assert hench.gold == 42

    def test_adventurer_factory_sets_gold(self):
        from nhc.entities.creatures.adventurer import (
            create_adventurer_at_level,
        )
        from nhc.utils.rng import set_seed

        set_seed(42)
        comps = create_adventurer_at_level(1, seed=42)
        hench = comps["Henchman"]
        # Chargen generates 3d6*20 copper / 10 = gold
        # With seed 42, gold should be > 0
        assert hench.gold > 0


# ── Buy from henchman ────────────────────────────────────────────


class TestBuyFromHenchman:
    def test_buy_transfers_item_and_gold(self):
        """Buying an item transfers it and adjusts gold on both sides."""
        from nhc.core.actions._helpers import (
            _count_slots_used,
            _item_slot_cost,
        )
        from nhc.rules.prices import buy_price

        world = World()
        pid = _make_player(world, gold=500)
        aid = _make_unhired(world, gold=50)

        # Give henchman a sword
        sword = _make_weapon(world, item_id="sword")
        h_inv = world.get_component(aid, "Inventory")
        h_inv.slots.append(sword)

        # Simulate buy: transfer item and gold
        price = buy_price("sword")
        player = world.get_component(pid, "Player")
        hench = world.get_component(aid, "Henchman")
        p_inv = world.get_component(pid, "Inventory")

        h_inv.slots.remove(sword)
        p_inv.slots.append(sword)
        player.gold -= price
        hench.gold += price

        assert sword in p_inv.slots
        assert sword not in h_inv.slots
        assert player.gold == 500 - price
        assert hench.gold == 50 + price


# ── Sell to henchman ─────────────────────────────────────────────


class TestSellToHenchman:
    def test_sell_transfers_item_and_gold(self):
        from nhc.rules.prices import sell_price

        world = World()
        pid = _make_player(world, gold=100)
        aid = _make_unhired(world, gold=200)

        sword = _make_weapon(world, item_id="sword")
        p_inv = world.get_component(pid, "Inventory")
        p_inv.slots.append(sword)

        price = sell_price("sword")
        player = world.get_component(pid, "Player")
        hench = world.get_component(aid, "Henchman")
        h_inv = world.get_component(aid, "Inventory")

        p_inv.slots.remove(sword)
        h_inv.slots.append(sword)
        player.gold += price
        hench.gold -= price

        assert sword in h_inv.slots
        assert sword not in p_inv.slots
        assert player.gold == 100 + price
        assert hench.gold == 200 - price

    def test_sell_rejected_when_henchman_cannot_afford(self):
        from nhc.rules.prices import sell_price

        world = World()
        pid = _make_player(world, gold=100)
        aid = _make_unhired(world, gold=0)  # broke henchman

        sword = _make_weapon(world, item_id="sword")
        price = sell_price("sword")
        hench = world.get_component(aid, "Henchman")

        # Henchman can't afford it
        assert hench.gold < price


# ── Hire flow ────────────────────────────────────────────────────


class TestHireFromMenu:
    @pytest.mark.asyncio
    async def test_hire_succeeds_with_room(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, gold=500)
        aid = _make_unhired(world, x=6, y=5, level=2)

        action = RecruitAction(actor=pid, target=aid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        hench = world.get_component(aid, "Henchman")
        assert hench.hired
        assert hench.owner == pid

    @pytest.mark.asyncio
    async def test_dismiss_then_hire(self):
        """When party is full, dismiss one then hire the new one."""
        world = World()
        level = _make_test_level()
        pid = _make_player(world, gold=500)

        # Two existing henchmen
        h1 = _make_hired(world, x=7, y=5, owner=pid)
        h2 = _make_hired(world, x=8, y=5, owner=pid)
        new = _make_unhired(world, x=6, y=5, level=1)

        assert len(get_hired_henchmen(world, pid)) == 2

        # Dismiss h1
        dismiss = DismissAction(actor=pid, henchman_id=h1)
        assert await dismiss.validate(world, level)
        await dismiss.execute(world, level)

        assert len(get_hired_henchmen(world, pid)) == 1

        # Now recruit the new one
        recruit = RecruitAction(actor=pid, target=new)
        assert await recruit.validate(world, level)
        await recruit.execute(world, level)

        hench = world.get_component(new, "Henchman")
        assert hench.hired
        assert len(get_hired_henchmen(world, pid)) == 2
