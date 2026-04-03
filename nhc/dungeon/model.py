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
    GRASS = auto()


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

    Uses min(width, height) as the diameter, forced to an odd number
    so there is always a single center tile and clean cardinal points.
    The circle is centered in the rect; tiles outside remain void.
    """

    type_name = "circle"

    @staticmethod
    def _diameter(rect: Rect) -> int:
        """Effective diameter (always odd)."""
        d = min(rect.width, rect.height)
        return d if d % 2 == 1 else d + 1

    def floor_tiles(self, rect: Rect) -> set[tuple[int, int]]:
        d = self._diameter(rect)
        r = (d - 1) / 2
        if r <= 0:
            return set()
        cx = rect.x + (rect.width - 1) / 2
        cy = rect.y + (rect.height - 1) / 2
        # Use (r + 0.5)² so edge tiles that the SVG circle covers
        # are included as walkable floor.
        r_eff = r + 0.5
        return {
            (x, y)
            for y in range(rect.y, rect.y2)
            for x in range(rect.x, rect.x2)
            if (x - cx) ** 2 + (y - cy) ** 2 <= r_eff ** 2
        }

    def cardinal_walls(self, rect: Rect) -> list[tuple[int, int]]:
        """Return the 4 cardinal wall positions (N, S, E, W).

        These are the wall tiles directly outside the circle at
        the north, south, east, and west extremes.
        """
        d = self._diameter(rect)
        r = (d - 1) // 2
        cx = rect.x + (rect.width - 1) // 2
        cy = rect.y + (rect.height - 1) // 2
        return [
            (cx, cy - r - 1),  # north
            (cx, cy + r + 1),  # south
            (cx - r - 1, cy),  # west
            (cx + r + 1, cy),  # east
        ]



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
        # Split exactly at the midpoint — no overlap needed because
        # CircleShape uses a generous radius (r + 0.5) that naturally
        # covers the seam tiles.
        if self.split == "vertical":
            mid = rect.x + rect.width // 2
            left_rect = Rect(
                rect.x, rect.y, mid - rect.x, rect.height,
            )
            right_rect = Rect(mid, rect.y, rect.x2 - mid, rect.height)
        else:
            mid = rect.y + rect.height // 2
            left_rect = Rect(
                rect.x, rect.y, rect.width, mid - rect.y,
            )
            right_rect = Rect(rect.x, mid, rect.width, rect.y2 - mid)

        base = (
            self.left.floor_tiles(left_rect)
            | self.right.floor_tiles(right_rect)
        )

        # Include diagonal transition tiles between the circle arc
        # endpoints and the rect corners at the seam.  The SVG draws
        # these as straight lines so they appear walkable.
        diag = self._diagonal_tiles(rect, left_rect, right_rect)

        # Clip to bounding rect to prevent overflow
        bounds = RectShape().floor_tiles(rect)
        return (base | diag) & bounds

    def _diagonal_tiles(
        self, rect: Rect,
        left_rect: Rect, right_rect: Rect,
    ) -> set[tuple[int, int]]:
        """Tiles inside the diagonal transition between arc and rect."""
        # Find which sub-shape is the circle
        circle_sub: RoomShape | None = None
        circle_side = ""
        for side, sub in [("left", self.left), ("right", self.right)]:
            if isinstance(sub, CircleShape):
                circle_sub = sub
                circle_side = side
                break
        if circle_sub is None:
            return set()

        # Compute circle geometry (matching SVG calculations)
        if self.split == "vertical":
            sub_r = left_rect if circle_side == "left" else right_rect
            tw, th = sub_r.width, rect.height
            d = circle_sub._diameter(Rect(0, 0, tw, th))
            radius = d / 2
            ccx = sub_r.x + sub_r.width / 2
            ccy = rect.y + rect.height / 2
            # Arc endpoints (top and bottom of semicircle)
            arc_top = (ccx, ccy - radius)
            arc_bot = (ccx, ccy + radius)
            mid = rect.x + rect.width // 2
            if circle_side == "left":
                # Diagonals: arc_top → (mid, rect.y)
                #            arc_bot → (mid, rect.y2)
                corner_top = (mid, rect.y)
                corner_bot = (mid, rect.y2)
            else:
                # Diagonals: arc_top → (mid, rect.y)
                #            arc_bot → (mid, rect.y2)
                corner_top = (mid, rect.y)
                corner_bot = (mid, rect.y2)
        else:
            sub_r = left_rect if circle_side == "left" else right_rect
            tw, th = rect.width, sub_r.height
            d = circle_sub._diameter(Rect(0, 0, tw, th))
            radius = d / 2
            ccx = rect.x + rect.width / 2
            ccy = sub_r.y + sub_r.height / 2
            # Arc endpoints (left and right of semicircle)
            arc_left = (ccx - radius, ccy)
            arc_right = (ccx + radius, ccy)
            mid = rect.y + rect.height // 2
            if circle_side == "left":
                corner_left = (rect.x, mid)
                corner_right = (rect.x2, mid)
            else:
                corner_left = (rect.x, mid)
                corner_right = (rect.x2, mid)

        # Rasterize: include tiles whose center is inside the two
        # diagonal triangles (between arc endpoint and rect corner).
        tiles: set[tuple[int, int]] = set()
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                tx, ty = x + 0.5, y + 0.5
                if self.split == "vertical":
                    at_x, at_y = arc_top
                    ab_x, ab_y = arc_bot
                    ct_x, ct_y = corner_top
                    cb_x, cb_y = corner_bot
                    # Upper line from arc_top to corner_top
                    if ct_x != at_x:
                        y_upper = at_y + (ct_y - at_y) * (tx - at_x) / (ct_x - at_x)
                    else:
                        continue
                    # Lower line from arc_bot to corner_bot
                    if cb_x != ab_x:
                        y_lower = ab_y + (cb_y - ab_y) * (tx - ab_x) / (cb_x - ab_x)
                    else:
                        continue
                    # Check tile is in the diagonal zone
                    x_min = min(at_x, ct_x)
                    x_max = max(at_x, ct_x)
                    if x_min <= tx <= x_max and y_upper <= ty <= y_lower:
                        tiles.add((x, y))
                else:
                    al_x, al_y = arc_left
                    ar_x, ar_y = arc_right
                    cl_x, cl_y = corner_left
                    cr_x, cr_y = corner_right
                    # Left line from arc_left to corner_left
                    if cl_y != al_y:
                        x_left = al_x + (cl_x - al_x) * (ty - al_y) / (cl_y - al_y)
                    else:
                        continue
                    # Right line from arc_right to corner_right
                    if cr_y != ar_y:
                        x_right = ar_x + (cr_x - ar_x) * (ty - ar_y) / (cr_y - ar_y)
                    else:
                        continue
                    y_min = min(al_y, cl_y)
                    y_max = max(al_y, cl_y)
                    if y_min <= ty <= y_max and x_left <= tx <= x_right:
                        tiles.add((x, y))

        return tiles


# ── Shape registry ────────────────────────────────────────────────

_SHAPE_REGISTRY: dict[str, type[RoomShape]] = {
    "rect": RectShape,
    "circle": CircleShape,
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
        return self.terrain in (Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)

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
    feeling: str = "normal"
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
