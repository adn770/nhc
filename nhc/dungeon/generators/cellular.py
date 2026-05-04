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
    SurfaceType,
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

        # Step 5.5: Break any overly-long straight corridor runs.
        # Waypoint kinking bounds individual legs, but two separate
        # _connect_regions calls can carve collinear segments that
        # fuse into one long run; this pass jogs every such run by
        # a single tile perpendicular to its direction.
        self._break_long_corridors(level, rng)

        # Step 6: Build walls around floor tiles
        self._build_walls(level)

        # Step 6.5: Erode wall peninsulas — wall tiles with floor
        # on 3+ cardinal sides create tight concavities that
        # produce knots in the SVG wall outline.  Convert them to
        # floor, rebuild walls, and repeat until no more
        # peninsulas remain (rebuilding can expose new ones).
        total_eroded = 0
        for _pass in range(10):  # bounded iterations
            all_floor: set[tuple[int, int]] = set()
            for y in range(level.height):
                for x in range(level.width):
                    if level.tiles[y][x].terrain == Terrain.FLOOR:
                        all_floor.add((x, y))
            eroded = _erode_wall_peninsulas(level, all_floor)
            if not eroded:
                break
            total_eroded += eroded
            self._build_walls(level)
        # Final sanity: if the last rebuild created new
        # peninsulas, run one more erosion + rebuild.
        else:
            logger.warning(
                "Wall erosion did not converge in 10 passes",
            )
        if total_eroded:
            # Add newly-converted tiles to the appropriate room.
            for room in level.rooms:
                if not isinstance(room.shape, CaveShape):
                    continue
                rtiles = room.shape._tiles
                for (x, y) in list(all_floor - rtiles):
                    for dx, dy in ((-1, 0), (1, 0),
                                   (0, -1), (0, 1)):
                        if (x + dx, y + dy) in rtiles:
                            rtiles.add((x, y))
                            break
            logger.info(
                "Eroded %d wall peninsula tiles", total_eroded,
            )

        # Step 7: Place stairs with max separation
        self._place_stairs(level, rng)

        # Step 8: Absorb corridor tiles into adjacent cave rooms.
        # Corridor tiles between cave rooms create narrow 1-tile
        # passages with walls on both sides — the SVG tracer
        # wraps tightly around these, producing knots.  Converting
        # them to room floor lets the tracer draw one smooth
        # boundary.  No doors in caves — natural rock has open
        # passages only.
        absorbed = _absorb_corridors_into_caves(level)
        if absorbed:
            self._build_walls(level)
            logger.info(
                "Absorbed %d corridor tiles into cave rooms",
                absorbed,
            )

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
        """Seed interior cells as FLOOR with given probability.

        Floor placement is restricted to ``[2, w-3] × [2, h-3]`` so
        the wall ring built by :meth:`_build_walls` lands at most
        at ``[1, w-2] × [1, h-2]``, leaving a 1-tile VOID margin
        on every canvas edge per the level-surface contract
        (``design/level_surface_layout.md``).
        """
        for y in range(2, level.height - 2):
            for x in range(2, level.width - 2):
                if rng.random() < density:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    @staticmethod
    def _automata_step(level: Level) -> None:
        """One iteration of cellular automata smoothing."""
        w, h = level.width, level.height
        new_states: list[tuple[int, int, Terrain]] = []

        for y in range(2, h - 2):
            for x in range(2, w - 2):
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
        """Carve a winding corridor between two regions.

        The path is split into short waypoint segments so no single
        straight run is long enough to feel rectilinear in a cave.
        For short connections (≤ ``MAX_STRAIGHT`` tiles total) a
        plain L is still used; longer ones are kinked every
        ``MAX_STRAIGHT`` tiles with a small perpendicular offset.
        """
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
        _carve_winding_corridor(level, ax, ay, bx, by, rng)

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
    def _break_long_corridors(
        level: Level, rng: random.Random,
    ) -> None:
        """Break any straight corridor run longer than
        :data:`MAX_STRAIGHT` tiles into two shorter runs.

        For a horizontal run, we pick a pivot tile near the middle
        (but not at either endpoint) and detour: carve three
        corridor tiles one row off the main axis ``(mid-1, ny)``,
        ``(mid, ny)``, ``(mid+1, ny)``, then remove the pivot
        ``(mid, y)`` — converting it back to VOID — so the original
        run splits into two halves connected via the 3-tile jog.
        Connectivity is preserved because ``(mid-1, y)`` /
        ``(mid+1, y)`` remain corridor tiles, each 4-adjacent to
        their ``ny`` neighbours.  Symmetric for vertical runs.

        The pass re-runs until no run exceeds the limit, with a
        safety bound to avoid pathological inputs."""
        w, h = level.width, level.height

        def _is_corridor(x: int, y: int) -> bool:
            if not level.in_bounds(x, y):
                return False
            return (
                level.tiles[y][x].surface_type == SurfaceType.CORRIDOR
            )

        def _is_carvable(x: int, y: int) -> bool:
            if not level.in_bounds(x, y):
                return False
            return level.tiles[y][x].terrain in (
                Terrain.VOID, Terrain.WALL,
            )

        def _carve(x: int, y: int) -> None:
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
            )

        def _void(x: int, y: int) -> None:
            level.tiles[y][x] = Tile(terrain=Terrain.VOID)

        def _try_break_horizontal(
            y: int, start: int, end: int,
        ) -> bool:
            # Try pivots near the middle outward, so the two halves
            # are roughly balanced.  Skip endpoints and cells whose
            # removal would strand an adjacent cave entrance.
            mid = (start + end) // 2
            order = []
            for off in range(1, (end - start) // 2):
                order.extend((mid - off, mid + off))
            order.insert(0, mid)
            candidates = [
                c for c in order
                if start < c < end
            ]
            for px in candidates:
                for side in (1, -1):
                    ny = y + side
                    # Restrict the detour row to the floor-eligible
                    # band so the rebuilt wall ring stays inside the
                    # 1-tile VOID margin.
                    if not (1 < ny < h - 2):
                        continue
                    # All three detour cells must be carvable
                    if not all(
                        _is_carvable(px + d, ny)
                        for d in (-1, 0, 1)
                    ):
                        continue
                    # Removing the pivot must not isolate a
                    # neighbouring cave cell: (px, y±1) should
                    # either already be corridor/void, never a
                    # cave floor that relied on the pivot.
                    nb_up = level.tile_at(px, y - 1)
                    nb_dn = level.tile_at(px, y + 1)
                    risky = False
                    for nb in (nb_up, nb_dn):
                        if (nb and nb.terrain == Terrain.FLOOR
                                and nb.surface_type
                                != SurfaceType.CORRIDOR):
                            risky = True
                            break
                    if risky:
                        continue
                    # Perform the break
                    for d in (-1, 0, 1):
                        _carve(px + d, ny)
                    _void(px, y)
                    return True
            return False

        def _try_break_vertical(
            x: int, start: int, end: int,
        ) -> bool:
            mid = (start + end) // 2
            order = []
            for off in range(1, (end - start) // 2):
                order.extend((mid - off, mid + off))
            order.insert(0, mid)
            candidates = [
                c for c in order
                if start < c < end
            ]
            for py in candidates:
                for side in (1, -1):
                    nx = x + side
                    # Restrict the detour column to the floor-
                    # eligible band so the rebuilt wall ring stays
                    # inside the 1-tile VOID margin.
                    if not (1 < nx < w - 2):
                        continue
                    if not all(
                        _is_carvable(nx, py + d)
                        for d in (-1, 0, 1)
                    ):
                        continue
                    nb_l = level.tile_at(x - 1, py)
                    nb_r = level.tile_at(x + 1, py)
                    risky = False
                    for nb in (nb_l, nb_r):
                        if (nb and nb.terrain == Terrain.FLOOR
                                and nb.surface_type
                                != SurfaceType.CORRIDOR):
                            risky = True
                            break
                    if risky:
                        continue
                    for d in (-1, 0, 1):
                        _carve(nx, py + d)
                    _void(x, py)
                    return True
            return False

        safety = 0
        while safety < 12:
            safety += 1
            broke_any = False
            # Horizontal runs
            for y in range(h):
                x = 0
                while x < w:
                    if not _is_corridor(x, y):
                        x += 1
                        continue
                    start = x
                    while x < w and _is_corridor(x, y):
                        x += 1
                    end = x - 1
                    run_len = end - start + 1
                    if run_len > MAX_STRAIGHT:
                        if _try_break_horizontal(y, start, end):
                            broke_any = True
                            # Restart row scan from the break
                            # point since the run changed.
                            x = start
            # Vertical runs
            for x in range(w):
                y = 0
                while y < h:
                    if not _is_corridor(x, y):
                        y += 1
                        continue
                    start = y
                    while y < h and _is_corridor(x, y):
                        y += 1
                    end = y - 1
                    run_len = end - start + 1
                    if run_len > MAX_STRAIGHT:
                        if _try_break_vertical(x, start, end):
                            broke_any = True
                            y = start
            if not broke_any:
                break

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
            and level.tiles[y][x].surface_type != SurfaceType.CORRIDOR
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
    def _place_doors(level: Level, rng: random.Random) -> None:
        """Place doors where corridors meet cavern floor.

        Caves use open passages by default — no wooden doors in
        natural rock.  ~10% of junctions get a secret door instead.
        """
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                tile = level.tiles[y][x]
                if (tile.surface_type != SurfaceType.CORRIDOR
                        or tile.feature):
                    continue
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tiles[y + dy][x + dx]
                    if (nb.terrain == Terrain.FLOOR
                            and nb.surface_type != SurfaceType.CORRIDOR
                            and not nb.feature):
                        if rng.random() < 0.10:
                            tile.feature = "door_secret"
                        break


def _absorb_corridors_into_caves(level: Level) -> int:
    """Absorb corridor and orphan floor tiles into cave rooms.

    Walks every floor tile that is either a corridor tile or not
    in any cave room and checks if it is adjacent to a CaveShape
    room.  If so, clears its ``surface_type`` (from CORRIDOR back
    to NONE) and adds it to that room's tile set.  This lets the
    SVG cave region tracer include these tiles in the smooth
    boundary instead of drawing per-tile wall segments around them.

    Iterates until stable — absorbing a tile can make its
    neighbor newly adjacent to the room.

    Returns the number of tiles absorbed.
    """
    # Build a lookup: tile coord → CaveShape room.
    # Also clear surface_type on any corridor tile already in a
    # cave room (e.g. added during erosion).
    cave_tiles: dict[tuple[int, int], Room] = {}
    for room in level.rooms:
        if not isinstance(room.shape, CaveShape):
            continue
        for tx, ty in room.shape._tiles:
            cave_tiles[(tx, ty)] = room
            tile = level.tiles[ty][tx]
            if tile.surface_type == SurfaceType.CORRIDOR:
                tile.surface_type = SurfaceType.NONE

    absorbed = 0
    changed = True
    while changed:
        changed = False
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                if (x, y) in cave_tiles:
                    continue
                t = level.tiles[y][x]
                if t.terrain != Terrain.FLOOR:
                    continue
                # Find an adjacent cave room
                owner = None
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    owner = cave_tiles.get((x + dx, y + dy))
                    if owner is not None:
                        break
                if owner is None:
                    continue
                # Absorb: clear corridor flag, add to room
                t.surface_type = SurfaceType.NONE
                owner.shape._tiles.add((x, y))
                cave_tiles[(x, y)] = owner
                absorbed += 1
                changed = True
    return absorbed


def _erode_wall_peninsulas(
    level: Level,
    floor_tiles: set[tuple[int, int]],
) -> int:
    """Remove narrow wall protrusions that poke into cave regions.

    Erodes wall tiles that form thin peninsulas or notches —
    these create tight concavities in the cave boundary that
    produce knots in the SVG wall outline.  Two criteria:

    1. **Peninsula tips**: wall with floor on 3+ cardinal sides.
    2. **Thin walls**: wall with floor on opposite cardinal sides
       (north+south or east+west), forming a 1-tile-thick wall
       between two floor areas.

    Iterates until stable.  Returns total tiles converted.
    """
    total = 0
    changed = True
    while changed:
        changed = False
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                t = level.tiles[y][x]
                if t.terrain != Terrain.WALL:
                    continue
                n = (x, y - 1) in floor_tiles
                s = (x, y + 1) in floor_tiles
                e = (x + 1, y) in floor_tiles
                w = (x - 1, y) in floor_tiles
                card = n + s + e + w
                erode = False
                if card >= 3:
                    erode = True
                elif card == 2 and (n and s or e and w):
                    # Floor on opposite sides — thin wall
                    erode = True
                if erode:
                    level.tiles[y][x] = Tile(
                        terrain=Terrain.FLOOR,
                    )
                    floor_tiles.add((x, y))
                    total += 1
                    changed = True
    return total


MAX_STRAIGHT = 4
"""Target maximum straight-run length in tiles for a single
corridor leg.  Each leg of a connection is bounded by this, but
runs across multiple connections can merge when two different
connect-region calls carve collinear or adjacent segments through
the same row/column — so the actual longest run in a generated
level may still exceed MAX_STRAIGHT by a small amount.  The
visual impact is far smaller than the previous 30+ tile straights,
and the tests accept the occasional outlier."""


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
                    terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
                )
    else:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if not level.in_bounds(x1, y):
                continue
            t = level.tiles[y][x1]
            if t.terrain in (Terrain.VOID, Terrain.WALL):
                level.tiles[y][x1] = Tile(
                    terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
                )


def _carve_l(
    level: Level, x1: int, y1: int, x2: int, y2: int,
    rng: random.Random,
    horizontal_first: bool | None = None,
) -> None:
    """Carve an L-shaped corridor: one horizontal leg + one
    vertical leg.  When *horizontal_first* is None the bend is
    picked at random; otherwise callers can force the order to
    avoid fusing with an adjacent segment."""
    if horizontal_first is None:
        horizontal_first = rng.random() < 0.5
    if horizontal_first:
        _carve_line(level, x1, y1, x2, y1)
        _carve_line(level, x2, y1, x2, y2)
    else:
        _carve_line(level, x1, y1, x1, y2)
        _carve_line(level, x1, y2, x2, y2)


def _carve_winding_corridor(
    level: Level, x1: int, y1: int, x2: int, y2: int,
    rng: random.Random,
) -> None:
    """Carve a kinked corridor from (x1,y1) to (x2,y2).

    Splits the path into legs no longer than ``MAX_STRAIGHT`` tiles
    on the dominant axis.  Intermediate waypoints are offset
    perpendicular to the main direction by a small random amount
    so the corridor reads as a zigzag instead of a long ruler line.
    Short connections (≤ MAX_STRAIGHT in both axes) fall through to
    a plain L, which is already organic enough.
    """
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) <= MAX_STRAIGHT and abs(dy) <= MAX_STRAIGHT:
        _carve_l(level, x1, y1, x2, y2, rng)
        return

    # Number of legs along the dominant axis
    dominant = max(abs(dx), abs(dy))
    n_legs = max(2, (dominant + MAX_STRAIGHT - 1) // MAX_STRAIGHT)

    # Waypoints interpolate linearly from A to B with a random
    # perpendicular jitter of up to MAX_STRAIGHT-1 tiles (smaller
    # than a leg so subsequent legs never need to double back
    # further than MAX_STRAIGHT tiles).
    jitter_cap = max(1, MAX_STRAIGHT - 1)
    waypoints: list[tuple[int, int]] = [(x1, y1)]
    for i in range(1, n_legs):
        t = i / n_legs
        mx = int(round(x1 + dx * t))
        my = int(round(y1 + dy * t))
        # Perpendicular offset — mostly-horizontal paths jitter
        # vertically, and vice versa.
        if abs(dx) >= abs(dy):
            my += rng.randint(-jitter_cap, jitter_cap)
        else:
            mx += rng.randint(-jitter_cap, jitter_cap)
        # Clamp to the floor-eligible interior so the surrounding
        # wall ring stays inside the 1-tile VOID margin per
        # ``design/level_surface_layout.md``.
        mx = max(2, min(level.width - 3, mx))
        my = max(2, min(level.height - 3, my))
        waypoints.append((mx, my))
    waypoints.append((x2, y2))

    # Carve L-shaped segments between consecutive waypoints with
    # a fixed bend order so adjacent legs can't fuse on the
    # dominant axis.  When the path is mostly-horizontal we do
    # "vertical first, horizontal second" for every leg: each leg
    # ends going horizontally, and the next leg starts going
    # vertically — so the horizontal runs are chopped into pieces
    # of length ≤ MAX_STRAIGHT and the vertical runs are bounded
    # by jitter_cap.  Symmetric for mostly-vertical paths.
    horizontal_first = abs(dx) < abs(dy)
    for (ax, ay), (bx, by) in zip(waypoints, waypoints[1:]):
        _carve_l(
            level, ax, ay, bx, by, rng,
            horizontal_first=horizontal_first,
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
