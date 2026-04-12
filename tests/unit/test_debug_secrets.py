"""Tests for the secrets overlay data in _gather_debug_data."""

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.core.ecs import World
from nhc.entities.components import Position, Renderable, Trap
from nhc.rendering.web_client import WebClient


def _make_level() -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_client() -> WebClient:
    return WebClient(game_mode="classic", lang="en")


class TestSecretsInDebugData:
    def test_empty_when_no_secrets(self):
        client = _make_client()
        level = _make_level()
        world = World()
        data = client._gather_debug_data(level, world)
        assert data["secrets"]["secret_doors"] == []
        assert data["secrets"]["buried"] == []
        assert data["secrets"]["hidden_traps"] == []

    def test_secret_doors_collected(self):
        client = _make_client()
        level = _make_level()
        world = World()
        tile = level.tile_at(3, 4)
        tile.feature = "door_secret"
        tile.door_side = "north"

        data = client._gather_debug_data(level, world)
        secrets = data["secrets"]["secret_doors"]
        assert len(secrets) == 1
        assert secrets[0]["x"] == 3
        assert secrets[0]["y"] == 4

    def test_buried_items_collected(self):
        client = _make_client()
        level = _make_level()
        world = World()
        tile = level.tile_at(5, 6)
        tile.buried = ["gold", "potion_healing"]

        data = client._gather_debug_data(level, world)
        buried = data["secrets"]["buried"]
        assert len(buried) == 1
        assert buried[0]["x"] == 5
        assert buried[0]["y"] == 6
        assert buried[0]["count"] == 2

    def test_hidden_traps_collected(self):
        client = _make_client()
        level = _make_level()
        world = World()
        world.create_entity({
            "Position": Position(x=7, y=8),
            "Renderable": Renderable(glyph="^", color="red"),
            "Trap": Trap(effect="fire", hidden=True, dc=14),
        })

        data = client._gather_debug_data(level, world)
        traps = data["secrets"]["hidden_traps"]
        assert len(traps) == 1
        assert traps[0]["x"] == 7
        assert traps[0]["y"] == 8
        assert traps[0]["effect"] == "fire"

    def test_revealed_traps_excluded(self):
        client = _make_client()
        level = _make_level()
        world = World()
        world.create_entity({
            "Position": Position(x=7, y=8),
            "Renderable": Renderable(glyph="^", color="red"),
            "Trap": Trap(effect="fire", hidden=False),
        })

        data = client._gather_debug_data(level, world)
        assert data["secrets"]["hidden_traps"] == []

    def test_backward_compat_without_world(self):
        """Calling without world still works, secrets are empty."""
        client = _make_client()
        level = _make_level()
        # Place a secret door to verify tile-based secrets still work
        tile = level.tile_at(2, 3)
        tile.feature = "door_secret"

        data = client._gather_debug_data(level)
        assert data["secrets"]["secret_doors"] == [
            {"x": 2, "y": 3}
        ]
        assert data["secrets"]["hidden_traps"] == []
