"""Settlement generator: district-based cities and villages.

Produces towns of varying sizes with buildings arranged in
districts, connected by streets. Larger settlements get city
walls with gate openings.
"""

from __future__ import annotations

import logging
import random

from nhc.dungeon.generator import DungeonGenerator, GenerationParams
from nhc.dungeon.model import (
    Corridor,
    Level,
    LevelMetadata,
    Rect,
    RectShape,
    Room,
    Terrain,
    Tile,
)

logger = logging.getLogger(__name__)


# ── Size classes ──────────────────────────────────────────────

SIZE_CLASSES: dict[str, dict] = {
    "hamlet": {
        "width": 25, "height": 20,
        "buildings": (3, 4), "districts": 1, "walls": False,
    },
    "village": {
        "width": 40, "height": 30,
        "buildings": (5, 8), "districts": 2, "walls": False,
    },
    "town": {
        "width": 60, "height": 40,
        "buildings": (10, 15), "districts": 3, "walls": True,
    },
    "city": {
        "width": 80, "height": 50,
        "buildings": (15, 25), "districts": 4, "walls": True,
    },
}


# ── District types ────────────────────────────────────────────

DISTRICT_TYPES: set[str] = {
    "market", "residential", "temple", "noble",
    "garrison", "slums", "docks",
}

# Which building tags belong to each district
_DISTRICT_BUILDINGS: dict[str, list[str]] = {
    "market": ["shop", "inn", "warehouse"],
    "residential": ["house", "house", "garden"],
    "temple": ["shrine", "hospice"],
    "noble": ["mansion", "garden"],
    "garrison": ["barracks", "armory", "training"],
    "slums": ["hovel", "hovel", "den"],
    "docks": ["warehouse", "tavern"],
}

# District weights for random selection
_DISTRICT_WEIGHTS: list[tuple[str, float]] = [
    ("market", 0.25),
    ("residential", 0.30),
    ("temple", 0.15),
    ("noble", 0.10),
    ("garrison", 0.10),
    ("slums", 0.10),
]


class SettlementGenerator(DungeonGenerator):
    """Generate settlement maps with districts and streets."""

    def generate(
        self, params: GenerationParams,
        rng: random.Random | None = None,
    ) -> Level:
        rng = rng or random.Random()
        w, h = params.width, params.height

        # Determine size class from map dimensions
        size_class = _size_class_for(w, h)
        sc = SIZE_CLASSES[size_class]

        logger.info(
            "Settlement generate: %dx%d size=%s",
            w, h, size_class,
        )

        level = Level.create_empty(
            id="settlement",
            name=f"Settlement",
            depth=1,
            width=w,
            height=h,
        )
        level.metadata = LevelMetadata(
            theme="settlement",
            difficulty=0,
            template=params.template,
        )

        # ── 1. City walls for town/city ──
        has_walls = sc["walls"]
        interior = Rect(0, 0, w, h)
        if has_walls:
            _build_city_walls(level)
            interior = Rect(3, 3, w - 6, h - 6)

        # ── 2. Place buildings ──
        min_b, max_b = sc["buildings"]
        n_buildings = rng.randint(min_b, max_b)
        buildings = _place_buildings(
            level, interior, n_buildings, rng,
        )

        # ── 3. Assign districts ──
        n_districts = sc["districts"]
        districts = _assign_districts(buildings, n_districts, rng)

        # ── 4. Create rooms ──
        for i, (rect, district) in enumerate(
            zip(buildings, districts)
        ):
            room = Room(
                id=f"building_{i + 1}",
                rect=rect,
                shape=RectShape(),
                tags=[district],
            )
            level.rooms.append(room)

        # ── 5. Carve streets ──
        _carve_streets(level, buildings, rng)

        # ── 6. Place entry ──
        _place_entry(level, has_walls, rng)

        # ── 7. Gate openings for walled settlements ──
        if has_walls:
            _carve_gate(level, rng)

        logger.info(
            "Settlement complete: %d buildings, %d districts",
            len(buildings), n_districts,
        )
        return level


def _size_class_for(width: int, height: int) -> str:
    """Infer size class from map dimensions."""
    area = width * height
    if area >= 3500:
        return "city"
    if area >= 2000:
        return "town"
    if area >= 900:
        return "village"
    return "hamlet"


def _build_city_walls(level: Level) -> None:
    """Build a 2-tile thick outer wall ring."""
    for y in range(level.height):
        for x in range(level.width):
            if (x < 2 or x >= level.width - 2
                    or y < 2 or y >= level.height - 2):
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)


def _place_buildings(
    level: Level, interior: Rect,
    count: int, rng: random.Random,
) -> list[Rect]:
    """Place non-overlapping building rectangles."""
    buildings: list[Rect] = []
    min_size, max_size = 4, 8
    padding = 3  # gap between buildings for streets

    for _ in range(count * 10):  # attempts
        if len(buildings) >= count:
            break
        bw = rng.randint(min_size, max_size)
        bh = rng.randint(min_size, max_size)
        bx = rng.randint(
            interior.x + padding,
            max(interior.x + padding,
                interior.x + interior.width - bw - padding),
        )
        by = rng.randint(
            interior.y + padding,
            max(interior.y + padding,
                interior.y + interior.height - bh - padding),
        )
        candidate = Rect(bx, by, bw, bh)

        # Check overlap with existing buildings (with padding)
        overlaps = False
        for b in buildings:
            padded = Rect(
                b.x - padding, b.y - padding,
                b.width + padding * 2, b.height + padding * 2,
            )
            if candidate.intersects(padded):
                overlaps = True
                break
        if not overlaps:
            buildings.append(candidate)
            # Carve building floor + walls
            _carve_building(level, candidate)

    return buildings


def _carve_building(level: Level, rect: Rect) -> None:
    """Carve a building: floor interior with surrounding walls."""
    # Floor
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            if level.in_bounds(x, y):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    # Walls around
    for y in range(rect.y - 1, rect.y2 + 1):
        for x in range(rect.x - 1, rect.x2 + 1):
            if not level.in_bounds(x, y):
                continue
            if (x < rect.x or x >= rect.x2
                    or y < rect.y or y >= rect.y2):
                if level.tiles[y][x].terrain == Terrain.VOID:
                    level.tiles[y][x] = Tile(terrain=Terrain.WALL)


def _assign_districts(
    buildings: list[Rect], n_districts: int,
    rng: random.Random,
) -> list[str]:
    """Assign each building to a district type."""
    # Pick district types
    names = [d for d, _ in _DISTRICT_WEIGHTS]
    weights = [w for _, w in _DISTRICT_WEIGHTS]
    chosen = rng.choices(names, weights=weights, k=n_districts)
    # Ensure market is always present
    if "market" not in chosen:
        chosen[0] = "market"

    # Assign buildings to districts by spatial clustering
    if not buildings:
        return []

    # Sort buildings by position, assign in chunks
    sorted_idx = sorted(
        range(len(buildings)),
        key=lambda i: (buildings[i].center[0], buildings[i].center[1]),
    )
    districts: list[str] = [""] * len(buildings)
    chunk_size = max(1, len(buildings) // n_districts)
    for i, idx in enumerate(sorted_idx):
        district_idx = min(i // chunk_size, len(chosen) - 1)
        districts[idx] = chosen[district_idx]

    return districts


def _carve_streets(
    level: Level, buildings: list[Rect],
    rng: random.Random,
) -> None:
    """Carve streets connecting buildings.

    Main street runs through the center. Side streets connect
    each building to the main street.
    """
    if not buildings:
        return

    # Main street: horizontal through the vertical center
    mid_y = level.height // 2
    # Find extent of buildings
    min_x = min(b.x for b in buildings) - 1
    max_x = max(b.x2 for b in buildings) + 1
    min_x = max(2, min_x)
    max_x = min(level.width - 2, max_x)

    _carve_street_line(level, min_x, mid_y, max_x, mid_y)

    # Connect each building to the main street
    for b in buildings:
        cx, cy = b.center
        # Vertical connection from building center to main street
        if cy < mid_y:
            _carve_street_line(level, cx, b.y2, cx, mid_y)
        else:
            _carve_street_line(level, cx, mid_y, cx, b.y - 1)

        # Place a door on the building wall closest to the street
        _place_building_door(level, b, cx, mid_y)


def _carve_street_line(
    level: Level, x1: int, y1: int, x2: int, y2: int,
) -> None:
    """Carve a straight street line."""
    if x1 == x2:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if level.in_bounds(x1, y):
                tile = level.tiles[y][x1]
                if tile.terrain in (Terrain.VOID, Terrain.WALL):
                    level.tiles[y][x1] = Tile(
                        terrain=Terrain.FLOOR,
                        is_street=True,
                    )
    elif y1 == y2:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if level.in_bounds(x, y1):
                tile = level.tiles[y1][x]
                if tile.terrain in (Terrain.VOID, Terrain.WALL):
                    level.tiles[y1][x] = Tile(
                        terrain=Terrain.FLOOR,
                        is_street=True,
                    )


def _place_building_door(
    level: Level, building: Rect,
    street_x: int, street_y: int,
) -> None:
    """Place a door on the building wall nearest the street."""
    cx, cy = building.center
    if street_y < building.y:
        # Street is above: door on north wall
        dx, dy = cx, building.y - 1
    elif street_y >= building.y2:
        # Street is below: door on south wall
        dx, dy = cx, building.y2
    else:
        # Street is at same level: door on nearest side
        if street_x < building.x:
            dx, dy = building.x - 1, cy
        else:
            dx, dy = building.x2, cy

    if level.in_bounds(dx, dy):
        level.tiles[dy][dx] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_closed",
        )


def _place_entry(
    level: Level, has_walls: bool, rng: random.Random,
) -> None:
    """Place stairs_up as the settlement entry point."""
    # Entry at bottom center
    ex = level.width // 2
    if has_walls:
        ey = level.height - 4  # inside the walls
    else:
        ey = level.height - 2

    # Ensure it's walkable
    if level.in_bounds(ex, ey):
        level.tiles[ey][ex] = Tile(
            terrain=Terrain.FLOOR,
            feature="stairs_up",
            is_street=True,
        )
        # Carve a path to the main street
        mid_y = level.height // 2
        _carve_street_line(level, ex, mid_y, ex, ey)


def _carve_gate(level: Level, rng: random.Random) -> None:
    """Carve gate openings in city walls."""
    w, h = level.width, level.height
    mid_x = w // 2

    # South gate (main entry)
    for row in range(max(0, h - 2), h):
        level.tiles[row][mid_x] = Tile(
            terrain=Terrain.FLOOR,
            is_street=True,
        )
    level.tiles[h - 1][mid_x].feature = "door_closed"
