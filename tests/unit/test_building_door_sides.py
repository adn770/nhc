"""Building-interior entry doors must carry door_side metadata.

Every site assembler places a ``door_closed`` tile on the
building's perimeter so the player can cross from the site
surface into the interior. M2 fixed door_side on the *surface*
side of those doors (``paint_surface_doors``); the matching
interior-side tile was left with ``door_side=""`` so the web
client rendered the interior doors on the wrong wall.

The fix runs ``_compute_door_sides`` on every building ground
floor after doors are stamped, using a FLOOR-direction fallback
for levels that lack ``level.rooms`` entries (building interiors
are single-room spaces without a Room object attached).
"""

from __future__ import annotations

import random

from nhc.dungeon.site import assemble_site


VALID_SIDES = {"north", "south", "east", "west"}


def _ground_doors(building) -> list:
    ground = building.ground
    out = []
    for y in range(ground.height):
        for x in range(ground.width):
            t = ground.tiles[y][x]
            if (t.feature or "").startswith("door_"):
                out.append((x, y, t))
    return out


def _assert_doors_have_sides(site) -> None:
    found = 0
    for b in site.buildings:
        for x, y, tile in _ground_doors(b):
            assert tile.door_side in VALID_SIDES, (
                f"building {b.id} door at ({x},{y}) has "
                f"door_side={tile.door_side!r}"
            )
            found += 1
    assert found > 0, "expected at least one building-entry door"


def test_town_building_entry_doors_have_side():
    site = assemble_site("town", "t_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_keep_building_entry_doors_have_side():
    site = assemble_site("keep", "k_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_tower_building_entry_door_has_side():
    site = assemble_site("tower", "tw_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_mansion_building_entry_doors_have_side():
    site = assemble_site("mansion", "m_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_farm_building_entry_doors_have_side():
    site = assemble_site("farm", "f_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_cottage_building_entry_door_has_side():
    site = assemble_site("cottage", "c_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_temple_building_entry_doors_have_side():
    site = assemble_site("temple", "te_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_ruin_building_entry_doors_have_side():
    site = assemble_site("ruin", "r_doors", random.Random(7))
    _assert_doors_have_sides(site)


def test_side_points_toward_interior_floor():
    """The door_side semantic is 'direction of the room interior
    floor' (matching the BSP dungeon behaviour). For a building
    entry door the interior floor sits opposite the building
    boundary, so door_side must point at a FLOOR neighbour, not
    at a wall or void neighbour."""
    from nhc.dungeon.model import Terrain
    site = assemble_site("town", "t_dir", random.Random(11))
    for b in site.buildings:
        for x, y, tile in _ground_doors(b):
            side = tile.door_side
            delta = {
                "north": (0, -1), "south": (0, 1),
                "east": (1, 0), "west": (-1, 0),
            }[side]
            nx, ny = x + delta[0], y + delta[1]
            nb = b.ground.tile_at(nx, ny)
            assert nb is not None and nb.terrain == Terrain.FLOOR, (
                f"door at ({x},{y}) side={side!r} points at "
                f"{nb.terrain if nb else None}, not FLOOR"
            )
