"""Tests for action resolution."""

import pytest

from nhc.core.actions import (
    BumpAction,
    DescendStairsAction,
    MeleeAttackAction,
    MoveAction,
    PickupItemAction,
    WaitAction,
)
from nhc.core.ecs import World
from nhc.core.events import CreatureAttacked, CreatureDied, ItemPickedUp, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    BlocksMovement,
    Consumable,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    Weapon,
)


def _make_test_level(width=10, height=10):
    """Create a simple floor-only level for testing."""
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    # Add walls around border
    for x in range(width):
        tiles[0][x].terrain = Terrain.WALL
        tiles[height - 1][x].terrain = Terrain.WALL
    for y in range(height):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][width - 1].terrain = Terrain.WALL

    return Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )


def _make_player(world, x=5, y=5):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=10, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(world, x=6, y=5, hp=4):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "Description": Description(name="Goblin"),
        "Renderable": Renderable(glyph="g"),
    })


class TestMoveAction:
    @pytest.mark.asyncio
    async def test_move_updates_position(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = MoveAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        await action.execute(world, level)

        pos = world.get_component(pid, "Position")
        assert pos.x == 6
        assert pos.y == 5

    @pytest.mark.asyncio
    async def test_move_into_wall_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=1, y=1)

        action = MoveAction(actor=pid, dx=-1, dy=0)  # Into wall at x=0
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_move_blocked_by_creature(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        _make_creature(world, x=6, y=5)

        action = MoveAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        # Move should be blocked, position unchanged
        pos = world.get_component(pid, "Position")
        assert pos.x == 5

    @pytest.mark.asyncio
    async def test_open_door_on_bump(self):
        world = World()
        level = _make_test_level()
        level.tiles[5][6].feature = "door_closed"
        pid = _make_player(world, x=5, y=5)

        action = MoveAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Door should be open, player stays put (opening costs the move)
        assert level.tiles[5][6].feature == "door_open"
        pos = world.get_component(pid, "Position")
        assert pos.x == 5


class TestMeleeAttackAction:
    @pytest.mark.asyncio
    async def test_attack_deals_damage(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5, hp=20)

        action = MeleeAttackAction(actor=pid, target=cid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Should have attack event
        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1

    @pytest.mark.asyncio
    async def test_killing_blow_destroys_entity(self):
        world = World()
        level = _make_test_level()
        # Give player high STR to guarantee kill
        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=20),
            "Health": Health(current=10, maximum=10),
            "Equipment": Equipment(),
            "Description": Description(name="You"),
        })
        cid = _make_creature(world, x=6, y=5, hp=1)

        action = MeleeAttackAction(actor=pid, target=cid)
        events = await action.execute(world, level)

        death_events = [e for e in events if isinstance(e, CreatureDied)]
        assert len(death_events) == 1
        # Entity should be destroyed
        assert world.get_component(cid, "Health") is None

    @pytest.mark.asyncio
    async def test_attack_non_adjacent_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=8, y=5)

        action = MeleeAttackAction(actor=pid, target=cid)
        assert not await action.validate(world, level)


class TestPickupItemAction:
    @pytest.mark.asyncio
    async def test_pickup_adds_to_inventory(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        inv = world.get_component(pid, "Inventory")
        assert item_id in inv.slots

        pickup_events = [e for e in events if isinstance(e, ItemPickedUp)]
        assert len(pickup_events) == 1

    @pytest.mark.asyncio
    async def test_pickup_auto_equips_weapon(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        await action.execute(world, level)

        equip = world.get_component(pid, "Equipment")
        assert equip.weapon == item_id

    @pytest.mark.asyncio
    async def test_pickup_full_inventory_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        inv = world.get_component(pid, "Inventory")
        inv.max_slots = 0  # Full

        item_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Description": Description(name="Thing"),
        })

        action = PickupItemAction(actor=pid, item=item_id)
        assert not await action.validate(world, level)


class TestBumpAction:
    @pytest.mark.asyncio
    async def test_bump_into_creature_attacks(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5, hp=20)

        action = BumpAction(actor=pid, dx=1, dy=0)
        events = await action.execute(world, level)

        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1

    @pytest.mark.asyncio
    async def test_bump_into_empty_moves(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = BumpAction(actor=pid, dx=1, dy=0)
        await action.execute(world, level)

        pos = world.get_component(pid, "Position")
        assert pos.x == 6


class TestDescendStairs:
    @pytest.mark.asyncio
    async def test_descend_on_stairs(self):
        world = World()
        level = _make_test_level()
        level.tiles[5][5].feature = "stairs_down"
        pid = _make_player(world, x=5, y=5)

        action = DescendStairsAction(actor=pid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        from nhc.core.events import GameWon
        won_events = [e for e in events if isinstance(e, GameWon)]
        assert len(won_events) == 1

    @pytest.mark.asyncio
    async def test_descend_not_on_stairs_invalid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = DescendStairsAction(actor=pid)
        assert not await action.validate(world, level)


class TestWaitAction:
    @pytest.mark.asyncio
    async def test_wait_always_valid(self):
        world = World()
        level = _make_test_level()
        pid = _make_player(world, x=5, y=5)

        action = WaitAction(actor=pid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)
        assert events == []
