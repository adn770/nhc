"""Inhabited-settlement sub-hex sites are not bare fields.

The ``inhabited_settlement`` family handles the FARM, CAMPSITE
and ORCHARD minor features. The original implementation dropped
a single ``farmhouse_door`` feature tile on the bare floor of an
enclosed rectangle plus one NPC; no farmhouse walls, no orchard
trees, no campfire area. The player saw a 30×20 grass field with
a door floating in the middle and an NPC next to it — didn't
read as a farm.

These tests pin the richer layout:

- FARM: an enclosed farmhouse (walls + one door opening), the
  farmhouse_door on the wall, the farmer inside, the player's
  entry tile reachable to the door via floor.
- ORCHARD: several ``tree`` feature tiles in a grid pattern.
- CAMPSITE: stays open (no interior walls), campfire present,
  NPC next to fire.
"""

from __future__ import annotations

from collections import deque

import pytest

from nhc.dungeon.model import Terrain
from nhc.hexcrawl.model import Biome, MinorFeatureType
from nhc.hexcrawl.sub_hex_sites import (
    SiteTier,
    generate_inhabited_settlement_site,
)


def _site(feature: MinorFeatureType, seed: int = 1):
    return generate_inhabited_settlement_site(
        feature=feature,
        biome=Biome.GREENLANDS,
        seed=seed,
        tier=SiteTier.MEDIUM,
    )


def _collect(level, terrain=None, feature=None):
    out: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tile_at(x, y)
            if tile is None:
                continue
            if terrain is not None and tile.terrain is not terrain:
                continue
            if feature is not None and tile.feature != feature:
                continue
            out.append((x, y))
    return out


def _reachable_floor(level, start):
    """BFS across FLOOR tiles from ``start``. Doors count as floor
    so the path through the farmhouse door isn't blocked."""
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nb = (x + dx, y + dy)
            if nb in seen:
                continue
            tile = level.tile_at(*nb)
            if tile is None:
                continue
            # Floor, or a door tile (which is FLOOR + feature).
            if tile.terrain is Terrain.FLOOR:
                seen.add(nb)
                q.append(nb)
    return seen


class TestFarmVariant:
    def test_has_interior_farmhouse_walls(self) -> None:
        """FARM stamps a small farmhouse — interior walls beyond
        the outer perimeter. A bare rectangle (current behaviour)
        would leave only the 1-tile perimeter, which fails here."""
        site = _site(MinorFeatureType.FARM)
        w, h = site.level.width, site.level.height
        perimeter = {
            (x, y)
            for y in range(h) for x in range(w)
            if x in (0, w - 1) or y in (0, h - 1)
        }
        walls = set(_collect(site.level, terrain=Terrain.WALL))
        interior_walls = walls - perimeter
        assert interior_walls, (
            "FARM must stamp interior walls (a small farmhouse), "
            "not rely only on the perimeter"
        )

    def test_has_exactly_one_farmhouse_door(self) -> None:
        site = _site(MinorFeatureType.FARM)
        doors = _collect(site.level, feature="farmhouse_door")
        assert len(doors) == 1, (
            f"expected exactly one farmhouse_door, got {len(doors)}"
        )

    def test_farmhouse_door_sits_on_a_wall(self) -> None:
        """The door tile is a gap in the farmhouse wall — at
        least one of its orthogonal neighbours must be an inner
        WALL so the door clearly opens into / out of a building."""
        site = _site(MinorFeatureType.FARM)
        doors = _collect(site.level, feature="farmhouse_door")
        assert doors
        dx, dy = doors[0]
        neighbours = [
            site.level.tile_at(dx + ox, dy + oy)
            for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        ]
        wall_neighbours = [
            t for t in neighbours
            if t is not None and t.terrain is Terrain.WALL
        ]
        assert len(wall_neighbours) >= 1, (
            "farmhouse_door must have at least one wall neighbour "
            "— otherwise it is a floating door on open ground"
        )

    def test_farmer_sits_inside_a_walled_interior(self) -> None:
        """The farmer NPC's tile sits inside the farmhouse: at
        least three of the four cardinal directions must hit a
        WALL within four steps. The fourth (south, through the
        door) legitimately opens onto the field — this is how
        the player walks in."""
        site = _site(MinorFeatureType.FARM)
        assert site.population.npcs, "expected a farmer NPC"
        npc_id, npc_xy = site.population.npcs[0]
        assert npc_id == "farmer"
        x, y = npc_xy
        walled_dirs = 0
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            for step in range(1, 5):
                tile = site.level.tile_at(
                    x + dx * step, y + dy * step,
                )
                if tile is None:
                    walled_dirs += 1
                    break
                if tile.terrain is Terrain.WALL:
                    walled_dirs += 1
                    break
        assert walled_dirs >= 3, (
            f"farmer NPC has walls within reach on only "
            f"{walled_dirs} of 4 cardinal directions — it's not "
            f"inside a farmhouse"
        )

    def test_entry_reaches_farmhouse_door_via_floor(self) -> None:
        """Player lands on entry_tile and must be able to walk to
        the farmhouse door through FLOOR tiles only (no clipping
        through walls). Door tile counts as floor."""
        site = _site(MinorFeatureType.FARM)
        reachable = _reachable_floor(site.level, site.entry_tile)
        doors = _collect(site.level, feature="farmhouse_door")
        assert doors[0] in reachable, (
            "farmhouse_door not reachable from entry tile"
        )


class TestCampsiteVariant:
    def test_campsite_has_campfire_feature(self) -> None:
        site = _site(MinorFeatureType.CAMPSITE)
        assert _collect(site.level, feature="campfire"), (
            "CAMPSITE must place a campfire feature tile"
        )

    def test_campsite_stays_open_ground(self) -> None:
        """A campsite is a clearing — no interior walls beyond
        the 1-tile perimeter the shell already stamps."""
        site = _site(MinorFeatureType.CAMPSITE)
        w, h = site.level.width, site.level.height
        perimeter = {
            (x, y)
            for y in range(h) for x in range(w)
            if x in (0, w - 1) or y in (0, h - 1)
        }
        walls = set(_collect(site.level, terrain=Terrain.WALL))
        interior_walls = walls - perimeter
        assert not interior_walls, (
            f"CAMPSITE should have no interior walls, got "
            f"{len(interior_walls)}"
        )


class TestOrchardVariant:
    def test_orchard_has_multiple_tree_features(self) -> None:
        """ORCHARD is not a single tree — it's rows of them. At
        least four ``tree`` feature tiles."""
        site = _site(MinorFeatureType.ORCHARD)
        trees = _collect(site.level, feature="tree")
        assert len(trees) >= 4, (
            f"ORCHARD expected at least 4 tree feature tiles, "
            f"got {len(trees)}"
        )
