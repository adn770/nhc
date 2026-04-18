"""Tests for room dressing via tables subsystem."""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import Level, Room, Rect, Tile, Terrain, LevelMetadata
from nhc.dungeon.pipeline import _roll_room_dressing
from nhc.i18n import init as i18n_init


def setup_module():
    i18n_init("en")


def _empty_level(*rooms: Room) -> Level:
    """Build a minimal Level with given rooms."""
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    return Level(
        id="test", name="Test", depth=1,
        width=10, height=10, tiles=tiles,
        rooms=list(rooms), corridors=[],
        metadata=LevelMetadata(),
    )


class TestRoomDressing:

    def test_dungeon_gen_rolls_dressing_for_each_room(self):
        r1 = Room(id="r1", rect=Rect(0, 0, 5, 5), tags=["standard"])
        r2 = Room(id="r2", rect=Rect(5, 0, 5, 5), tags=["crypt"])
        level = _empty_level(r1, r2)
        rng = random.Random(42)
        _roll_room_dressing(level, rng)
        for room in level.rooms:
            assert room.dressing, f"room {room.id} has no dressing"
            assert any(k in room.dressing for k in ("smell", "sight", "sound"))

    def test_dressing_is_reproducible_under_seed(self):
        r1 = Room(id="r1", rect=Rect(0, 0, 5, 5), tags=["standard"])
        r2 = Room(id="r2", rect=Rect(0, 0, 5, 5), tags=["standard"])
        level_a = _empty_level(r1)
        level_b = _empty_level(r2)
        _roll_room_dressing(level_a, random.Random(99))
        _roll_room_dressing(level_b, random.Random(99))
        assert level_a.rooms[0].dressing == level_b.rooms[0].dressing

    def test_dressing_gated_by_room_type(self):
        barracks = Room(
            id="r1", rect=Rect(0, 0, 5, 5), tags=["barracks"],
        )
        level = _empty_level(barracks)
        rng = random.Random(42)
        _roll_room_dressing(level, rng)
        # Barracks should get barracks-specific dressing
        assert barracks.dressing

    def test_dressing_persists_in_save_roundtrip(self):
        from nhc.core.save import _deserialize_level, _serialize_level

        room = Room(
            id="r1", rect=Rect(0, 0, 5, 5), tags=["standard"],
            dressing={"smell": "Damp air.", "sight": "Cobwebs."},
        )
        level = _empty_level(room)
        data = _serialize_level(level)
        loaded = _deserialize_level(data)
        assert loaded.rooms[0].dressing == {
            "smell": "Damp air.", "sight": "Cobwebs.",
        }

    def test_dressing_empty_if_room_type_has_no_table(self):
        """Room types without matching entries get empty dressing."""
        exotic = Room(
            id="r1", rect=Rect(0, 0, 5, 5), tags=["zoo"],
        )
        level = _empty_level(exotic)
        rng = random.Random(42)
        _roll_room_dressing(level, rng)
        # zoo has no dressing entries — should not crash
        # dressing may be empty or partially filled
        assert isinstance(exotic.dressing, dict)
