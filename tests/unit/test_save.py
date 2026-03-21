"""Tests for save/load game state."""

import pytest
from pathlib import Path

from nhc.core.ecs import World
from nhc.core.save import delete_save, load_game, save_game
from nhc.dungeon.model import Level, Room, Rect, Terrain, Tile
from nhc.entities.components import (
    Description,
    Equipment,
    Health,
    Inventory,
    LootTable,
    Player,
    Position,
    Renderable,
    Stats,
    Weapon,
)


def _make_level():
    """Create a small test level."""
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(10)]
        for _ in range(10)
    ]
    tiles[0][0].terrain = Terrain.WALL
    tiles[5][5].feature = "stairs_down"
    tiles[3][3].explored = True

    return Level(
        id="test", name="Test Dungeon", depth=1,
        width=10, height=10, tiles=tiles,
        rooms=[Room(id="room_1", rect=Rect(1, 1, 5, 5))],
    )


def _make_world():
    """Create a world with a player and an item."""
    world = World()
    pid = world.create_entity({
        "Position": Position(x=3, y=3, level_id="test"),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=8, maximum=12),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@", color="bright_yellow"),
    })

    item_id = world.create_entity({
        "Position": Position(x=5, y=5),
        "Description": Description(name="Sword"),
        "Weapon": Weapon(damage="1d8", type="melee"),
        "Renderable": Renderable(glyph=")", color="white"),
    })

    return world, pid, item_id


class TestSaveLoad:
    def test_round_trip(self, tmp_path):
        """Save and load produces equivalent state."""
        world, pid, item_id = _make_world()
        level = _make_level()
        messages = ["Welcome!", "You see a sword."]

        save_path = tmp_path / "test_save.json"
        save_game(world, level, pid, turn=5, messages=messages,
                  save_path=save_path)

        assert save_path.exists()

        w2, l2, pid2, turn2, msgs2 = load_game(save_path)

        assert turn2 == 5
        assert pid2 == pid
        assert msgs2 == messages

        # Check player components survived
        pos = w2.get_component(pid2, "Position")
        assert pos.x == 3
        assert pos.y == 3

        health = w2.get_component(pid2, "Health")
        assert health.current == 8
        assert health.maximum == 12

        stats = w2.get_component(pid2, "Stats")
        assert stats.strength == 2

        # Check item survived
        wpn = w2.get_component(item_id, "Weapon")
        assert wpn.damage == "1d8"

    def test_level_tiles_preserved(self, tmp_path):
        """Level tile state (terrain, features, explored) round-trips."""
        world, pid, _ = _make_world()
        level = _make_level()

        save_path = tmp_path / "test_save.json"
        save_game(world, level, pid, turn=0, messages=[],
                  save_path=save_path)

        _, l2, _, _, _ = load_game(save_path)

        assert l2.name == "Test Dungeon"
        assert l2.width == 10
        assert l2.tiles[0][0].terrain == Terrain.WALL
        assert l2.tiles[5][5].feature == "stairs_down"
        assert l2.tiles[3][3].explored is True

    def test_level_rooms_preserved(self, tmp_path):
        world, pid, _ = _make_world()
        level = _make_level()

        save_path = tmp_path / "test_save.json"
        save_game(world, level, pid, turn=0, messages=[],
                  save_path=save_path)

        _, l2, _, _, _ = load_game(save_path)
        assert len(l2.rooms) == 1
        assert l2.rooms[0].id == "room_1"
        assert l2.rooms[0].rect.x == 1

    def test_inventory_with_items(self, tmp_path):
        """Items in inventory serialize correctly."""
        world, pid, item_id = _make_world()
        level = _make_level()

        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)
        equip = world.get_component(pid, "Equipment")
        equip.weapon = item_id

        save_path = tmp_path / "test_save.json"
        save_game(world, level, pid, turn=3, messages=[],
                  save_path=save_path)

        w2, _, pid2, _, _ = load_game(save_path)

        inv2 = w2.get_component(pid2, "Inventory")
        assert item_id in inv2.slots

        equip2 = w2.get_component(pid2, "Equipment")
        assert equip2.weapon == item_id

    def test_loot_table_round_trip(self, tmp_path):
        """LootTable tuple entries survive serialization."""
        world = World()
        eid = world.create_entity({
            "LootTable": LootTable(entries=[
                ("gold", 0.5, "2d6"),
                ("dagger", 0.3),
            ]),
            "Position": Position(x=1, y=1),
        })
        level = _make_level()

        save_path = tmp_path / "test_save.json"
        save_game(world, level, player_id=eid, turn=0, messages=[],
                  save_path=save_path)

        w2, _, _, _, _ = load_game(save_path)
        lt = w2.get_component(eid, "LootTable")
        assert len(lt.entries) == 2
        assert lt.entries[0][0] == "gold"
        assert lt.entries[0][1] == 0.5
        assert lt.entries[0][2] == "2d6"

    def test_delete_save(self, tmp_path):
        save_path = tmp_path / "test_save.json"
        save_path.write_text("{}")

        delete_save(save_path)
        assert not save_path.exists()

    def test_bool_component_round_trip(self, tmp_path):
        """Boolean tag components (like Gold: True) round-trip."""
        world = World()
        eid = world.create_entity({
            "Gold": True,
            "Position": Position(x=1, y=1),
        })
        level = _make_level()

        save_path = tmp_path / "test_save.json"
        save_game(world, level, player_id=eid, turn=0, messages=[],
                  save_path=save_path)

        w2, _, _, _, _ = load_game(save_path)
        assert w2.get_component(eid, "Gold") is True
