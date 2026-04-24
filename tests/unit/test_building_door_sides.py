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

from nhc.sites._site import assemble_site


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


def test_side_matches_outside_neighbour_direction():
    """Every building-entry door is stamped via
    :func:`stamp_building_door`, which records ``door_side`` as
    the direction from the door tile to its ``outside_neighbour``.
    The same neighbour is the surface-side door coordinate, so
    the building interior and the surface describe the *same*
    physical wall from their respective sides. No heuristic
    involved -- this test pins the precise invariant across
    every site kind."""
    from nhc.sites._site import outside_neighbour
    _EXPECTED = {
        (0, -1): "north", (0, 1): "south",
        (1, 0): "east", (-1, 0): "west",
    }
    kinds = (
        "town", "keep", "tower", "mansion",
        "farm", "cottage", "ruin", "temple",
    )
    for kind in kinds:
        site = assemble_site(kind, f"{kind}_exact", random.Random(7))
        for b in site.buildings:
            for x, y, tile in _ground_doors(b):
                nb = outside_neighbour(b, x, y)
                if nb is None:
                    continue  # degenerate perimeter, no neighbour
                delta = (nb[0] - x, nb[1] - y)
                assert delta in _EXPECTED, (
                    f"{kind} door at ({x},{y}) has non-orthogonal "
                    f"outside neighbour delta {delta}"
                )
                assert tile.door_side == _EXPECTED[delta], (
                    f"{kind} door at ({x},{y}) "
                    f"door_side={tile.door_side!r} "
                    f"does not match outside_neighbour delta "
                    f"{delta}"
                )


def test_surface_and_interior_describe_same_wall():
    """The surface-painted door and the building-interior stamped
    door should point at *opposite* compass directions -- both
    describing the same physical wall from their own sides. This
    is the invariant that was broken in the live session: the
    building-interior door's side disagreed with the surface
    door's side."""
    _OPPOSITE = {
        "north": "south", "south": "north",
        "east": "west", "west": "east",
    }
    kinds = ("town", "keep", "mansion", "farm", "cottage", "ruin",
             "temple")
    for kind in kinds:
        site = assemble_site(
            kind, f"{kind}_consist", random.Random(7),
        )
        for (sx, sy), (bid, bx, by) in site.building_doors.items():
            surface_tile = site.surface.tile_at(sx, sy)
            if surface_tile is None:
                continue
            # Find the matching building and its interior door tile.
            building = next(b for b in site.buildings if b.id == bid)
            interior_tile = building.ground.tile_at(bx, by)
            assert surface_tile.door_side in _OPPOSITE
            assert interior_tile.door_side in _OPPOSITE
            assert interior_tile.door_side == _OPPOSITE[
                surface_tile.door_side
            ], (
                f"{kind} door mismatch: surface side="
                f"{surface_tile.door_side!r} but interior side="
                f"{interior_tile.door_side!r}; they must be "
                "opposite compass directions describing the same "
                "physical wall"
            )
