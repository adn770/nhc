"""Tests for autosave/restore system."""

import pickle
import zlib

import pytest

from nhc.core.autosave import (
    _DEFAULT_PATH,
    autosave,
    auto_restore,
    delete_autosave,
    has_autosave,
    _build_payload,
    _restore_payload,
)
from nhc.core.ecs import World
from nhc.core.events import EventBus
from nhc.dungeon.model import Level, Terrain, Tile, Room, Rect, LevelMetadata
from nhc.entities.components import (
    AI, Description, Equipment, Health, Inventory, Player,
    Position, Renderable, Stats, Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.rules.identification import ItemKnowledge
from nhc.utils.rng import set_seed


class FakeRenderer:
    """Minimal renderer stub for testing."""

    def __init__(self):
        self.messages = []
        self.game_mode = "classic"
        self.narrative_log = type("NL", (), {"add_mechanical": lambda s, t: None})()

    def initialize(self):
        pass

    def add_message(self, text):
        self._messages.append(text)


class FakeGame:
    """Minimal Game stub for autosave testing."""

    def __init__(self):
        self.world = World()
        self.event_bus = EventBus()
        self.turn = 0
        self.player_id = -1
        self.level = None
        self.god_mode = False
        self.mode = "classic"
        self.renderer = FakeRenderer()
        self._floor_cache = {}
        self._knowledge = None
        self._character = None
        self._seen_creatures = set()
        self.running = False
        self.won = False
        self.game_over = False
        self.killed_by = ""

    def _update_fov(self):
        pass

    def _on_message(self, event):
        pass

    def _on_game_won(self, event):
        pass

    def _on_creature_died(self, event):
        pass

    def _on_level_entered(self, event):
        pass

    def _on_item_used(self, event):
        pass


def _make_level():
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    return Level(
        id="test_1", name="Test Level", depth=1,
        width=10, height=10, tiles=tiles,
        rooms=[Room(id="room_1", rect=Rect(1, 1, 5, 5))],
        corridors=[], entities=[],
        metadata=LevelMetadata(theme="dungeon", difficulty=1),
    )


def _make_game():
    """Build a game with a player, items, and a creature."""
    EntityRegistry.discover_all()
    game = FakeGame()
    game.level = _make_level()
    game.turn = 42

    # Create player
    game.player_id = game.world.create_entity({
        "Position": Position(x=3, y=3),
        "Stats": Stats(strength=2, dexterity=3),
        "Health": Health(current=10, maximum=12),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(xp=50, level=2, gold=35),
        "Description": Description(name="Tester"),
        "Equipment": Equipment(),
    })

    # Create an item in inventory
    sword_id = game.world.create_entity({
        "Description": Description(name="Sword"),
        "Weapon": Weapon(damage="1d8"),
        "Renderable": Renderable(glyph=")", color="cyan"),
    })
    inv = game.world.get_component(game.player_id, "Inventory")
    inv.slots.append(sword_id)
    equip = game.world.get_component(game.player_id, "Equipment")
    equip.weapon = sword_id

    # Create a creature on the map
    game.world.create_entity({
        "Position": Position(x=5, y=5),
        "AI": AI(behavior="aggressive_melee"),
        "Health": Health(current=4, maximum=4),
        "Description": Description(name="Goblin"),
    })

    # Set up identification
    set_seed(42)
    game._knowledge = ItemKnowledge()
    game._knowledge.identify("healing_potion")

    # Messages
    game.renderer.messages = ["Hello", "World"]
    game._seen_creatures = {10, 20}

    return game


class TestBuildPayload:
    def test_contains_required_keys(self):
        game = _make_game()
        payload = _build_payload(game)
        assert payload["version"] == 1
        assert payload["turn"] == 42
        assert payload["player_id"] == game.player_id
        assert "world_entities" in payload
        assert "world_components" in payload
        assert "level" in payload
        assert "messages" in payload
        assert "knowledge_identified" in payload

    def test_entities_captured(self):
        game = _make_game()
        payload = _build_payload(game)
        # Player + sword + goblin = 3 entities
        assert len(payload["world_entities"]) == 3

    def test_identification_captured(self):
        game = _make_game()
        payload = _build_payload(game)
        assert "healing_potion" in payload["knowledge_identified"]

    def test_messages_captured(self):
        game = _make_game()
        payload = _build_payload(game)
        assert payload["messages"] == ["Hello", "World"]


class TestRoundTrip:
    def test_restore_preserves_turn(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        game2.level = _make_level()
        _restore_payload(game2, payload)
        assert game2.turn == 42

    def test_restore_preserves_player(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        _restore_payload(game2, payload)
        assert game2.player_id == game.player_id

        health = game2.world.get_component(game2.player_id, "Health")
        assert health.current == 10
        assert health.maximum == 12

        player = game2.world.get_component(game2.player_id, "Player")
        assert player.gold == 35
        assert player.xp == 50

    def test_restore_preserves_inventory(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        _restore_payload(game2, payload)
        inv = game2.world.get_component(game2.player_id, "Inventory")
        assert len(inv.slots) == 1

        equip = game2.world.get_component(game2.player_id, "Equipment")
        assert equip.weapon == inv.slots[0]

    def test_restore_preserves_creatures(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        _restore_payload(game2, payload)
        # Find the goblin
        found = False
        for eid, ai, pos in game2.world.query("AI", "Position"):
            if pos and pos.x == 5 and pos.y == 5:
                found = True
        assert found

    def test_restore_preserves_identification(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        _restore_payload(game2, payload)
        assert game2._knowledge.is_identified("healing_potion")
        assert not game2._knowledge.is_identified("potion_frost")

    def test_restore_preserves_messages(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        _restore_payload(game2, payload)
        assert game2.renderer.messages == ["Hello", "World"]

    def test_restore_preserves_seen_creatures(self):
        game = _make_game()
        payload = _build_payload(game)

        game2 = FakeGame()
        _restore_payload(game2, payload)
        assert game2._seen_creatures == {10, 20}


class TestPickleRoundTrip:
    """Test the full pickle+zlib serialization path."""

    def test_serialize_deserialize(self):
        game = _make_game()
        payload = _build_payload(game)

        # Pickle + compress
        data = zlib.compress(pickle.dumps(payload, protocol=5), level=1)
        assert len(data) > 0

        # Decompress + unpickle
        restored = pickle.loads(zlib.decompress(data))
        assert restored["turn"] == 42
        assert restored["version"] == 1


class TestMultiFloor:
    def test_floor_cache_preserved(self):
        game = _make_game()

        # Simulate a cached floor
        level2 = _make_level()
        level2.id = "test_2"
        level2.depth = 2
        entity_data = {
            100: {"Description": Description(name="Skeleton"),
                  "Position": Position(x=2, y=2)},
        }
        game._floor_cache[2] = (level2, entity_data)

        payload = _build_payload(game)
        assert 2 in payload["floor_cache"]

        game2 = FakeGame()
        _restore_payload(game2, payload)
        assert 2 in game2._floor_cache
        cached_level, cached_entities = game2._floor_cache[2]
        assert cached_level.depth == 2
        assert 100 in cached_entities


class TestFileOperations:
    def test_has_autosave_false_initially(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_PATH",
            tmp_path / "nonexistent.nhc",
        )
        assert not has_autosave()

    def test_autosave_creates_file(self, tmp_path, monkeypatch):
        save_path = tmp_path / "autosave.nhc"
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_PATH", save_path,
        )
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_DIR", tmp_path,
        )
        game = _make_game()
        autosave(game)
        assert save_path.exists()
        assert save_path.stat().st_size > 0

    def test_autosave_restore_roundtrip(self, tmp_path, monkeypatch):
        save_path = tmp_path / "autosave.nhc"
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_PATH", save_path,
        )
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_DIR", tmp_path,
        )

        game = _make_game()
        autosave(game)

        game2 = FakeGame()
        assert auto_restore(game2)
        assert game2.turn == 42

    def test_delete_autosave(self, tmp_path, monkeypatch):
        save_path = tmp_path / "autosave.nhc"
        save_path.write_bytes(b"test")
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_PATH", save_path,
        )
        delete_autosave()
        assert not save_path.exists()

    def test_corrupt_file_handled(self, tmp_path, monkeypatch):
        save_path = tmp_path / "autosave.nhc"
        save_path.write_bytes(b"corrupt data")
        monkeypatch.setattr(
            "nhc.core.autosave._DEFAULT_PATH", save_path,
        )
        game = FakeGame()
        assert not auto_restore(game)
        # Corrupt file should be deleted
        assert not save_path.exists()


class TestCustomSaveDir:
    """Test autosave with explicit save_dir (per-player persistence)."""

    def test_has_autosave_with_save_dir(self, tmp_path):
        save_dir = tmp_path / "player_abc"
        assert not has_autosave(save_dir)

        save_dir.mkdir()
        (save_dir / "autosave.nhc").write_bytes(b"data")
        assert has_autosave(save_dir)

    def test_autosave_creates_file_in_save_dir(self, tmp_path):
        save_dir = tmp_path / "player_abc"
        game = _make_game()
        autosave(game, save_dir)

        expected = save_dir / "autosave.nhc"
        assert expected.exists()
        assert expected.stat().st_size > 0

    def test_autosave_creates_save_dir(self, tmp_path):
        save_dir = tmp_path / "nested" / "player_abc"
        assert not save_dir.exists()

        game = _make_game()
        autosave(game, save_dir)
        assert save_dir.exists()

    def test_restore_from_save_dir(self, tmp_path):
        save_dir = tmp_path / "player_abc"
        game = _make_game()
        autosave(game, save_dir)

        game2 = FakeGame()
        assert auto_restore(game2, save_dir)
        assert game2.turn == 42

    def test_delete_from_save_dir(self, tmp_path):
        save_dir = tmp_path / "player_abc"
        save_dir.mkdir(parents=True)
        (save_dir / "autosave.nhc").write_bytes(b"data")

        delete_autosave(save_dir)
        assert not (save_dir / "autosave.nhc").exists()

    def test_two_players_independent_saves(self, tmp_path):
        dir_a = tmp_path / "player_a"
        dir_b = tmp_path / "player_b"

        game_a = _make_game()
        game_a.turn = 10
        autosave(game_a, dir_a)

        game_b = _make_game()
        game_b.turn = 99
        autosave(game_b, dir_b)

        restored_a = FakeGame()
        assert auto_restore(restored_a, dir_a)
        assert restored_a.turn == 10

        restored_b = FakeGame()
        assert auto_restore(restored_b, dir_b)
        assert restored_b.turn == 99
