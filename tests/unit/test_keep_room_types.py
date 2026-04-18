"""Tests for keep-specific room type assignment."""

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level
from nhc.dungeon.pipeline import generate_level


class TestKeepRoomTypes:
    def test_keep_has_courtyard(self):
        """Keep template assigns a courtyard room."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:keep",
        )
        level = generate_level(params)
        courtyard_rooms = [
            r for r in level.rooms if "courtyard" in r.tags
        ]
        assert len(courtyard_rooms) >= 1

    def test_keep_has_barracks(self):
        """Keep template assigns barracks rooms."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:keep",
        )
        level = generate_level(params)
        barracks_rooms = [
            r for r in level.rooms if "barracks" in r.tags
        ]
        assert len(barracks_rooms) >= 1

    def test_keep_courtyard_is_largest(self):
        """Courtyard should be the largest room."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:keep",
        )
        level = generate_level(params)
        courtyard_rooms = [
            r for r in level.rooms if "courtyard" in r.tags
        ]
        if not courtyard_rooms:
            return
        courtyard = courtyard_rooms[0]
        courtyard_area = courtyard.rect.width * courtyard.rect.height
        non_vault = [
            r for r in level.rooms if "vault" not in r.tags
        ]
        largest_area = max(
            r.rect.width * r.rect.height for r in non_vault
        )
        assert courtyard_area == largest_area

    def test_non_keep_has_no_courtyard(self):
        """Normal dungeons don't get keep room types."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
        )
        level = generate_level(params)
        courtyard_rooms = [
            r for r in level.rooms if "courtyard" in r.tags
        ]
        assert len(courtyard_rooms) == 0
