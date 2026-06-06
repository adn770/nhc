"""Secret doors render as plain wall in the floor IR.

A ``door_secret`` tile is terrain ``FLOOR`` carrying the hidden-door
feature, so the geometry pipeline would otherwise paint an open
doorway through the wall. Discovery flips the feature to
``door_closed`` (see ``actions/_interaction`` search + the detection
ring), so every tile that is *still* ``door_secret`` is by definition
undiscovered — we can mask all of them to wall with no discovery
check. The mask is render-only: the live ``Level`` keeps the secret
door so movement / search still work.
"""

from __future__ import annotations

import dataclasses

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.rendering._ir_helpers import mask_secret_doors_as_walls


def _level_with_secret_door() -> Level:
    lvl = Level.create_empty("d", "D", 1, 5, 3)
    # Room floor at (1,1), secret door at (2,1) bridging to a corridor.
    lvl.set_tile(1, 1, Tile(terrain=Terrain.FLOOR, explored=True,
                            visible=True))
    lvl.set_tile(2, 1, Tile(terrain=Terrain.FLOOR, feature="door_secret",
                            door_side="west", explored=True, visible=True))
    lvl.set_tile(3, 1, Tile(terrain=Terrain.FLOOR))
    return lvl


def test_secret_door_tile_becomes_wall():
    lvl = _level_with_secret_door()
    masked = mask_secret_doors_as_walls(lvl)
    t = masked.tile_at(2, 1)
    assert t.terrain is Terrain.WALL
    assert t.feature is None
    assert t.door_side == ""


def test_mask_preserves_explored_and_visible():
    # The player has seen this "wall", so it must read as already
    # explored — otherwise it would fog/hatch differently from the
    # adjacent seen walls.
    masked = mask_secret_doors_as_walls(_level_with_secret_door())
    t = masked.tile_at(2, 1)
    assert t.explored is True and t.visible is True


def test_original_level_is_not_mutated():
    lvl = _level_with_secret_door()
    mask_secret_doors_as_walls(lvl)
    orig = lvl.tile_at(2, 1)
    assert orig.terrain is Terrain.FLOOR
    assert orig.feature == "door_secret"


def test_non_secret_tiles_are_preserved():
    lvl = _level_with_secret_door()
    masked = mask_secret_doors_as_walls(lvl)
    # Ordinary floor tiles pass through unchanged (same object is fine).
    assert masked.tile_at(1, 1).terrain is Terrain.FLOOR
    assert masked.tile_at(3, 1).terrain is Terrain.FLOOR


def test_visible_closed_door_is_untouched():
    # Only door_secret is masked; a discovered (closed) door still
    # renders as a normal door opening.
    lvl = Level.create_empty("d", "D", 1, 4, 3)
    lvl.set_tile(1, 1, Tile(terrain=Terrain.FLOOR, feature="door_closed",
                            door_side="west"))
    masked = mask_secret_doors_as_walls(lvl)
    t = masked.tile_at(1, 1)
    assert t.terrain is Terrain.FLOOR and t.feature == "door_closed"


def test_no_secret_doors_returns_same_level():
    # Cheap path: nothing to mask → no copy.
    lvl = Level.create_empty("d", "D", 1, 4, 3)
    lvl.set_tile(1, 1, Tile(terrain=Terrain.FLOOR))
    assert mask_secret_doors_as_walls(lvl) is lvl


def test_origin_and_metadata_carried_through():
    lvl = Level.create_empty("d", "D", 1, 4, 3, origin_x=10, origin_y=20)
    lvl.set_tile(11, 21, Tile(terrain=Terrain.FLOOR, feature="door_secret"))
    masked = mask_secret_doors_as_walls(lvl)
    assert (masked.origin_x, masked.origin_y) == (10, 20)
    assert masked.tile_at(11, 21).terrain is Terrain.WALL
    assert masked is not lvl
