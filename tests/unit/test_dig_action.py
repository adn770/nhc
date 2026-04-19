"""Tests for the dig action and digging tool items."""

from unittest.mock import patch

import pytest

from nhc.core.actions import DigAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    Description, DiggingTool, Equipment, Health, Inventory, Player,
    Position, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level_with_wall() -> Level:
    """10x10 level with a WALL at (6, 5) and FLOOR everywhere else."""
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    tiles[5][6] = Tile(terrain=Terrain.WALL)
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world(
    strength: int = 3, with_tool: bool = True, equipped: bool = True,
    tool_bonus: int = 0,
) -> tuple[World, int, Level, int | None]:
    """Create a world with player at (5,5) and optional digging tool."""
    i18n_init("en")
    set_seed(42)
    world = World()
    level = _make_level_with_wall()

    pid = world.create_entity({
        "Position": Position(x=5, y=5),
        "Player": Player(),
        "Health": Health(current=20, maximum=20),
        "Stats": Stats(strength=strength, dexterity=1, constitution=2),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })

    tool_id = None
    if with_tool:
        tool_id = world.create_entity({
            "Description": Description(name="Pick"),
            "Renderable": Renderable(glyph="(", color="white"),
            "Weapon": Weapon(damage="1d4", type="melee", slots=1),
            "DiggingTool": DiggingTool(bonus=tool_bonus),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(tool_id)
        if equipped:
            equip = world.get_component(pid, "Equipment")
            equip.weapon = tool_id

    return world, pid, level, tool_id


class TestDigActionValidation:
    @pytest.mark.asyncio
    async def test_valid_dig_adjacent_wall(self):
        """Dig validates when wielding a DiggingTool near a WALL."""
        world, pid, level, _ = _make_world()
        action = DigAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_no_adjacent_wall(self):
        """Dig fails validation when no WALL in target direction."""
        world, pid, level, _ = _make_world()
        action = DigAction(actor=pid, dx=-1, dy=0)  # FLOOR at (4, 5)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_no_tool_equipped(self):
        """Dig fails when no weapon is equipped."""
        world, pid, level, _ = _make_world(with_tool=False)
        action = DigAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_tool_not_wielded(self):
        """Dig fails when tool is in inventory but not equipped."""
        world, pid, level, _ = _make_world(equipped=False)
        action = DigAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_weapon_without_digging(self):
        """Dig fails when wielding a weapon without DiggingTool."""
        world, pid, level, _ = _make_world(with_tool=False)
        # Equip a sword (no DiggingTool component)
        sword = world.create_entity({
            "Description": Description(name="Sword"),
            "Weapon": Weapon(damage="1d8", type="melee"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(sword)
        equip = world.get_component(pid, "Equipment")
        equip.weapon = sword

        action = DigAction(actor=pid, dx=1, dy=0)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_valid_dig_adjacent_void(self):
        """Autodig: digging into VOID is allowed."""
        world, pid, level, _ = _make_world()
        # Replace the wall at (6, 5) with VOID.
        level.tiles[5][6] = Tile(terrain=Terrain.VOID)
        action = DigAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_dig_into_floor(self):
        """Digging into an existing floor is still rejected."""
        world, pid, level, _ = _make_world()
        action = DigAction(actor=pid, dx=-1, dy=0)  # FLOOR at (4, 5)
        assert not await action.validate(world, level)


class TestDigActionVoidExecution:
    @pytest.mark.asyncio
    async def test_success_converts_void_to_floor(self):
        """Autodig: a successful STR check converts VOID to FLOOR."""
        world, pid, level, _ = _make_world(strength=6, tool_bonus=5)
        level.tiles[5][6] = Tile(terrain=Terrain.VOID)

        action = DigAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)
        with patch("nhc.core.actions._interaction.d20", return_value=15):
            await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.terrain == Terrain.FLOOR


class TestDigActionExecution:
    @pytest.mark.asyncio
    async def test_success_converts_wall_to_floor(self):
        """On a successful STR check, WALL becomes FLOOR."""
        world, pid, level, _ = _make_world(strength=6, tool_bonus=5)
        action = DigAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)

        # Force d20 to roll high enough to guarantee success
        with patch("nhc.core.actions._interaction.d20", return_value=15):
            events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.terrain == Terrain.FLOOR
        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("break" in m.lower() or "crumble" in m.lower()
                    for m in msgs)

    @pytest.mark.asyncio
    async def test_failure_wall_remains(self):
        """On a failed STR check, the wall stays."""
        world, pid, level, _ = _make_world(strength=1, tool_bonus=0)
        action = DigAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)

        with patch("nhc.core.actions._interaction.d20", return_value=1):
            events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.terrain == Terrain.WALL
        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1

    @pytest.mark.asyncio
    async def test_tool_bonus_helps_check(self):
        """High tool bonus should make digging easier."""
        # STR 1 + bonus 5 + roll 7 = 13 >= DC 12 → success
        world, pid, level, _ = _make_world(strength=1, tool_bonus=5)
        action = DigAction(actor=pid, dx=1, dy=0)
        assert await action.validate(world, level)

        with patch("nhc.core.actions._interaction.d20", return_value=7):
            await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.terrain == Terrain.FLOOR

    @pytest.mark.asyncio
    async def test_clears_features_on_dig(self):
        """Digging should clear any feature on the wall tile."""
        world, pid, level, _ = _make_world(strength=6, tool_bonus=5)
        tile = level.tile_at(6, 5)
        tile.feature = "some_feature"

        action = DigAction(actor=pid, dx=1, dy=0)
        with patch("nhc.core.actions._interaction.d20", return_value=20):
            await action.execute(world, level)

        assert tile.terrain == Terrain.FLOOR
        assert tile.feature is None or tile.feature == ""

    @pytest.mark.asyncio
    async def test_dug_wall_marks_tile(self):
        """Successful dig sets dug_wall and marks CORRIDOR surface."""
        world, pid, level, _ = _make_world(strength=6, tool_bonus=5)
        action = DigAction(actor=pid, dx=1, dy=0)
        with patch("nhc.core.actions._interaction.d20", return_value=20):
            await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.dug_wall is True
        assert tile.surface_type == SurfaceType.CORRIDOR


class TestDiggingToolItems:
    """Verify all digging tool items have correct components."""

    @pytest.fixture(autouse=True)
    def _init(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("item_id,expected_bonus", [
        ("pick", 0),
        ("shovel", -2),
        ("pickaxe", 3),
        ("mattock", 5),
    ])
    def test_has_digging_tool_component(self, item_id, expected_bonus):
        comps = EntityRegistry.get_item(item_id)
        assert "DiggingTool" in comps
        assert comps["DiggingTool"].bonus == expected_bonus

    @pytest.mark.parametrize("item_id", [
        "pick", "shovel", "pickaxe", "mattock",
    ])
    def test_has_weapon_component(self, item_id):
        comps = EntityRegistry.get_item(item_id)
        assert "Weapon" in comps
        assert comps["Weapon"].type == "melee"

    @pytest.mark.parametrize("item_id,expected_damage", [
        ("pick", "1d4"),
        ("shovel", "1d4"),
        ("pickaxe", "1d6"),
        ("mattock", "1d8"),
    ])
    def test_weapon_damage(self, item_id, expected_damage):
        comps = EntityRegistry.get_item(item_id)
        assert comps["Weapon"].damage == expected_damage
