"""Tests for chest entity: spawning, opening, loot drops."""

import pytest

from nhc.core.actions import BumpAction, OpenChestAction
from nhc.core.ecs import World
from nhc.core.events import CreatureAttacked, MessageEvent
from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.dungeon.populator import populate_level
from nhc.dungeon.room_types import assign_room_types
from nhc.entities.components import (
    AI, BlocksMovement, Description, Equipment, Health, Inventory,
    LootTable, Player, Position, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.utils.rng import get_rng, set_seed


def _make_level() -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world_with_chest(
    loot_entries: list[tuple] | None = None,
) -> tuple[World, int, int, Level]:
    """Create world with a player adjacent to a chest."""
    i18n_init("en")
    set_seed(42)
    world = World()
    level = _make_level()

    pid = world.create_entity({
        "Position": Position(x=5, y=5),
        "Player": Player(),
        "Health": Health(current=10, maximum=10),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })

    entries = loot_entries or [
        ("potion_healing", 1.0),
        ("gold", 1.0, "2d6"),
    ]
    chest_id = world.create_entity({
        "Position": Position(x=6, y=5),
        "Renderable": Renderable(glyph="=", color="bright_yellow", render_order=1),
        "Description": Description(name="Chest", short="a chest"),
        "LootTable": LootTable(entries=entries),
        "BlocksMovement": BlocksMovement(),
        "Chest": True,
    })

    return world, pid, chest_id, level


class TestChestFactory:
    def test_chest_has_required_components(self):
        i18n_init("en")
        EntityRegistry.discover_all()
        components = EntityRegistry.get_feature("chest")
        assert "Renderable" in components
        assert "Description" in components
        assert "LootTable" in components
        assert "Chest" in components
        assert components["Renderable"].glyph == "="

    def test_chest_blocks_movement(self):
        i18n_init("en")
        EntityRegistry.discover_all()
        components = EntityRegistry.get_feature("chest")
        assert "BlocksMovement" in components


class TestOpenChest:
    @pytest.mark.asyncio
    async def test_open_drops_loot(self):
        world, pid, cid, level = _make_world_with_chest()
        action = OpenChestAction(actor=pid, chest=cid)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        # Loot should be on the ground at chest position
        items_at = []
        for eid in list(world._entities):
            pos = world.get_component(eid, "Position")
            desc = world.get_component(eid, "Description")
            if pos and desc and pos.x == 6 and pos.y == 5 and eid != cid:
                items_at.append(eid)
        assert len(items_at) >= 1

    @pytest.mark.asyncio
    async def test_open_removes_chest_tag(self):
        world, pid, cid, level = _make_world_with_chest()
        action = OpenChestAction(actor=pid, chest=cid)
        await action.validate(world, level)
        await action.execute(world, level)

        # Chest tag should be gone (opened)
        assert not world.has_component(cid, "Chest")

    @pytest.mark.asyncio
    async def test_open_changes_glyph(self):
        world, pid, cid, level = _make_world_with_chest()
        action = OpenChestAction(actor=pid, chest=cid)
        await action.validate(world, level)
        await action.execute(world, level)

        r = world.get_component(cid, "Renderable")
        # Open chest should have a different glyph
        assert r.glyph != "="

    @pytest.mark.asyncio
    async def test_open_no_longer_blocks_movement(self):
        world, pid, cid, level = _make_world_with_chest()
        action = OpenChestAction(actor=pid, chest=cid)
        await action.validate(world, level)
        await action.execute(world, level)

        assert not world.has_component(cid, "BlocksMovement")

    @pytest.mark.asyncio
    async def test_cannot_open_twice(self):
        world, pid, cid, level = _make_world_with_chest()
        action = OpenChestAction(actor=pid, chest=cid)
        await action.validate(world, level)
        await action.execute(world, level)

        # Second open should fail validation
        action2 = OpenChestAction(actor=pid, chest=cid)
        assert not await action2.validate(world, level)

    @pytest.mark.asyncio
    async def test_must_be_adjacent(self):
        world, pid, cid, level = _make_world_with_chest()
        # Move player far away
        pos = world.get_component(pid, "Position")
        pos.x = 0
        pos.y = 0

        action = OpenChestAction(actor=pid, chest=cid)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_generates_message(self):
        world, pid, cid, level = _make_world_with_chest()
        action = OpenChestAction(actor=pid, chest=cid)
        await action.validate(world, level)
        events = await action.execute(world, level)

        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1

    @pytest.mark.asyncio
    async def test_empty_chest(self):
        """Chest with no loot still opens cleanly."""
        world, pid, cid, level = _make_world_with_chest(loot_entries=[])
        action = OpenChestAction(actor=pid, chest=cid)
        await action.validate(world, level)
        events = await action.execute(world, level)

        assert not world.has_component(cid, "Chest")


class TestBumpToOpenChest:
    @pytest.mark.asyncio
    async def test_bump_opens_chest(self):
        """Walking into a chest should open it, not attack it."""
        world, pid, cid, level = _make_world_with_chest()
        # Player at (5,5), chest at (6,5) — bump right
        action = BumpAction(actor=pid, dx=1, dy=0)
        await action.validate(world, level)
        events = await action.execute(world, level)

        # Chest should be opened
        assert not world.has_component(cid, "Chest")
        r = world.get_component(cid, "Renderable")
        assert r.glyph == "_"

    @pytest.mark.asyncio
    async def test_bump_still_attacks_creatures(self):
        """Bumping a creature should attack, not try to open it."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _make_level()

        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Player": Player(),
            "Health": Health(current=10, maximum=10),
            "Stats": Stats(strength=3, dexterity=2, constitution=2),
            "Inventory": Inventory(max_slots=12),
            "Equipment": Equipment(),
            "Description": Description(name="Hero"),
        })
        mob = world.create_entity({
            "Position": Position(x=6, y=5),
            "Health": Health(current=4, maximum=4),
            "Stats": Stats(strength=1),
            "AI": AI(behavior="aggressive_melee"),
            "BlocksMovement": BlocksMovement(),
            "Description": Description(name="Rat"),
            "Weapon": Weapon(damage="1d4"),
        })

        action = BumpAction(actor=pid, dx=1, dy=0)
        await action.validate(world, level)
        events = await action.execute(world, level)

        attacks = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attacks) >= 1


class TestChestSpawning:
    def test_populator_places_chests(self):
        """Dungeons should occasionally contain chests."""
        found_chest = False
        for seed in range(50):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(GenerationParams(width=80, height=50, depth=2))
            assign_room_types(level, get_rng())
            populate_level(level)
            for e in level.entities:
                if e.entity_id == "chest":
                    found_chest = True
                    break
            if found_chest:
                break
        assert found_chest, "No chests found in 50 generated levels"
