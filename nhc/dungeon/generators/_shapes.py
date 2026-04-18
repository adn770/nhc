"""Room shape selection and carving for BSP dungeons."""

from __future__ import annotations

import random
from typing import Callable

from nhc.dungeon.model import (
    CircleShape,
    CrossShape,
    HybridShape,
    Level,
    OctagonShape,
    PillShape,
    Rect,
    RectShape,
    RoomShape,
    TempleShape,
    Terrain,
    Tile,
)


_SHAPE_NAME_TO_FACTORY: dict[str, Callable[[], RoomShape]] = {
    "rect": RectShape,
    "circle": CircleShape,
    "octagon": OctagonShape,
    "pill": PillShape,
    "cross": CrossShape,
}


def _pick_shape(
    rect: Rect, variety: float, rng: random.Random,
    preferred_shapes: list[str] | None = None,
) -> RoomShape:
    """Choose a room shape based on variety setting and rect size.

    When *preferred_shapes* is set (from a StructuralTemplate),
    only those shape types are considered. Geometric constraints
    still apply — if no preferred shape fits, falls back to rect.
    """
    if variety <= 0 or rng.random() >= variety:
        return RectShape()
    min_dim = min(rect.width, rect.height)
    max_dim = max(rect.width, rect.height)

    if min_dim < 5:
        return RectShape()

    # When preferred_shapes restricts the palette, skip the
    # hybrid lottery and go straight to candidate filtering.
    if preferred_shapes is None:
        # Hybrids: half-circle + rect. Split along the longer axis
        # so the circle half is near-square.  The half that receives
        # the circle must have an odd dimension for clean cardinal
        # points (CircleShape enforces odd diameter internally).
        if max_dim >= 7 and rng.random() < 0.20:
            if rect.width >= rect.height:
                split = "vertical"
            else:
                split = "horizontal"
            return HybridShape(CircleShape(), RectShape(), split)

    # Collect eligible (name, factory) pairs for this room size.
    eligible: list[tuple[str, Callable[[], RoomShape]]] = [
        ("octagon", OctagonShape),
        ("cross", CrossShape),
    ]
    # Circles only for near-square rooms where both dimensions
    # are odd (ensures integer center and clean cardinal points)
    if (max_dim / min_dim <= 1.3
            and rect.width % 2 == 1 and rect.height % 2 == 1):
        eligible.append(("circle", CircleShape))
    # Pills only for elongated rooms where the short dimension
    # is odd (clean integer geometry for the semicircle caps).
    if (max_dim - min_dim >= 2 and min_dim >= 5 and min_dim % 2 == 1):
        eligible.append(("pill", PillShape))
    # Temples need room for 4 arms with rounded caps. Require
    # both dimensions odd and min_dim >= 7.
    if (min_dim >= 7
            and rect.width % 2 == 1 and rect.height % 2 == 1):
        eligible.append((
            "temple",
            lambda r=rng: TempleShape(
                flat_side=r.choice(TempleShape.VALID_SIDES),
            ),
        ))

    # Filter to preferred shapes when a template restricts them.
    if preferred_shapes is not None:
        allowed = set(preferred_shapes)
        eligible = [(n, f) for n, f in eligible if n in allowed]
        if not eligible:
            return RectShape()

    return rng.choice(eligible)[1]()


def _carve_room(
    level: Level, rect: Rect, shape: RoomShape | None = None,
) -> None:
    """Carve floor tiles for a room shape within the given rect."""
    tiles = (shape or RectShape()).floor_tiles(rect)
    for x, y in tiles:
        if level.in_bounds(x, y):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
