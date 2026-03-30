"""Dungeon data model: Level, Room, Corridor, Tile."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto


class Terrain(Enum):
    """Tile terrain types."""
    VOID = auto()
    FLOOR = auto()
    WALL = auto()
    WATER = auto()
    LAVA = auto()
    CHASM = auto()


@dataclass
class Rect:
    """Axis-aligned rectangle."""
    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def intersects(self, other: Rect) -> bool:
        return (self.x < other.x2 and self.x2 > other.x
                and self.y < other.y2 and self.y2 > other.y)


# ── Room shapes ────────────────────────────────────────────────────


class RoomShape(ABC):
    """Strategy that defines which tiles within a bounding rect are floor."""

    type_name: str = ""

    @abstractmethod
    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        """Return the set of (x, y) positions that are floor."""

    def perimeter_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        """Floor tiles adjacent to at least one non-floor tile."""
        floor = self.floor_tiles(rect)
        return {
            (x, y) for x, y in floor
            if any(
                (x + dx, y + dy) not in floor
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
            )
        }


class RectShape(RoomShape):
    """Rectangular room — all tiles in the bounding rect are floor."""

    type_name = "rect"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        return {
            (x, y)
            for y in range(rect.y, rect.y2)
            for x in range(rect.x, rect.x2)
        }


class CircleShape(RoomShape):
    """Circular room — filled ellipse inscribed in the bounding rect."""

    type_name = "circle"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        cx = rect.x + (rect.width - 1) / 2
        cy = rect.y + (rect.height - 1) / 2
        rx = (rect.width - 1) / 2
        ry = (rect.height - 1) / 2
        if rx <= 0 or ry <= 0:
            return set()
        return {
            (x, y)
            for y in range(rect.y, rect.y2)
            for x in range(rect.x, rect.x2)
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0
        }


_SHAPE_REGISTRY: dict[str, type[RoomShape]] = {
    "rect": RectShape,
    "circle": CircleShape,
}


def shape_from_type(type_name: str | None) -> RoomShape:
    """Resolve a shape type string to a RoomShape instance."""
    cls = _SHAPE_REGISTRY.get(type_name or "rect", RectShape)
    return cls()


@dataclass
class Tile:
    """Single map cell."""
    terrain: Terrain = Terrain.WALL
    feature: str | None = None  # door, stairs_up, stairs_down, trap, etc.
    explored: bool = False
    visible: bool = False
    is_corridor: bool = False  # True for tunnel tiles (rendered as #)
    door_side: str = ""  # "north","south","east","west" — which tile edge
                         # the door sits on (set at generation time)

    @property
    def walkable(self) -> bool:
        if self.feature == "door_secret":
            return False
        return self.terrain in (Terrain.FLOOR, Terrain.WATER)

    @property
    def blocks_sight(self) -> bool:
        if self.feature in ("door_secret", "door_closed", "door_locked"):
            return True
        return self.terrain in (Terrain.WALL, Terrain.VOID)


@dataclass
class Room:
    """Room metadata (for AI/narrative, overlays the tile grid)."""
    id: str
    rect: Rect
    shape: RoomShape = field(default_factory=RectShape)
    tags: list[str] = field(default_factory=list)
    description: str = ""
    connections: list[str] = field(default_factory=list)

    def floor_tiles(self) -> set[tuple[int, int]]:
        """Return the set of (x, y) tiles belonging to this room."""
        return self.shape.floor_tiles(self.rect)


@dataclass
class Corridor:
    """Corridor connecting rooms."""
    id: str
    points: list[tuple[int, int]] = field(default_factory=list)
    connects: list[str] = field(default_factory=list)


@dataclass
class EntityPlacement:
    """Entity spawn point within a level."""
    entity_type: str    # "creature", "item", "feature"
    entity_id: str      # Registry ID: "goblin", "healing_potion", etc.
    x: int = 0
    y: int = 0
    extra: dict = field(default_factory=dict)  # patrol routes, hidden, dc, etc.


@dataclass
class LevelMetadata:
    """Level-wide narrative and theming data."""
    theme: str = "dungeon"
    difficulty: int = 1
    narrative_hooks: list[str] = field(default_factory=list)
    faction: str | None = None
    ambient: str = ""


@dataclass
class Level:
    """A single dungeon level."""
    id: str
    name: str
    depth: int
    width: int
    height: int
    tiles: list[list[Tile]] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    corridors: list[Corridor] = field(default_factory=list)
    entities: list[EntityPlacement] = field(default_factory=list)
    metadata: LevelMetadata = field(default_factory=LevelMetadata)

    @classmethod
    def create_empty(cls, id: str, name: str, depth: int,
                     width: int, height: int) -> Level:
        """Create a level filled with void."""
        tiles = [
            [Tile(terrain=Terrain.VOID) for _ in range(width)]
            for _ in range(height)
        ]
        return cls(
            id=id, name=name, depth=depth,
            width=width, height=height, tiles=tiles,
        )

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def tile_at(self, x: int, y: int) -> Tile | None:
        if self.in_bounds(x, y):
            return self.tiles[y][x]
        return None
