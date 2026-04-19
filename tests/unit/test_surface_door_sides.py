"""Surface-door tiles carry ``door_side`` metadata.

Interior-dungeon doors get ``door_side`` set by
``_compute_door_sides`` after BSP generation. Surface doors
painted by ``paint_surface_doors`` used to leave the field empty,
which is why the web client's polygon renderer fell back to
drawing the door at the tile centre instead of snapping to the
building wall. M2 wires ``door_side`` through the painter using
the ``(sx, sy)`` → ``(building_id, bx, by)`` map the site
assemblers already populate.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.site import _compass
from nhc.dungeon.sites.cottage import assemble_cottage
from nhc.dungeon.sites.farm import assemble_farm
from nhc.dungeon.sites.keep import assemble_keep
from nhc.dungeon.sites.mansion import assemble_mansion
from nhc.dungeon.sites.ruin import assemble_ruin
from nhc.dungeon.sites.temple import assemble_temple
from nhc.dungeon.sites.town import assemble_town


class TestCompassHelper:
    @pytest.mark.parametrize(
        "delta, expected",
        [
            ((0, -1), "north"),
            ((0, 1), "south"),
            ((1, 0), "east"),
            ((-1, 0), "west"),
        ],
    )
    def test_orthogonal_deltas(
        self, delta: tuple[int, int], expected: str,
    ) -> None:
        assert _compass(*delta) == expected

    def test_zero_delta_raises(self) -> None:
        with pytest.raises(ValueError):
            _compass(0, 0)

    def test_diagonal_delta_raises(self) -> None:
        with pytest.raises(ValueError):
            _compass(1, 1)


VALID_SIDES = {"north", "south", "east", "west"}


def _assert_all_doors_tagged(site) -> None:
    surface = site.surface
    found = 0
    for (sx, sy), (_bid, bx, by) in site.building_doors.items():
        if not surface.in_bounds(sx, sy):
            continue
        tile = surface.tiles[sy][sx]
        assert tile.feature == "door_closed"
        assert tile.door_side in VALID_SIDES, (
            f"surface door at ({sx},{sy}) lacks door_side: "
            f"got {tile.door_side!r}"
        )
        # Door_side must point at the building-side coord.
        assert tile.door_side == _compass(bx - sx, by - sy)
        found += 1
    assert found > 0, "expected at least one in-bounds surface door"


class TestSiteSurfaceDoorsTagged:
    def test_town(self) -> None:
        site = assemble_town("t1", random.Random(1))
        _assert_all_doors_tagged(site)

    def test_keep(self) -> None:
        site = assemble_keep("k1", random.Random(1))
        _assert_all_doors_tagged(site)

    def test_mansion(self) -> None:
        site = assemble_mansion("m1", random.Random(1))
        _assert_all_doors_tagged(site)

    def test_farm(self) -> None:
        site = assemble_farm("f1", random.Random(1))
        _assert_all_doors_tagged(site)

    def test_cottage(self) -> None:
        site = assemble_cottage("c1", random.Random(1))
        _assert_all_doors_tagged(site)

    def test_ruin(self) -> None:
        site = assemble_ruin("r1", random.Random(1))
        _assert_all_doors_tagged(site)

    def test_temple(self) -> None:
        site = assemble_temple("te1", random.Random(1))
        _assert_all_doors_tagged(site)
