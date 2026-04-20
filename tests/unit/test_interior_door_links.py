"""Cross-building door link tests (M15).

:class:`InteriorDoorLink` pairs door tiles on mirrored perimeter
positions across two buildings; site assemblers populate the
list on ``Site.interior_door_links``. Door state must stay in
sync across the pair — :func:`sync_linked_door_state` is the
helper actions and ``tick_doors`` call to propagate changes.
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.model import Level, Rect, RectShape, Terrain, Tile
from nhc.dungeon.site import (
    InteriorDoorLink, Site, sync_linked_door_state,
)
from nhc.dungeon.sites.mansion import assemble_mansion


def _tiny_building(building_id: str, x0: int) -> Building:
    """A 1-floor 4x4 building at ``(x0, 1)`` with all FLOOR tiles."""
    rect = Rect(x0, 1, 4, 4)
    level = Level.create_empty(
        f"{building_id}_f0", f"{building_id} f0",
        1, x0 + 8, 8,
    )
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.building_id = building_id
    level.floor_index = 0
    return Building(
        id=building_id, base_shape=RectShape(), base_rect=rect,
        floors=[level],
    )


class TestInteriorDoorLinkDataclass:
    def test_constructs_with_expected_fields(self):
        link = InteriorDoorLink(
            from_building="a", to_building="b",
            floor=0, from_tile=(3, 2), to_tile=(4, 2),
        )
        assert link.from_building == "a"
        assert link.to_building == "b"
        assert link.floor == 0
        assert link.from_tile == (3, 2)
        assert link.to_tile == (4, 2)


class TestMansionInteriorDoorLinks:
    def test_mansion_populates_links_for_adjacent_pairs(self):
        """Every mansion with ≥ 2 buildings and overlapping
        perimeters gets at least one InteriorDoorLink."""
        found = False
        for seed in range(30):
            site = assemble_mansion("m1", random.Random(seed))
            if len(site.buildings) >= 2 and site.interior_door_links:
                found = True
                break
        assert found, "no mansion seed produced an interior door link"

    def test_mansion_link_matches_legacy_interior_doors(self):
        """The new list mirrors the legacy dict — for every link in
        interior_door_links there is a symmetric pair of dict
        entries."""
        for seed in range(30):
            site = assemble_mansion("m1", random.Random(seed))
            for link in site.interior_door_links:
                key_from = (
                    link.from_building,
                    link.from_tile[0],
                    link.from_tile[1],
                )
                key_to = (
                    link.to_building,
                    link.to_tile[0],
                    link.to_tile[1],
                )
                assert site.interior_doors.get(key_from) == (
                    link.to_building,
                    link.to_tile[0],
                    link.to_tile[1],
                )
                assert site.interior_doors.get(key_to) == (
                    link.from_building,
                    link.from_tile[0],
                    link.from_tile[1],
                )


class TestSyncLinkedDoorState:
    def _site_with_link(self) -> Site:
        a = _tiny_building("a", 0)
        b = _tiny_building("b", 5)
        site = Site(
            id="s", kind="mansion",
            buildings=[a, b],
            surface=Level.create_empty("surf", "surf", 0, 10, 8),
        )
        # Stamp a door tile on each side.
        a.floors[0].tiles[2][3].feature = "door_closed"
        b.floors[0].tiles[2][5].feature = "door_closed"
        site.interior_door_links.append(InteriorDoorLink(
            from_building="a", to_building="b",
            floor=0, from_tile=(3, 2), to_tile=(5, 2),
        ))
        return site

    def test_open_on_one_side_propagates(self):
        site = self._site_with_link()
        # Open A side.
        site.buildings[0].floors[0].tiles[2][3].feature = "door_open"
        site.buildings[0].floors[0].tiles[2][3].opened_at_turn = 7
        sync_linked_door_state(site, "a", (3, 2))
        b_tile = site.buildings[1].floors[0].tiles[2][5]
        assert b_tile.feature == "door_open"
        assert b_tile.opened_at_turn == 7

    def test_close_on_one_side_propagates(self):
        site = self._site_with_link()
        # Start both open, then close A.
        for tile in (
            site.buildings[0].floors[0].tiles[2][3],
            site.buildings[1].floors[0].tiles[2][5],
        ):
            tile.feature = "door_open"
            tile.opened_at_turn = 5
        site.buildings[0].floors[0].tiles[2][3].feature = "door_closed"
        site.buildings[0].floors[0].tiles[2][3].opened_at_turn = None
        sync_linked_door_state(site, "a", (3, 2))
        b_tile = site.buildings[1].floors[0].tiles[2][5]
        assert b_tile.feature == "door_closed"
        assert b_tile.opened_at_turn is None

    def test_sync_reverse_direction(self):
        """Syncing from ``to_building`` side propagates back to
        ``from_building`` side."""
        site = self._site_with_link()
        site.buildings[1].floors[0].tiles[2][5].feature = "door_open"
        site.buildings[1].floors[0].tiles[2][5].opened_at_turn = 9
        sync_linked_door_state(site, "b", (5, 2))
        a_tile = site.buildings[0].floors[0].tiles[2][3]
        assert a_tile.feature == "door_open"
        assert a_tile.opened_at_turn == 9

    def test_sync_on_unlinked_tile_is_noop(self):
        site = self._site_with_link()
        # No change expected; just make sure no exception.
        sync_linked_door_state(site, "a", (0, 0))
