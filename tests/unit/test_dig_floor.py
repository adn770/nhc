"""Tests for the dig-floor mechanic: buried items, hole risk, fall."""

from unittest.mock import patch

import pytest

from nhc.core.ecs import World
from nhc.core.events import LevelEntered, MessageEvent, VisualEffect
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    Description, DiggingTool, Equipment, Health, Inventory, Player,
    Position, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level(buried=None, dug=False) -> Level:
    """10x10 level; player tile (5,5) can have buried items."""
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    if buried:
        tiles[5][5].buried = list(buried)
    tiles[5][5].dug_floor = dug
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world(
    strength: int = 3, with_tool: bool = True, equipped: bool = True,
    buried=None, dug=False, can_dig_floor: bool = True,
) -> tuple[World, int, Level]:
    """Create world with player at (5,5) and optional shovel."""
    i18n_init("en")
    set_seed(42)
    EntityRegistry.discover_all()
    world = World()
    level = _make_level(buried=buried, dug=dug)

    pid = world.create_entity({
        "Position": Position(x=5, y=5, level_id="t"),
        "Player": Player(),
        "Health": Health(current=20, maximum=20),
        "Stats": Stats(strength=strength, dexterity=1, constitution=2),
        "Inventory": Inventory(max_slots=12),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })

    if with_tool:
        tool_id = world.create_entity({
            "Description": Description(name="Shovel"),
            "Renderable": Renderable(glyph="(", color="white"),
            "Weapon": Weapon(damage="1d4", type="melee", slots=1),
            "DiggingTool": DiggingTool(
                bonus=-2, can_dig_floor=can_dig_floor,
            ),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(tool_id)
        if equipped:
            equip = world.get_component(pid, "Equipment")
            equip.weapon = tool_id

    return world, pid, level


class TestDigFloorValidation:
    @pytest.mark.asyncio
    async def test_valid_with_buried_items(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["gold"])
        action = DigFloorAction(actor=pid)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_valid_on_dug_tile(self):
        """Second dig on already-dug tile is valid (guarantees fall)."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(dug=True)
        action = DigFloorAction(actor=pid)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_valid_on_empty_floor(self):
        """Digging an empty floor is valid (may find nothing)."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world()
        action = DigFloorAction(actor=pid)
        assert await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_without_tool(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(
            with_tool=False, buried=["gold"],
        )
        action = DigFloorAction(actor=pid)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_tool_not_equipped(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(
            equipped=False, buried=["gold"],
        )
        action = DigFloorAction(actor=pid)
        assert not await action.validate(world, level)

    @pytest.mark.asyncio
    async def test_invalid_with_pickaxe_cannot_dig_floor(self):
        """Only a shovel (can_dig_floor) may dig the floor."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(
            buried=["gold"], can_dig_floor=False,
        )
        action = DigFloorAction(actor=pid)
        assert not await action.validate(world, level)

    def test_shovel_factory_can_dig_floor(self):
        from nhc.entities.registry import EntityRegistry
        EntityRegistry.discover_all()
        comps = EntityRegistry.get_item("shovel")
        assert comps["DiggingTool"].can_dig_floor is True

    def test_pickaxe_factory_cannot_dig_floor(self):
        from nhc.entities.registry import EntityRegistry
        EntityRegistry.discover_all()
        for item_id in ("pickaxe", "pick", "mattock"):
            comps = EntityRegistry.get_item(item_id)
            assert comps["DiggingTool"].can_dig_floor is False, (
                f"{item_id} should not be able to dig floors"
            )


class TestDigFloorExecution:
    @pytest.mark.asyncio
    async def test_reveals_buried_gold(self):
        """Digging spawns buried gold as entity at player pos."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["gold"])
        action = DigFloorAction(actor=pid)
        # Force no hole (roll high → miss the 1+STR in 20 window)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 20
            events = await action.execute(world, level)

        # Buried items cleared
        tile = level.tile_at(5, 5)
        assert tile.buried == []

        # Gold entity spawned at player pos
        golds = [(eid, pos) for eid, _, pos
                 in world.query("Gold", "Position")
                 if pos.x == 5 and pos.y == 5]
        assert len(golds) >= 1

    @pytest.mark.asyncio
    async def test_reveals_buried_potion(self):
        """Digging spawns buried potion as entity at player pos."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["potion_healing"])
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 20
            events = await action.execute(world, level)

        tile = level.tile_at(5, 5)
        assert tile.buried == []

        # Potion entity with Consumable component at (5,5)
        potions = [(eid, pos) for eid, _, pos
                   in world.query("Consumable", "Position")
                   if pos.x == 5 and pos.y == 5]
        assert len(potions) >= 1

    @pytest.mark.asyncio
    async def test_emits_treasure_visual_effect(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["gold"])
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 20
            events = await action.execute(world, level)

        vfx = [e for e in events if isinstance(e, VisualEffect)]
        assert len(vfx) == 1
        assert vfx[0].effect == "dig_treasure"
        assert vfx[0].x == 5
        assert vfx[0].y == 5

    @pytest.mark.asyncio
    async def test_sets_dug_flag(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["gold"])
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 20
            await action.execute(world, level)

        tile = level.tile_at(5, 5)
        assert tile.dug_floor is True

    @pytest.mark.asyncio
    async def test_second_dig_guarantees_fall(self):
        """Digging a tile that was already dug always causes a fall."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(dug=True)
        action = DigFloorAction(actor=pid)
        events = await action.execute(world, level)

        level_events = [e for e in events if isinstance(e, LevelEntered)]
        assert len(level_events) == 1
        assert level_events[0].fell is True
        assert level_events[0].depth == 2

    @pytest.mark.asyncio
    async def test_hole_chance_with_strength(self):
        """Hole probability is (1 + STR_bonus) in 20."""
        from nhc.core.actions._interaction import DigFloorAction
        # STR bonus 3 → hole if roll <= 4
        world, pid, level = _make_world(
            strength=3, buried=["gold"],
        )
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            # Roll 4 → 4 <= 1+3=4 → hole
            mock_rng.return_value.randint.return_value = 4
            events = await action.execute(world, level)

        level_events = [e for e in events if isinstance(e, LevelEntered)]
        assert len(level_events) == 1

    @pytest.mark.asyncio
    async def test_no_hole_when_roll_exceeds_threshold(self):
        """Roll above (1 + STR) → no hole."""
        from nhc.core.actions._interaction import DigFloorAction
        # STR bonus 3 → threshold 4, roll 5 → no hole
        world, pid, level = _make_world(
            strength=3, buried=["gold"],
        )
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 5
            events = await action.execute(world, level)

        level_events = [e for e in events if isinstance(e, LevelEntered)]
        assert len(level_events) == 0

    @pytest.mark.asyncio
    async def test_hole_applies_falling_damage(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(dug=True)
        action = DigFloorAction(actor=pid)
        events = await action.execute(world, level)

        health = world.get_component(pid, "Health")
        assert health.current < 20

    @pytest.mark.asyncio
    async def test_hole_carries_fallen_items(self):
        """When a hole opens, buried item IDs are in LevelEntered."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(
            strength=3, buried=["gold", "potion_healing"],
        )
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 1  # always hole
            events = await action.execute(world, level)

        le = [e for e in events if isinstance(e, LevelEntered)][0]
        assert "gold" in le.fallen_items
        assert "potion_healing" in le.fallen_items

    @pytest.mark.asyncio
    async def test_hole_items_not_spawned_on_current_level(self):
        """On a hole, items should NOT be spawned on current level."""
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["gold"], dug=True)
        action = DigFloorAction(actor=pid)
        events = await action.execute(world, level)

        # No gold entity at (5,5) on this level
        golds = [(eid, pos) for eid, _, pos
                 in world.query("Gold", "Position")
                 if pos.x == 5 and pos.y == 5]
        assert len(golds) == 0

    @pytest.mark.asyncio
    async def test_hole_emits_dig_hole_visual(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(dug=True)
        action = DigFloorAction(actor=pid)
        events = await action.execute(world, level)

        vfx = [e for e in events if isinstance(e, VisualEffect)]
        assert len(vfx) == 1
        assert vfx[0].effect == "dig_hole"

    @pytest.mark.asyncio
    async def test_emits_message(self):
        from nhc.core.actions._interaction import DigFloorAction
        world, pid, level = _make_world(buried=["gold"])
        action = DigFloorAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 20
            events = await action.execute(world, level)

        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1


class TestDigFloorMiss:
    """Swinging a non-shovel digging tool at the floor may hurt."""

    @pytest.mark.asyncio
    async def test_rolls_1_applies_1d2_damage(self):
        from nhc.core.actions._interaction import DigFloorMissAction
        world, pid, level = _make_world(can_dig_floor=False)
        action = DigFloorMissAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            # Force d20 = 1 (hurt), then d2 roll = 2
            mock_rng.return_value.randint.side_effect = [1, 2]
            events = await action.execute(world, level)

        health = world.get_component(pid, "Health")
        assert health.current == 18  # 20 - 2
        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert any("2" in m.text for m in msgs)

    @pytest.mark.asyncio
    async def test_rolls_above_1_no_damage(self):
        from nhc.core.actions._interaction import DigFloorMissAction
        world, pid, level = _make_world(can_dig_floor=False)
        action = DigFloorMissAction(actor=pid)
        with patch("nhc.core.actions._interaction.get_rng") as mock_rng:
            mock_rng.return_value.randint.return_value = 2  # safe
            events = await action.execute(world, level)

        health = world.get_component(pid, "Health")
        assert health.current == 20  # unchanged
        msgs = [e for e in events if isinstance(e, MessageEvent)]
        assert len(msgs) >= 1

    def test_find_dig_action_returns_miss_for_pickaxe(self):
        """With pickaxe equipped and no walls, find_dig_action should
        return a DigFloorMissAction (turn-consuming risky swing)."""
        from nhc.core.actions._interaction import DigFloorMissAction
        from nhc.core.game_input import find_dig_action

        world, pid, level = _make_world(can_dig_floor=False)

        class FakeRenderer:
            def __init__(self):
                self.messages = []
            def add_message(self, msg):
                self.messages.append(msg)
            def show_selection_menu(self, prompt, options):
                return None

        class FakeGame:
            def __init__(self):
                self.world = world
                self.player_id = pid
                self.level = level
                self.renderer = FakeRenderer()

        game = FakeGame()
        result = find_dig_action(game)
        assert isinstance(result, DigFloorMissAction)


class TestDigFloorAutodigExclusion:
    def test_autodig_data_skips_floor_dig(self):
        """find_dig_action with data=[dx,dy] never returns DigFloorAction."""
        from nhc.core.actions._interaction import DigFloorAction
        from nhc.core.game_input import find_dig_action

        # We need a minimal Game mock for find_dig_action
        world, pid, level = _make_world(buried=["gold"])

        class FakeRenderer:
            def add_message(self, msg):
                pass
            def show_selection_menu(self, prompt, options):
                return None

        class FakeGame:
            def __init__(self):
                self.world = world
                self.player_id = pid
                self.level = level
                self.renderer = FakeRenderer()

        game = FakeGame()
        # Autodig sends [dx, dy] data — should only check walls
        result = find_dig_action(game, data=[1, 0])
        # (5+1, 5) is FLOOR, not WALL → no dig action
        assert result is None or not isinstance(result, DigFloorAction)

    def test_autodig_into_door_falls_back_to_bump(self):
        """A directed dig at a door tile should bump-open it, not no-op."""
        from nhc.core.actions._movement import BumpAction
        from nhc.core.game_input import find_dig_action

        world, pid, level = _make_world()
        # Place a closed door east of the player.
        door_tile = level.tile_at(6, 5)
        door_tile.feature = "door_closed"

        class FakeRenderer:
            def add_message(self, msg):
                pass
            def show_selection_menu(self, prompt, options):
                return None

        class FakeGame:
            def __init__(self):
                self.world = world
                self.player_id = pid
                self.level = level
                self.renderer = FakeRenderer()

        game = FakeGame()
        action = find_dig_action(game, data=[1, 0])
        assert isinstance(action, BumpAction)
        assert (action.dx, action.dy) == (1, 0)


class TestBuriedItemPopulation:
    def test_populate_buries_items(self):
        """populate_level should bury items in some floor tiles."""
        from nhc.dungeon.model import Room, Rect
        from nhc.dungeon.populator import populate_level
        import random

        tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(20)]
                 for _ in range(20)]
        rooms = [Room(
            id="r0",
            rect=Rect(1, 1, 18, 18),
            tags=[],
            connections=[],
        )]
        level = Level(
            id="t", name="T", depth=3, width=20, height=20,
            tiles=tiles, rooms=rooms, corridors=[], entities=[],
        )
        populate_level(level, rng=random.Random(42))

        buried_count = sum(
            1 for row in level.tiles
            for t in row if t.buried
        )
        assert buried_count > 0

    def test_buried_count_scales_inversely_with_depth(self):
        """Shallow levels should have more buried items than deep ones.

        Formula: count = max(1, round(room_count * 2 / sqrt(depth))).
        """
        import math
        import random
        from nhc.dungeon.model import Rect, Room
        from nhc.dungeon.populator import _bury_items

        def _run(depth: int, n_rooms: int) -> int:
            # One big level with n_rooms separate rooms, large enough
            # that all requested items fit without collisions.
            width = 6 * n_rooms + 2
            tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(width)]
                     for _ in range(10)]
            rooms = [
                Room(
                    id=f"r{i}",
                    rect=Rect(1 + i * 6, 1, 5, 8),
                    tags=[],
                    connections=[],
                )
                for i in range(n_rooms)
            ]
            level = Level(
                id="t", name="T", depth=depth,
                width=width, height=10,
                tiles=tiles, rooms=rooms, corridors=[], entities=[],
            )
            _bury_items(level, rng=random.Random(0))
            return sum(
                len(t.buried) for row in level.tiles for t in row
            )

        n_rooms = 4
        shallow = _run(1, n_rooms)
        mid = _run(4, n_rooms)
        deep = _run(16, n_rooms)

        # Formula-exact expectations (rooms are big enough to fit all).
        assert shallow == max(1, round(n_rooms * 2 / math.sqrt(1)))
        assert mid == max(1, round(n_rooms * 2 / math.sqrt(4)))
        assert deep == max(1, round(n_rooms * 2 / math.sqrt(16)))
        assert shallow > mid > deep
        assert deep >= 1  # floor of 1 enforced
