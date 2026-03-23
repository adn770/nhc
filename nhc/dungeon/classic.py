"""Classic random room-and-corridor dungeon generator."""

from __future__ import annotations

from nhc.dungeon.generator import DungeonGenerator, GenerationParams
from nhc.dungeon.model import (
    Corridor,
    Level,
    Rect,
    Room,
    Terrain,
    Tile,
)
from nhc.utils.rng import get_rng


class ClassicGenerator(DungeonGenerator):
    """Generate dungeons using random room placement with L-shaped corridors."""

    def generate(self, params: GenerationParams) -> Level:
        rng = get_rng()
        level = Level.create_empty(
            id=f"depth_{params.depth}",
            name=f"Dungeon Level {params.depth}",
            depth=params.depth,
            width=params.width,
            height=params.height,
        )
        level.metadata.theme = params.theme
        level.metadata.difficulty = params.depth

        room_count = rng.randint(params.room_count.min, params.room_count.max)
        rooms: list[Rect] = []

        for _ in range(room_count * 10):  # Attempt limit
            if len(rooms) >= room_count:
                break

            w = rng.randint(params.room_size.min, params.room_size.max)
            h = rng.randint(params.room_size.min, params.room_size.max)
            x = rng.randint(1, params.width - w - 1)
            y = rng.randint(1, params.height - h - 1)
            candidate = Rect(x=x, y=y, width=w, height=h)

            # Check overlap with padding
            padded = Rect(x=x - 1, y=y - 1, width=w + 2, height=h + 2)
            if any(padded.intersects(r) for r in rooms):
                continue

            rooms.append(candidate)
            self._carve_room(level, candidate)

            room_id = f"room_{len(rooms)}"
            level.rooms.append(Room(
                id=room_id,
                rect=candidate,
            ))

        # Connect rooms sequentially with corridors
        for i in range(len(rooms) - 1):
            cx1, cy1 = rooms[i].center
            cx2, cy2 = rooms[i + 1].center

            corridor_id = f"corridor_{i}"
            points: list[tuple[int, int]] = []

            # L-shaped corridor (random bend direction)
            if rng.random() < 0.5:
                points += self._carve_h_tunnel(level, cx1, cx2, cy1)
                points += self._carve_v_tunnel(level, cy1, cy2, cx2)
            else:
                points += self._carve_v_tunnel(level, cy1, cy2, cx1)
                points += self._carve_h_tunnel(level, cx1, cx2, cy2)

            level.corridors.append(Corridor(
                id=corridor_id,
                points=points,
                connects=[
                    level.rooms[i].id,
                    level.rooms[i + 1].id,
                ],
            ))

        # Place stairs
        if rooms:
            # Stairs up in first room, stairs down in last room
            sx, sy = rooms[0].center
            level.tiles[sy][sx].feature = "stairs_up"

            ex, ey = rooms[-1].center
            level.tiles[ey][ex].feature = "stairs_down"

        # Build walls around carved areas
        self._build_walls(level)

        # Place doors at corridor-room junctions
        if params.corridor_style != "open":
            self._place_doors(level)

        return level

    def _build_walls(self, level: Level) -> None:
        """Place a single layer of WALL tiles around floor/water."""
        walkable = {Terrain.FLOOR, Terrain.WATER}
        to_wall: set[tuple[int, int]] = set()
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].terrain not in walkable:
                    continue
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                               (-1, -1), (1, -1), (-1, 1), (1, 1)]:
                    nx, ny = x + dx, y + dy
                    if (level.in_bounds(nx, ny)
                            and level.tiles[ny][nx].terrain == Terrain.VOID):
                        to_wall.add((nx, ny))
        for wx, wy in to_wall:
            level.tiles[wy][wx] = Tile(terrain=Terrain.WALL)
        # Strip walls that don't touch floor (prevent double-layer)
        for wx, wy in list(to_wall):
            if not any(
                level.tile_at(wx + dx, wy + dy)
                and level.tile_at(wx + dx, wy + dy).terrain in walkable
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
            ):
                level.tiles[wy][wx] = Tile(terrain=Terrain.VOID)

    def _carve_room(self, level: Level, rect: Rect) -> None:
        """Carve a rectangular room into the level."""
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                if level.in_bounds(x, y):
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    def _carve_h_tunnel(
        self, level: Level, x1: int, x2: int, y: int,
    ) -> list[tuple[int, int]]:
        """Carve a horizontal tunnel, return carved points."""
        points: list[tuple[int, int]] = []
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if level.in_bounds(x, y):
                existing = level.tiles[y][x]
                if existing.terrain != Terrain.FLOOR:
                    level.tiles[y][x] = Tile(
                        terrain=Terrain.FLOOR, is_corridor=True,
                    )
                points.append((x, y))
        return points

    def _carve_v_tunnel(
        self, level: Level, y1: int, y2: int, x: int,
    ) -> list[tuple[int, int]]:
        """Carve a vertical tunnel, return carved points."""
        points: list[tuple[int, int]] = []
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if level.in_bounds(x, y):
                existing = level.tiles[y][x]
                if existing.terrain != Terrain.FLOOR:
                    level.tiles[y][x] = Tile(
                        terrain=Terrain.FLOOR, is_corridor=True,
                    )
                points.append((x, y))
        return points

    def _place_doors(self, level: Level) -> None:
        """Place doors at corridor-room transition points."""
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                tile = level.tiles[y][x]
                if tile.terrain != Terrain.FLOOR or tile.feature:
                    continue

                # Check for door-like patterns (corridor between walls)
                h_walls = (
                    level.tiles[y - 1][x].terrain == Terrain.WALL
                    and level.tiles[y + 1][x].terrain == Terrain.WALL
                )
                v_walls = (
                    level.tiles[y][x - 1].terrain == Terrain.WALL
                    and level.tiles[y][x + 1].terrain == Terrain.WALL
                )

                if h_walls or v_walls:
                    # Count adjacent floor tiles
                    adj_floor = sum(
                        1 for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                        if (level.in_bounds(x + dx, y + dy)
                            and level.tiles[y + dy][x + dx].terrain
                            == Terrain.FLOOR)
                    )
                    if adj_floor == 2:
                        tile.feature = "door_closed"
