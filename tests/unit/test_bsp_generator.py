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


    def test_no_orphaned_doors(self):
        """Every door must have a corridor or room floor on both sides."""
        door_feats = {"door_closed", "door_open", "door_secret"}
        for seed in [42, 99, 123, 256, 1748291]:
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(GenerationParams(width=80, height=50))
            for y in range(level.height):
                for x in range(level.width):
                    tile = level.tiles[y][x]
                    if tile.feature not in door_feats:
                        continue
                    # Door must have floor on at least 2 cardinal sides
                    floor_sides = 0
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb and nb.terrain == Terrain.FLOOR:
                            floor_sides += 1
                    assert floor_sides >= 2, (
                        f"Orphaned door at ({x},{y}) seed={seed}: "
                        f"only {floor_sides} floor neighbor(s)"
                    )


    def test_adjacent_doors_same_type(self):
        """Adjacent doors must always be the same type."""
        door_feats = {"door_closed", "door_open", "door_secret",
                      "door_locked"}
        for seed in range(200):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(GenerationParams(width=120, height=40))
            for y in range(level.height):
                for x in range(level.width):
                    tile = level.tiles[y][x]
                    if tile.feature not in door_feats:
                        continue
                    for dx, dy in [(1, 0), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb and nb.feature in door_feats:
                            assert tile.feature == nb.feature, (
                                f"Mismatched doors at ({x},{y})="
                                f"{tile.feature} and ({x+dx},{y+dy})="
                                f"{nb.feature} seed={seed}"
                            )

    def test_all_rooms_reachable(self):
        """Every room must be reachable from the entry room via floor tiles."""
        def flood(level, sx, sy):
            visited = set()
            stack = [(sx, sy)]
            while stack:
                fx, fy = stack.pop()
                if (fx, fy) in visited:
                    continue
                t = level.tile_at(fx, fy)
                if not t or t.terrain != Terrain.FLOOR:
                    continue
                visited.add((fx, fy))
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    stack.append((fx + dx, fy + dy))
            return visited

        for seed in range(500):
            set_seed(seed)
            gen = BSPGenerator()
            level = gen.generate(GenerationParams(width=80, height=50))
            entry = [r for r in level.rooms if "entry" in r.tags]
            assert entry, f"No entry room seed={seed}"
            ex, ey = entry[0].rect.center
            reachable = flood(level, ex, ey)
            for room in level.rooms:
                rx, ry = room.rect.center
                assert (rx, ry) in reachable, (
                    f"Room {room.id} at ({rx},{ry}) unreachable "
                    f"from entry at ({ex},{ey}) seed={seed}"
                )


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


class TestWallRendering:
    """Walls between doors must match room border orientation."""

    def test_no_wrong_wall_between_doors_seed_1748291(self):
        """Regression: seed 1748291 produced ─ between vertical doors."""
        from nhc.rendering.terminal.renderer import TerminalRenderer

        set_seed(1748291)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(width=80, height=50, depth=1))
        rng = get_rng()
        assign_room_types(level, rng)
        apply_terrain(level, rng)

        door_feats = {"door_closed", "door_open", "door_locked", "door_secret"}
        for y in range(level.height):
            for x in range(level.width):
                t = level.tiles[y][x]
                if t.terrain != Terrain.WALL:
                    continue
                n = level.tile_at(x, y - 1)
                s = level.tile_at(x, y + 1)
                e = level.tile_at(x + 1, y)
                w = level.tile_at(x - 1, y)

                doors_ns = (
                    (n and n.feature in door_feats)
                    and (s and s.feature in door_feats)
                )
                doors_ew = (
                    (e and e.feature in door_feats)
                    and (w and w.feature in door_feats)
                )
                if not (doors_ns or doors_ew):
                    continue

                ch = TerminalRenderer._wall_char_at(level, x, y)
                if doors_ns:
                    # Vertical doors → wall must be vertical
                    assert ch in ("│", "┤", "├", "┼"), (
                        f"({x},{y}): wall '{ch}' between N/S doors "
                        f"should be vertical"
                    )
                if doors_ew:
                    # Horizontal doors → wall must be horizontal
                    assert ch in ("─", "┬", "┴", "┼"), (
                        f"({x},{y}): wall '{ch}' between E/W doors "
                        f"should be horizontal"
                    )


    def test_no_missing_corner_glyphs(self):
        """Room corners next to doors must still render as corners."""
        from nhc.rendering.terminal.renderer import TerminalRenderer

        for seed in range(20):
            set_seed(seed)
            level = BSPGenerator().generate(
                GenerationParams(width=60, height=40),
            )
            for room in level.rooms:
                r = room.rect
                corners = [
                    (r.x - 1, r.y - 1),
                    (r.x2, r.y - 1),
                    (r.x - 1, r.y2),
                    (r.x2, r.y2),
                ]
                for cx, cy in corners:
                    t = level.tile_at(cx, cy)
                    if not t or t.terrain != Terrain.WALL:
                        continue
                    ch = TerminalRenderer._wall_char_at(level, cx, cy)
                    assert ch not in ("─", "│"), (
                        f"seed={seed} {room.id} corner ({cx},{cy}): "
                        f"got straight '{ch}', expected a corner glyph"
                    )


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
