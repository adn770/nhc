"""Doors are framed as corridor doorways only on dungeon floors.

``_collect_corridor_tiles`` pulls door tiles into the corridor set so
a dungeon door reads as a framed doorway in the corridor wall. That is
wanted in a dungeon, but on a building floor (doors connect rooms) and
on a site surface (building *entry* doors on the street) it renders a
spurious 1-tile square around every door. Box doors only on real
dungeon floors: not building floors (``building_id`` set), not
prerevealed site surfaces.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.rendering._floor_layers import _collect_corridor_tiles


def _floor_with_door_and_corridor(*, building_id=None, prerevealed=False):
    lvl = Level.create_empty("f", "F", 1, 6, 4)
    lvl.building_id = building_id
    lvl.metadata.prerevealed = prerevealed
    # A door tile and a real corridor tile.
    lvl.set_tile(2, 1, Tile(terrain=Terrain.FLOOR, feature="door_closed",
                            door_side="west"))
    lvl.set_tile(4, 2, Tile(terrain=Terrain.FLOOR,
                            surface_type=SurfaceType.CORRIDOR))
    return lvl


def test_dungeon_door_is_collected_as_corridor():
    lvl = _floor_with_door_and_corridor()
    tiles = _collect_corridor_tiles(lvl, set())
    assert (2, 1) in tiles   # door framed as doorway
    assert (4, 2) in tiles   # real corridor


def test_building_floor_door_is_not_collected():
    lvl = _floor_with_door_and_corridor(building_id="b7")
    tiles = _collect_corridor_tiles(lvl, set())
    assert (2, 1) not in tiles   # no spurious box around the door
    assert (4, 2) in tiles       # real corridors still render


def test_site_surface_door_is_not_collected():
    # Town/keep/etc. surfaces ship prerevealed; building entry doors
    # on the street must not get a corridor box.
    lvl = _floor_with_door_and_corridor(prerevealed=True)
    tiles = _collect_corridor_tiles(lvl, set())
    assert (2, 1) not in tiles
    assert (4, 2) in tiles
