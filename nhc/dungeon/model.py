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
    """Circular room — true circle centered in the bounding rect.

    Uses min(width, height) as the diameter so the result is always
    a circle, never an ellipse.  The circle is centered in the rect;
    tiles outside the circle but inside the rect remain void.
    """

    type_name = "circle"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        diameter = min(rect.width, rect.height)
        r = (diameter - 1) / 2
        if r <= 0:
            return set()
        cx = rect.x + (rect.width - 1) / 2
        cy = rect.y + (rect.height - 1) / 2
        return {
            (x, y)
            for y in range(rect.y, rect.y2)
            for x in range(rect.x, rect.x2)
            if (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2
        }


class HexShape(RoomShape):
    """Hexagonal room — flat-topped hex inscribed in the bounding rect."""

    type_name = "hex"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        cy = rect.y + (rect.height - 1) / 2
        half_h = (rect.height - 1) / 2
        if half_h <= 0:
            return set()
        tiles: set[tuple[int, int]] = set()
        for y in range(rect.y, rect.y2):
            dy = abs(y - cy) / half_h
            inset = round(rect.width * dy / 4)
            for x in range(rect.x + inset, rect.x2 - inset):
                tiles.add((x, y))
        return tiles


class OctagonShape(RoomShape):
    """Octagonal room — rectangle with clipped 45-degree corners."""

    type_name = "octagon"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        clip = max(1, min(rect.width, rect.height) // 3)
        tiles: set[tuple[int, int]] = set()
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                lx = x - rect.x
                ly = y - rect.y
                rx = rect.x2 - 1 - x
                ry = rect.y2 - 1 - y
                if (lx + ly < clip
                        or rx + ly < clip
                        or lx + ry < clip
                        or rx + ry < clip):
                    continue
                tiles.add((x, y))
        return tiles


class CrossShape(RoomShape):
    """Cross-shaped room — a + shape with both symmetry axes.

    The cross has a horizontal bar and a vertical bar intersecting
    at the center of the bounding rect.  Bar width is roughly 1/3
    of the room dimension (at least 2 tiles).
    """

    type_name = "cross"

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        cx = rect.x + rect.width // 2
        cy = rect.y + rect.height // 2
        # Bar widths: ~1/3 of dimension, at least 2, at most dim-2
        bar_w = max(2, rect.width // 3)
        bar_h = max(2, rect.height // 3)
        # Center the bars
        h_left = cx - bar_w // 2
        h_right = h_left + bar_w
        v_top = cy - bar_h // 2
        v_bottom = v_top + bar_h
        tiles: set[tuple[int, int]] = set()
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                # In horizontal bar (full width, bar_h tall)
                in_h_bar = v_top <= y < v_bottom
                # In vertical bar (full height, bar_w wide)
                in_v_bar = h_left <= x < h_right
                if in_h_bar or in_v_bar:
                    tiles.add((x, y))
        return tiles


class HybridShape(RoomShape):
    """Composite room — two sub-shapes joined along a split axis.

    The bounding rect is split vertically or horizontally at the
    midpoint. Each half uses a different sub-shape.
    """

    def __init__(
        self,
        left: RoomShape,
        right: RoomShape,
        split: str = "vertical",
    ) -> None:
        self.left = left
        self.right = right
        self.split = split  # "vertical" or "horizontal"
        self.type_name = (
            f"hybrid_{left.type_name}_{right.type_name}_{split[0]}"
        )

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        # Overlap the two halves by 1 tile at the seam so curved
        # shapes (circle, hex) meet the other half without gaps.
        # The union naturally merges overlapping tiles.
        if self.split == "vertical":
            mid = rect.x + rect.width // 2
            left_rect = Rect(
                rect.x, rect.y, mid - rect.x + 1, rect.height,
            )
            right_rect = Rect(mid, rect.y, rect.x2 - mid, rect.height)
        else:
            mid = rect.y + rect.height // 2
            left_rect = Rect(
                rect.x, rect.y, rect.width, mid - rect.y + 1,
            )
            right_rect = Rect(rect.x, mid, rect.width, rect.y2 - mid)
        # Clip to bounding rect to prevent overflow
        bounds = RectShape().floor_tiles(rect)
        return (
            self.left.floor_tiles(left_rect)
            | self.right.floor_tiles(right_rect)
        ) & bounds


# ── Shape registry ────────────────────────────────────────────────

_SHAPE_REGISTRY: dict[str, type[RoomShape]] = {
    "rect": RectShape,
    "circle": CircleShape,
    "hex": HexShape,
    "octagon": OctagonShape,
    "cross": CrossShape,
}

# Predefined hybrid combinations for serialization
_HYBRID_PRESETS: dict[str, tuple[str, str, str]] = {
    "hybrid_circle_rect_v": ("circle", "rect", "vertical"),
    "hybrid_rect_circle_v": ("rect", "circle", "vertical"),
    "hybrid_circle_rect_h": ("circle", "rect", "horizontal"),
    "hybrid_rect_circle_h": ("rect", "circle", "horizontal"),
    "hybrid_hex_rect_v": ("hex", "rect", "vertical"),
    "hybrid_rect_hex_v": ("rect", "hex", "vertical"),
    "hybrid_hex_rect_h": ("hex", "rect", "horizontal"),
    "hybrid_rect_hex_h": ("rect", "hex", "horizontal"),
    "hybrid_octagon_rect_v": ("octagon", "rect", "vertical"),
    "hybrid_rect_octagon_v": ("rect", "octagon", "vertical"),
    "hybrid_octagon_rect_h": ("octagon", "rect", "horizontal"),
    "hybrid_rect_octagon_h": ("rect", "octagon", "horizontal"),
}


def shape_from_type(type_name: str | None) -> RoomShape:
    """Resolve a shape type string to a RoomShape instance."""
    name = type_name or "rect"
    # Check simple shapes first
    cls = _SHAPE_REGISTRY.get(name)
    if cls:
        return cls()
    # Check hybrid presets
    preset = _HYBRID_PRESETS.get(name)
    if preset:
        left_name, right_name, split = preset
        return HybridShape(
            _SHAPE_REGISTRY[left_name](),
            _SHAPE_REGISTRY[right_name](),
            split,
        )
    return RectShape()


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
