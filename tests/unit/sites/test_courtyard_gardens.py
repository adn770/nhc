"""City courtyards get garden patches that complement the pavement.

After the pave-courtyard post-pass turns the whole city interior into
PAVEMENT, ``_scatter_courtyard_gardens`` converts a fraction of those
open paved tiles into GARDEN patches (grass + trees / bushes / the
occasional formal flower bed). The pavement is complemented, not
replaced: most of the courtyard stays paved, and streets / door
approaches are left clear.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, Rect, SurfaceType, Terrain, Tile
from nhc.sites.town import _scatter_courtyard_gardens


def _paved_courtyard(w=24, h=24):
    """A surface that is all PAVEMENT inside a palisade rect, with one
    STREET column and a door tile to guard."""
    surf = Level.create_empty("s", "S", 0, w, h)
    rect = Rect(2, 2, w - 4, h - 4)
    for x in range(rect.x, rect.x2):
        for y in range(rect.y, rect.y2):
            surf.set_tile(x, y, Tile(terrain=Terrain.FLOOR,
                                     surface_type=SurfaceType.PAVEMENT))
    # A street column through the middle.
    for y in range(rect.y, rect.y2):
        surf.set_tile(rect.x + 6, y, Tile(terrain=Terrain.FLOOR,
                                          surface_type=SurfaceType.STREET))
    return surf, rect


def _counts(surf):
    c = {"PAVEMENT": 0, "GARDEN": 0, "STREET": 0}
    veg = 0
    for _x, _y, t in surf.iter_world():
        n = t.surface_type.name
        if n in c:
            c[n] += 1
        if t.feature in ("tree", "bush", "flower"):
            veg += 1
    return c, veg


def test_some_pavement_becomes_garden():
    surf, rect = _paved_courtyard()
    before, _ = _counts(surf)
    _scatter_courtyard_gardens(surf, rect, set(), set(), random.Random(1))
    after, veg = _counts(surf)
    assert after["GARDEN"] > 0           # gardens were added
    assert veg > 0                       # gardens carry vegetation


def test_pavement_is_complemented_not_replaced():
    surf, rect = _paved_courtyard()
    before, _ = _counts(surf)
    _scatter_courtyard_gardens(surf, rect, set(), set(), random.Random(2))
    after, _ = _counts(surf)
    # Most of the courtyard stays paved.
    assert after["PAVEMENT"] > after["GARDEN"]
    assert after["GARDEN"] < before["PAVEMENT"] * 0.5


def test_streets_are_never_gardened():
    surf, rect = _paved_courtyard()
    _scatter_courtyard_gardens(surf, rect, set(), set(), random.Random(3))
    for y in range(rect.y, rect.y2):  # the street column
        assert surf.tile_at(rect.x + 6, y).surface_type is SurfaceType.STREET


def test_blocked_tiles_stay_paved():
    surf, rect = _paved_courtyard()
    # Guard a door tile + its 4-ring.
    door = (rect.x + 2, rect.y + 2)
    blocked = {door}
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        blocked.add((door[0] + dx, door[1] + dy))
    _scatter_courtyard_gardens(surf, rect, blocked, set(), random.Random(4))
    for (bx, by) in blocked:
        assert surf.tile_at(bx, by).surface_type is SurfaceType.PAVEMENT


def test_deterministic_for_same_seed():
    def run(seed):
        surf, rect = _paved_courtyard()
        _scatter_courtyard_gardens(surf, rect, set(), set(),
                                   random.Random(seed))
        return {(x, y): (t.surface_type.name, t.feature)
                for x, y, t in surf.iter_world()}
    assert run(7) == run(7)
    assert run(7) != run(8)


def test_trees_avoid_building_adjacent_tiles():
    surf, rect = _paved_courtyard()
    # A footprint tile in the courtyard; trees must not land 4-adjacent
    # to it (canopy would overlap the roof in the render).
    footprints = {(rect.x + 10, rect.y + 10)}
    _scatter_courtyard_gardens(surf, rect, set(), footprints,
                               random.Random(11))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        t = surf.tile_at(rect.x + 10 + dx, rect.y + 10 + dy)
        assert t.feature != "tree"
