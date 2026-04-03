"""Cellular automata cave generator.

Produces organic cave layouts as an alternative to BSP rooms.
Algorithm: random fill -> CA smoothing -> flood-fill regions ->
connect -> walls -> stairs -> doors.
"""

from __future__ import annotations

import logging
import random
from collections import deque

from nhc.dungeon.generator import DungeonGenerator, GenerationParams
from nhc.dungeon.model import (
    Level,
    LevelMetadata,
    Rect,
    Room,
    RoomShape,
    Terrain,
    Tile,
)
from nhc.utils.rng import get_rng

logger = logging.getLogger(__name__)

# CA parameters
CA_ITERATIONS = 5
BIRTH_THRESHOLD = 5   # dead cell becomes alive with >= 5 neighbors
SURVIVE_THRESHOLD = 4  # live cell stays alive with >= 4 neighbors
MIN_REGION_SIZE = 9    # discard caverns smaller than this


class CaveShape(RoomShape):
    """Room shape backed by an explicit set of floor tiles."""

    type_name = "cave"

    def __init__(self, tiles: set[tuple[int, int]]) -> None:
        self._tiles = tiles

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        return self._tiles


class CellularGenerator(DungeonGenerator):
    """Generate cave dungeons using cellular automata."""

    def generate(
        self, params: GenerationParams,
        rng: random.Random | None = None,
    ) -> Level:
        rng = rng or get_rng()
        logger.info(
            "Cellular generate: %dx%d depth=%d",
            params.width, params.height, params.depth,
        )

        level = Level.create_empty(
            id=f"depth_{params.depth}",
            name=f"Cave Level {params.depth}",
            depth=params.depth,
            width=params.width,
            height=params.height,
        )
        level.metadata = LevelMetadata(
            theme=params.theme, difficulty=params.depth,
        )

        # Step 1: Random fill
        self._init_grid(level, params.density, rng)

        # Step 2: CA smoothing
        for _ in range(CA_ITERATIONS):
            self._automata_step(level)

        # Step 3: Find connected regions
        regions = self._flood_fill(level)
        regions.sort(key=len, reverse=True)

        if not regions:
            # Fallback: carve a small room in the center
            cx, cy = params.width // 2, params.height // 2
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    level.tiles[cy + dy][cx + dx] = Tile(
                        terrain=Terrain.FLOOR,
                    )
            regions = [
                {(cx + dx, cy + dy)
                 for dy in range(-2, 3) for dx in range(-2, 3)}
            ]

        # Step 4: Keep largest, connect or discard smaller ones
        main_region = regions[0]
        kept_regions = [main_region]

        for region in regions[1:]:
            if len(region) < MIN_REGION_SIZE:
                # Fill back to VOID
                for x, y in region:
                    level.tiles[y][x] = Tile(terrain=Terrain.VOID)
            else:
                self._connect_regions(level, main_region, region, rng)
                main_region = main_region | region
                kept_regions.append(region)

        # Step 5: Build Room objects from regions
        for i, region in enumerate(kept_regions):
            room = self._region_to_room(region, i)
            level.rooms.append(room)

        # Step 6: Build walls around floor tiles
        self._build_walls(level)

        # Step 7: Place stairs with max separation
        self._place_stairs(level, rng)

        # Step 8: Place doors at corridor-cavern junctions
        self._place_doors(level)

        floors = sum(
            1 for row in level.tiles for t in row
            if t.terrain == Terrain.FLOOR
        )
        logger.info(
            "Cave complete: %d rooms, %d floor tiles",
            len(level.rooms), floors,
        )

        return level

    @staticmethod
    def _init_grid(
        level: Level, density: float, rng: random.Random,
    ) -> None:
        """Seed interior cells as FLOOR with given probability."""
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                if rng.random() < density:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    @staticmethod
    def _automata_step(level: Level) -> None:
        """One iteration of cellular automata smoothing."""
        w, h = level.width, level.height
        new_states: list[tuple[int, int, Terrain]] = []

        for y in range(1, h - 1):
            for x in range(1, w - 1):
                count = 0
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        if level.tiles[y + dy][x + dx].terrain != Terrain.VOID:
                            count += 1

                is_floor = level.tiles[y][x].terrain != Terrain.VOID
                if is_floor:
                    new_t = (Terrain.FLOOR if count >= SURVIVE_THRESHOLD
                             else Terrain.VOID)
                else:
                    new_t = (Terrain.FLOOR if count >= BIRTH_THRESHOLD
                             else Terrain.VOID)
                new_states.append((x, y, new_t))

        for x, y, t in new_states:
            level.tiles[y][x] = Tile(terrain=t)

    @staticmethod
    def _flood_fill(level: Level) -> list[set[tuple[int, int]]]:
        """Find all connected regions of floor tiles."""
        visited: set[tuple[int, int]] = set()
        regions: list[set[tuple[int, int]]] = []

        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                if (x, y) in visited:
                    continue
                if level.tiles[y][x].terrain == Terrain.VOID:
                    continue

                # BFS flood fill
                region: set[tuple[int, int]] = set()
                queue = deque([(x, y)])
                while queue:
                    cx, cy = queue.popleft()
                    if (cx, cy) in visited:
                        continue
                    if not level.in_bounds(cx, cy):
                        continue
                    if level.tiles[cy][cx].terrain == Terrain.VOID:
                        continue
                    visited.add((cx, cy))
                    region.add((cx, cy))
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = cx + dx, cy + dy
                        if (nx, ny) not in visited:
                            queue.append((nx, ny))

                if region:
                    regions.append(region)

        return regions

    @staticmethod
    def _connect_regions(
        level: Level,
        region_a: set[tuple[int, int]],
        region_b: set[tuple[int, int]],
        rng: random.Random,
    ) -> None:
        """Carve an L-shaped corridor between two regions."""
        # Find closest pair of tiles between regions
        best_dist = 99999
        best_a = best_b = (0, 0)

        # Sample from regions for efficiency
        sample_a = (list(region_a) if len(region_a) <= 40
                    else rng.sample(list(region_a), 40))
        sample_b = (list(region_b) if len(region_b) <= 40
                    else rng.sample(list(region_b), 40))

        for ax, ay in sample_a:
            for bx, by in sample_b:
                d = abs(ax - bx) + abs(ay - by)
                if d < best_dist:
                    best_dist = d
                    best_a = (ax, ay)
                    best_b = (bx, by)

        ax, ay = best_a
        bx, by = best_b

        # Carve L-shaped corridor
        if rng.random() < 0.5:
            _carve_line(level, ax, ay, bx, ay)
            _carve_line(level, bx, ay, bx, by)
        else:
            _carve_line(level, ax, ay, ax, by)
            _carve_line(level, ax, by, bx, by)

    @staticmethod
    def _region_to_room(
        region: set[tuple[int, int]], index: int,
    ) -> Room:
        """Create a Room from a set of floor tiles."""
        min_x = min(x for x, y in region)
        max_x = max(x for x, y in region)
        min_y = min(y for x, y in region)
        max_y = max(y for x, y in region)
        rect = Rect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
        return Room(
            id=f"cave_{index + 1}",
            rect=rect,
            shape=CaveShape(region),
        )

    @staticmethod
    def _build_walls(level: Level) -> None:
        """Place WALL tiles around all floor tiles (8-neighbor)."""
        walkable = {Terrain.FLOOR, Terrain.WATER, Terrain.GRASS}
        to_wall: set[tuple[int, int]] = set()

        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.terrain not in walkable:
                    continue
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if (level.in_bounds(nx, ny)
                                and level.tiles[ny][nx].terrain
                                == Terrain.VOID):
                            to_wall.add((nx, ny))

        for wx, wy in to_wall:
            level.tiles[wy][wx] = Tile(terrain=Terrain.WALL)

    @staticmethod
    def _place_stairs(level: Level, rng: random.Random) -> None:
        """Place stairs with maximum separation using BFS."""
        # Collect all non-corridor floor tiles
        floors = [
            (x, y) for y in range(level.height)
            for x in range(level.width)
            if level.tiles[y][x].terrain == Terrain.FLOOR
            and not level.tiles[y][x].is_corridor
        ]

        if len(floors) < 2:
            return

        # BFS twice to find the two most separated tiles
        start = rng.choice(floors)
        farthest_a = _bfs_farthest(level, start)
        farthest_b = _bfs_farthest(level, farthest_a)

        sx, sy = farthest_a
        ex, ey = farthest_b
        level.tiles[sy][sx].feature = "stairs_up"
        level.tiles[ey][ex].feature = "stairs_down"

        # Tag rooms
        for room in level.rooms:
            tiles = room.floor_tiles()
            if (sx, sy) in tiles and "entry" not in room.tags:
                room.tags.append("entry")
            if (ex, ey) in tiles and "exit" not in room.tags:
                room.tags.append("exit")

        # ~15% chance of second stairs_down
        if rng.random() < 0.15 and len(floors) > 10:
            candidates = [
                (x, y) for x, y in floors
                if (abs(x - sx) + abs(y - sy) > 10
                    and abs(x - ex) + abs(y - ey) > 10
                    and not level.tiles[y][x].feature)
            ]
            if candidates:
                x2, y2 = rng.choice(candidates)
                level.tiles[y2][x2].feature = "stairs_down"
                for room in level.rooms:
                    if (x2, y2) in room.floor_tiles():
                        if "exit" not in room.tags:
                            room.tags.append("exit")
                        break

    @staticmethod
    def _place_doors(level: Level) -> None:
        """Place doors where corridors meet cavern floor."""
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                tile = level.tiles[y][x]
                if not tile.is_corridor or tile.feature:
                    continue
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tiles[y + dy][x + dx]
                    if (nb.terrain == Terrain.FLOOR
                            and not nb.is_corridor
                            and not nb.feature):
                        tile.feature = "door_closed"
                        break


def _carve_line(
    level: Level, x1: int, y1: int, x2: int, y2: int,
) -> None:
    """Carve a straight corridor line through any terrain."""
    if y1 == y2:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if not level.in_bounds(x, y1):
                continue
            t = level.tiles[y1][x]
            if t.terrain in (Terrain.VOID, Terrain.WALL):
                level.tiles[y1][x] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )
    else:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if not level.in_bounds(x1, y):
                continue
            t = level.tiles[y][x1]
            if t.terrain in (Terrain.VOID, Terrain.WALL):
                level.tiles[y][x1] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )


def _bfs_farthest(
    level: Level, start: tuple[int, int],
) -> tuple[int, int]:
    """BFS from start, return the farthest reachable floor tile."""
    visited: set[tuple[int, int]] = set()
    queue = deque([start])
    visited.add(start)
    farthest = start

    while queue:
        cx, cy = queue.popleft()
        farthest = (cx, cy)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in visited:
                continue
            if not level.in_bounds(nx, ny):
                continue
            tile = level.tiles[ny][nx]
            if tile.terrain in (
                Terrain.FLOOR, Terrain.WATER, Terrain.GRASS,
            ):
                visited.add((nx, ny))
                queue.append((nx, ny))

    return farthest
