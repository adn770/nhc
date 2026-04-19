"""Tests for the classic dungeon generator."""

import pytest

from nhc.dungeon.classic import ClassicGenerator
from nhc.dungeon.generator import GenerationParams, Range
from nhc.dungeon.model import Level, Room, Rect, SurfaceType, Terrain, Tile
from nhc.dungeon.populator import populate_level
from nhc.utils.rng import set_seed


class TestClassicGenerator:
    def test_generates_level_with_rooms(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(
            width=60, height=40,
            room_count=Range(4, 8),
            room_size=Range(4, 10),
        )
        level = gen.generate(params)

        assert level.width == 60
        assert level.height == 40
        assert len(level.rooms) >= 4

    def test_rooms_have_floor_tiles(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        for room in level.rooms:
            rect = room.rect
            cx, cy = rect.center
            tile = level.tile_at(cx, cy)
            assert tile is not None
            assert tile.terrain == Terrain.FLOOR

    def test_corridors_connect_rooms(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        assert len(level.corridors) == len(level.rooms) - 1
        for corridor in level.corridors:
            assert len(corridor.connects) == 2

    def test_stairs_placed(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        # First room should have stairs_up
        first_cx, first_cy = level.rooms[0].rect.center
        assert level.tiles[first_cy][first_cx].feature == "stairs_up"

        # Last room should have stairs_down
        last_cx, last_cy = level.rooms[-1].rect.center
        assert level.tiles[last_cy][last_cx].feature == "stairs_down"

    def test_border_is_walls(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=40, height=30)
        level = gen.generate(params)

        # Borders are void (rooms don't touch map edge)
        for x in range(level.width):
            assert level.tiles[0][x].terrain != Terrain.FLOOR
            assert level.tiles[level.height - 1][x].terrain != Terrain.FLOOR
        for y in range(level.height):
            assert level.tiles[y][0].terrain != Terrain.FLOOR
            assert level.tiles[y][level.width - 1].terrain != Terrain.FLOOR

    def test_deterministic_with_seed(self):
        """Same seed produces identical layouts."""
        gen = ClassicGenerator()
        params = GenerationParams(width=50, height=30)

        set_seed(123)
        level1 = gen.generate(params)

        set_seed(123)
        level2 = gen.generate(params)

        assert len(level1.rooms) == len(level2.rooms)
        for r1, r2 in zip(level1.rooms, level2.rooms):
            assert r1.rect.x == r2.rect.x
            assert r1.rect.y == r2.rect.y


class TestPopulator:
    def test_populates_entities(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level, creature_count=3, item_count=2, trap_count=1)

        creatures = [
            e for e in level.entities
            if e.entity_type == "creature"
            and e.entity_id != "adventurer"
        ]
        items = [e for e in level.entities if e.entity_type == "item"]
        features = [e for e in level.entities if e.entity_type == "feature"]

        assert len(creatures) <= 3
        # items includes gold piles placed by the populator
        assert len(items) >= 1
        assert len(features) >= 1  # chests, barrels, crates, traps
        assert len(level.entities) > 0

    def test_depth_1_always_has_adventurer(self):
        """Depth-1 floors must always spawn a recruitable adventurer.

        Gives new players a reliable path to their first henchman.
        """
        from nhc.dungeon.generator import GenerationParams as GP
        from nhc.dungeon.pipeline import generate_level

        for seed in range(40):
            level = generate_level(GP(
                width=120, height=40, depth=1, seed=seed,
            ))
            adventurers = [
                e for e in level.entities
                if (e.entity_type == "creature"
                    and e.entity_id == "adventurer")
            ]
            assert len(adventurers) >= 1, (
                f"seed={seed} depth=1 has no adventurer"
            )

    def test_gold_piles_have_dice(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level, creature_count=0, item_count=0, trap_count=0)

        gold_placements = [
            e for e in level.entities
            if e.entity_id == "gold" and e.extra.get("gold_dice")
        ]
        assert len(gold_placements) > 0
        for gp in gold_placements:
            # Formula: (2 + depth)d8
            expected = f"{2 + level.depth}d8"
            assert gp.extra["gold_dice"] == expected

    def test_entities_on_floor_tiles(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level)

        for entity in level.entities:
            tile = level.tile_at(entity.x, entity.y)
            assert tile is not None
            assert tile.terrain == Terrain.FLOOR

    def test_no_entities_in_first_room(self):
        """Entities should not be placed in the player spawn room."""
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level, creature_count=5, item_count=5)

        if level.rooms:
            spawn_rect = level.rooms[0].rect
            for entity in level.entities:
                in_spawn = (
                    spawn_rect.x <= entity.x < spawn_rect.x2
                    and spawn_rect.y <= entity.y < spawn_rect.y2
                )
                assert not in_spawn, (
                    f"{entity.entity_id} placed in spawn room"
                )

    def test_single_tile_corridors_get_entities(self):
        """Single-tile corridor segments should randomly get a
        creature or item placed on them."""
        # Build a level with two rooms connected by a single-tile
        # corridor at (5,3)
        level = Level.create_empty("t", "T", depth=1,
                                   width=12, height=7)
        # Room A: (1,1)-(4,5)
        for y in range(1, 5):
            for x in range(1, 4):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r1", rect=Rect(1, 1, 3, 4)))
        # Room B: (7,1)-(10,5)
        for y in range(1, 5):
            for x in range(7, 10):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        level.rooms.append(Room(id="r2", rect=Rect(7, 1, 3, 4)))
        # Door at (4,3) and (6,3)
        level.tiles[3][4] = Tile(terrain=Terrain.FLOOR,
                                 feature="door_closed")
        level.tiles[3][6] = Tile(terrain=Terrain.FLOOR,
                                 feature="door_closed")
        # Single-tile corridor at (5,3)
        level.tiles[3][5] = Tile(terrain=Terrain.FLOOR,
                                 surface_type=SurfaceType.CORRIDOR)

        # Run populate many times and collect placements at (5,3)
        creature_count = 0
        item_count = 0
        nothing_count = 0
        trials = 500
        for seed in range(trials):
            level.entities.clear()
            set_seed(seed)
            populate_level(level, creature_count=0, item_count=0,
                           trap_count=0)
            placed = [e for e in level.entities
                      if e.x == 5 and e.y == 3]
            if not placed:
                nothing_count += 1
            else:
                for e in placed:
                    if e.entity_type == "creature":
                        creature_count += 1
                    elif e.entity_type == "item":
                        item_count += 1

        total_placed = creature_count + item_count
        assert total_placed > 0, (
            "No entities placed on single-tile corridor across "
            f"{trials} seeds")
        # Check rough distribution: 50% nothing, 30% creature,
        # 20% item (allow generous tolerance)
        assert nothing_count > trials * 0.3, (
            f"Too few empty rolls: {nothing_count}/{trials}")
        assert creature_count > trials * 0.1, (
            f"Too few creatures: {creature_count}/{trials}")
        assert item_count > trials * 0.05, (
            f"Too few items: {item_count}/{trials}")
