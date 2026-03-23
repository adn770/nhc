"""Tests for the BSP dungeon generator."""

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Terrain
from nhc.dungeon.room_types import assign_room_types
from nhc.dungeon.terrain import apply_terrain
from nhc.dungeon.populator import populate_level
from nhc.utils.rng import set_seed, get_rng


class TestBSPGenerator:
    def test_generates_level(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        assert level is not None
        assert level.width == 60
        assert level.height == 40

    def test_has_rooms(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        assert len(level.rooms) >= 3

    def test_has_corridors(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        assert len(level.corridors) >= 1

    def test_has_stairs(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        has_up = has_down = False
        for row in level.tiles:
            for tile in row:
                if tile.feature == "stairs_up":
                    has_up = True
                if tile.feature == "stairs_down":
                    has_down = True
        assert has_up, "Missing stairs up"
        assert has_down, "Missing stairs down"

    def test_entry_exit_tagged(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        entry = [r for r in level.rooms if "entry" in r.tags]
        exit_ = [r for r in level.rooms if "exit" in r.tags]
        assert len(entry) == 1
        assert len(exit_) == 1

    def test_has_doors(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        doors = 0
        for row in level.tiles:
            for tile in row:
                if tile.feature in ("door_closed", "door_secret"):
                    doors += 1
        assert doors >= 1

    def test_border_no_floor(self):
        """No floor tiles on the map border."""
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        for x in range(level.width):
            assert level.tiles[0][x].terrain != Terrain.FLOOR
            assert level.tiles[level.height - 1][x].terrain != Terrain.FLOOR
        for y in range(level.height):
            assert level.tiles[y][0].terrain != Terrain.FLOOR
            assert level.tiles[y][level.width - 1].terrain != Terrain.FLOOR

    def test_deterministic(self):
        set_seed(123)
        a = BSPGenerator().generate(GenerationParams(width=60, height=40))
        set_seed(123)
        b = BSPGenerator().generate(GenerationParams(width=60, height=40))
        assert len(a.rooms) == len(b.rooms)
        assert a.rooms[0].rect == b.rooms[0].rect

    def test_multiple_seeds_vary(self):
        set_seed(1)
        a = BSPGenerator().generate(GenerationParams(width=60, height=40))
        set_seed(2)
        b = BSPGenerator().generate(GenerationParams(width=60, height=40))
        # Very unlikely to produce identical layouts
        assert (len(a.rooms) != len(b.rooms)
                or a.rooms[0].rect != b.rooms[0].rect)


class TestRoomTypes:
    def test_assigns_types(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        rng = get_rng()
        assign_room_types(level, rng)
        # Every room should have at least one tag
        for room in level.rooms:
            assert len(room.tags) >= 1, f"Room {room.id} has no tags"

    def test_has_standard_rooms(self):
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40))
        rng = get_rng()
        assign_room_types(level, rng)
        standards = [r for r in level.rooms if "standard" in r.tags]
        assert len(standards) >= 3


class TestTerrain:
    def test_applies_water(self):
        set_seed(42)
        gen = BSPGenerator()
        params = GenerationParams(width=60, height=40, theme="sewer")
        level = gen.generate(params)
        rng = get_rng()
        apply_terrain(level, rng)
        water_count = sum(
            1 for row in level.tiles for tile in row
            if tile.terrain == Terrain.WATER
        )
        # Sewer theme should generate some water
        assert water_count > 0


class TestFullPipeline:
    def test_generate_populate(self):
        """Full pipeline: BSP → room types → terrain → populate."""
        set_seed(42)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=60, height=40, depth=2))
        rng = get_rng()
        assign_room_types(level, rng)
        apply_terrain(level, rng)
        populate_level(level)
        assert len(level.entities) > 0
        creatures = [e for e in level.entities
                     if e.entity_type == "creature"]
        assert len(creatures) >= 1
