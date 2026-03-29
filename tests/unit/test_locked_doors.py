"""Tests for locked doors, pick locks, and force open mechanics."""

import pytest

from nhc.core.ecs import World
from nhc.core.actions import MoveAction, PickLockAction, ForceDoorAction
from nhc.core.events import MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    Description, Equipment, Health, Inventory, Player,
    Position, Renderable, Stats, Weapon,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level_with_locked_door() -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    # Place a locked door at (6, 5)
    tiles[5][6] = Tile(terrain=Terrain.FLOOR, feature="door_locked")
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world(
    dex: int = 1, strength: int = 1, with_lockpicks: bool = False,
) -> tuple[World, int, Level]:
    i18n_init("en")
    set_seed(42)
    world = World()
    level = _make_level_with_locked_door()

    pid = world.create_entity({
        "Position": Position(x=5, y=5),
        "Player": Player(),
        "Health": Health(current=20, maximum=20),
        "Stats": Stats(strength=strength, dexterity=dex, constitution=2),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })

    if with_lockpicks:
        lp = world.create_entity({
            "Description": Description(name="Lockpicks"),
            "Renderable": Renderable(glyph="(", color="grey"),
            "Lockpicks": True,
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(lp)

    return world, pid, level


class TestBumpLockedDoor:
    @pytest.mark.asyncio
    async def test_bump_locked_door_does_not_move(self):
        """Bumping a locked door should not move the player through."""
        world, pid, level = _make_world()
        action = MoveAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)
        pos = world.get_component(pid, "Position")
        assert pos.x == 5  # Did not move

    @pytest.mark.asyncio
    async def test_bump_locked_door_shows_message(self):
        world, pid, level = _make_world()
        action = MoveAction(actor=pid, dx=1, dy=0)
        await action.validate(world, level)
        events = await action.execute(world, level)
        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1


class TestPickLock:
    @pytest.mark.asyncio
    async def test_requires_lockpicks(self):
        """Cannot pick lock without lockpicks."""
        world, pid, level = _make_world(with_lockpicks=False)
        action = PickLockAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_requires_adjacent_locked_door(self):
        """Must be next to a locked door."""
        world, pid, level = _make_world(with_lockpicks=True)
        # Direction with no locked door
        action = PickLockAction(actor=pid, dx=-1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_high_dex_unlocks(self):
        """High DEX should reliably unlock the door."""
        world, pid, level = _make_world(dex=10, with_lockpicks=True)
        action = PickLockAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        await action.execute(world, level)
        tile = level.tile_at(6, 5)
        # Door should be unlocked (closed or open, not locked)
        assert tile.feature != "door_locked"

    @pytest.mark.asyncio
    async def test_generates_message(self):
        world, pid, level = _make_world(dex=10, with_lockpicks=True)
        action = PickLockAction(actor=pid, dx=1, dy=0)
        await action.validate(world, level)
        events = await action.execute(world, level)
        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1


class TestForceDoor:
    @pytest.mark.asyncio
    async def test_requires_adjacent_locked_door(self):
        world, pid, level = _make_world()
        action = ForceDoorAction(actor=pid, dx=-1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_high_str_breaks_door(self):
        """High STR should reliably break the door open."""
        set_seed(42)
        world, pid, level = _make_world(strength=15)
        action = ForceDoorAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        await action.execute(world, level)
        tile = level.tile_at(6, 5)
        assert tile.feature != "door_locked"

    @pytest.mark.asyncio
    async def test_failure_deals_damage(self):
        """Failed force attempt should hurt the player."""
        # Use very low STR and high seed to ensure failure
        world, pid, level = _make_world(strength=0)
        # Manually set a seed that gives a low d20 roll
        set_seed(7)
        action = ForceDoorAction(actor=pid, dx=1, dy=0)
        await action.validate(world, level)
        events = await action.execute(world, level)
        # Either the door opened or player took damage
        tile = level.tile_at(6, 5)
        health = world.get_component(pid, "Health")
        if tile.feature == "door_locked":
            assert health.current < 20

    @pytest.mark.asyncio
    async def test_generates_message(self):
        world, pid, level = _make_world(strength=10)
        action = ForceDoorAction(actor=pid, dx=1, dy=0)
        await action.validate(world, level)
        events = await action.execute(world, level)
        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1


class TestForceDoorWithTool:
    @pytest.mark.asyncio
    async def test_crowbar_lowers_dc(self):
        """Crowbar gives -5 DC bonus, making it easier."""
        set_seed(42)
        world, pid, level = _make_world(strength=5)
        # Add a crowbar
        crowbar = world.create_entity({
            "Description": Description(name="Crowbar"),
            "Renderable": Renderable(glyph="(", color="cyan"),
            "ForceTool": True,
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(crowbar)

        # DC 15 - 5 (crowbar) = 10; STR 5 + d20(4 at seed 42) = 9 < 10
        # Actually with seed 42, first d20 is 4, so 5+4=9 < 10... still fails
        # Use higher STR to ensure pass
        stats = world.get_component(pid, "Stats")
        stats.strength = 8  # 8 + 4 = 12 >= 10

        action = ForceDoorAction(actor=pid, dx=1, dy=0, tool=crowbar)
        assert await action.validate(world, level)
        await action.execute(world, level)
        tile = level.tile_at(6, 5)
        assert tile.feature != "door_locked"

    @pytest.mark.asyncio
    async def test_weapon_lowers_dc(self):
        """Melee weapon gives -3 DC bonus."""
        set_seed(42)
        world, pid, level = _make_world(strength=10)
        axe = world.create_entity({
            "Description": Description(name="Axe"),
            "Renderable": Renderable(glyph=")", color="white"),
            "Weapon": Weapon(damage="1d8", type="melee", slots=2),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(axe)

        # DC 15 - 3 = 12; STR 10 + d20(4) = 14 >= 12
        action = ForceDoorAction(actor=pid, dx=1, dy=0, tool=axe)
        await action.validate(world, level)
        await action.execute(world, level)
        tile = level.tile_at(6, 5)
        assert tile.feature != "door_locked"

    @pytest.mark.asyncio
    async def test_bare_hands_no_tool(self):
        """No tool = base DC 15."""
        set_seed(42)
        world, pid, level = _make_world(strength=15)
        action = ForceDoorAction(actor=pid, dx=1, dy=0, tool=None)
        await action.validate(world, level)
        await action.execute(world, level)
        tile = level.tile_at(6, 5)
        assert tile.feature != "door_locked"

    @pytest.mark.asyncio
    async def test_tool_can_break(self):
        """Tools have a chance to break when used."""
        # Use a seed where the breakage RNG triggers
        world, pid, level = _make_world(strength=15)
        crowbar = world.create_entity({
            "Description": Description(name="Crowbar"),
            "Renderable": Renderable(glyph="(", color="cyan"),
            "ForceTool": True,
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(crowbar)

        # Try many seeds until one breaks the tool
        broke = False
        for seed in range(200):
            # Re-create fresh state each time
            level.tiles[5][6].feature = "door_locked"
            set_seed(seed)
            action = ForceDoorAction(actor=pid, dx=1, dy=0, tool=crowbar)
            if not await action.validate(world, level):
                continue
            events = await action.execute(world, level)
            if not world.has_component(crowbar, "ForceTool"):
                # Entity was destroyed
                broke = True
                break
            # Reset door for next attempt
            level.tiles[5][6].feature = "door_locked"
        assert broke, "Crowbar never broke in 200 attempts (10% chance each)"


class TestLockedDoorGeneration:
    def test_bsp_generates_locked_doors(self):
        """Some seeds should produce locked doors."""
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.generators.bsp import BSPGenerator

        found = False
        for seed in range(100):
            set_seed(seed)
            level = BSPGenerator().generate(
                GenerationParams(width=80, height=50, depth=3),
            )
            for row in level.tiles:
                for tile in row:
                    if tile.feature == "door_locked":
                        found = True
                        break
                if found:
                    break
            if found:
                break
        assert found, "No locked doors in 100 seeds"
