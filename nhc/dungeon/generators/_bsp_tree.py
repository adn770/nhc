"""BSP tree data structure and subdivision logic."""

from __future__ import annotations

import random
from dataclasses import dataclass

from nhc.dungeon.model import Rect

MIN_LEAF = 9
MAX_ROOM = 10
MIN_ROOM = 4
PADDING = 2  # ≥2 ensures void gap between adjacent rooms' walls


@dataclass
class _Node:
    rect: Rect
    left: _Node | None = None
    right: _Node | None = None
    room: Rect | None = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    def leaves(self) -> list[_Node]:
        if self.is_leaf:
            return [self]
        out: list[_Node] = []
        if self.left:
            out += self.left.leaves()
        if self.right:
            out += self.right.leaves()
        return out


def _split(
    node: _Node, rng: random.Random,
    min_leaf: int = MIN_LEAF,
) -> None:
    """Recursively split a BSP node.

    ``min_leaf`` tunes how small a leaf can be before splits stop.
    Dungeon callers use the module-level :data:`MIN_LEAF` (9);
    building partitioners pass a tighter value (5) so small
    footprints still get multiple rooms.
    """
    w, h = node.rect.width, node.rect.height
    if w < min_leaf * 2 and h < min_leaf * 2:
        return

    if w > h * 1.25:
        horiz = False
    elif h > w * 1.25:
        horiz = True
    else:
        horiz = rng.random() < 0.5

    if horiz:
        if h < min_leaf * 2:
            return
        at = rng.randint(min_leaf, h - min_leaf)
        node.left = _Node(Rect(node.rect.x, node.rect.y, w, at))
        node.right = _Node(Rect(node.rect.x, node.rect.y + at, w, h - at))
    else:
        if w < min_leaf * 2:
            return
        at = rng.randint(min_leaf, w - min_leaf)
        node.left = _Node(Rect(node.rect.x, node.rect.y, at, h))
        node.right = _Node(Rect(node.rect.x + at, node.rect.y, w - at, h))

    _split(node.left, rng, min_leaf=min_leaf)
    _split(node.right, rng, min_leaf=min_leaf)


def _place_room(leaf: _Node, rng: random.Random) -> None:
    """Place a random room inside a BSP leaf."""
    mw = min(MAX_ROOM, leaf.rect.width - PADDING * 2)
    mh = min(MAX_ROOM, leaf.rect.height - PADDING * 2)
    if mw < MIN_ROOM or mh < MIN_ROOM:
        return
    w = rng.randint(MIN_ROOM, mw)
    h = rng.randint(MIN_ROOM, mh)
    x = leaf.rect.x + rng.randint(PADDING, leaf.rect.width - w - PADDING)
    y = leaf.rect.y + rng.randint(PADDING, leaf.rect.height - h - PADDING)
    leaf.room = Rect(x, y, w, h)
