"""After dropping the 1-tile VOID buffer ring around building
footprints on every site kind, two invariants hold across
town / keep / mansion / ruin / cottage / temple / farm:

1. No surface door is sealed -- every door tile on the site
   surface has at least one walkable 4-neighbour.
2. A tile immediately 4-adjacent to a building footprint (not
   in any footprint, within the surface bounds, and inside the
   enclosure polygon when one exists) is walkable FLOOR, not
   VOID -- the ring is gone.

These tests are a sweeping version of the per-site ring fix
reported from the live session, where an L-shaped town building
sealed its door inside a notch.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import Terrain
from nhc.sites._site import assemble_site


_SITE_KINDS_WITH_BUILDINGS = (
    "town", "keep", "mansion", "ruin", "cottage", "temple", "farm",
)


_SURFACE_WALKABLE = (Terrain.FLOOR, Terrain.GRASS)


def _walkable_neighbour_count(surface, x, y) -> int:
    count = 0
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = x + dx, y + dy
        if not surface.in_bounds(nx, ny):
            continue
        if surface.tiles[ny][nx].terrain in _SURFACE_WALKABLE:
            count += 1
    return count


@pytest.mark.parametrize("kind", _SITE_KINDS_WITH_BUILDINGS)
def test_every_surface_door_has_walkable_approach(kind: str) -> None:
    """For every seed, every surface door on every site kind
    must be adjacent to at least one walkable tile so the player
    can step onto it."""
    for seed in range(30):
        site = assemble_site(kind, f"s_{seed}", random.Random(seed))
        for (sx, sy), (bid, _bx, _by) in (
            site.building_doors.items()
        ):
            if not site.surface.in_bounds(sx, sy):
                continue
            tile = site.surface.tiles[sy][sx]
            assert tile.terrain in _SURFACE_WALKABLE, (
                f"{kind}/seed {seed}: door of {bid} at "
                f"({sx},{sy}) is not walkable"
            )
            assert _walkable_neighbour_count(
                site.surface, sx, sy,
            ) >= 1, (
                f"{kind}/seed {seed}: door of {bid} at "
                f"({sx},{sy}) has no walkable 4-neighbour -- "
                "sealed by neighbouring footprint or ring"
            )


@pytest.mark.parametrize("kind", _SITE_KINDS_WITH_BUILDINGS)
def test_no_void_ring_flanks_rect_buildings(kind: str) -> None:
    """A tile 4-adjacent to a rectangular building footprint
    must be walkable FLOOR when it is not inside any other
    building's footprint (and, for walled sites, inside the
    enclosure). Catches a lingering buffer ring."""
    from nhc.dungeon.model import RectShape
    found_any_flank = False
    for seed in range(20):
        site = assemble_site(kind, f"s_{seed}", random.Random(seed))
        all_footprints: set[tuple[int, int]] = set()
        for b in site.buildings:
            all_footprints |= b.base_shape.floor_tiles(b.base_rect)
        if site.enclosure is not None:
            xs = [p[0] for p in site.enclosure.polygon]
            ys = [p[1] for p in site.enclosure.polygon]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
        else:
            min_x = min_y = 0
            max_x, max_y = site.surface.width, site.surface.height
        for b in site.buildings:
            if not isinstance(b.base_shape, RectShape):
                continue
            fp = b.base_shape.floor_tiles(b.base_rect)
            for (x, y) in fp:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in all_footprints:
                        continue
                    if not (min_x <= nx < max_x
                            and min_y <= ny < max_y):
                        continue
                    if not site.surface.in_bounds(nx, ny):
                        continue
                    tile = site.surface.tiles[ny][nx]
                    assert tile.terrain in _SURFACE_WALKABLE, (
                        f"{kind}/seed {seed}: footprint at "
                        f"({x},{y}) has VOID neighbour "
                        f"({nx},{ny}) -- buffer ring still in "
                        "place"
                    )
                    found_any_flank = True
    assert found_any_flank, (
        f"{kind}: no flanking tile exercised by any seed"
    )
