"""Role-first town building sizing + archetype partitioning (C3).

M14 added per-role entries in ``ARCHETYPE_CONFIG`` (tavern 13-16,
shop 10-12, temple 14-16, etc.) but town buildings still drew
from the residential (7-9) size range and partitioned as
residential. C3 wires role → size → partitioner end to end, so
the tavern actually lands a 13-16 footprint and a multi-room
rect_bsp interior.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.sites.town import (
    SERVICE_ROLES_WITH_NPCS,
    SERVICE_ROLES_RESERVED,
    assemble_town,
)


def _role_of(building) -> str:
    """Pull the role tag from the ground-floor entrance room."""
    for tag in building.ground.rooms[0].tags:
        if tag in SERVICE_ROLES_WITH_NPCS + SERVICE_ROLES_RESERVED:
            return tag
    return "residential"


class TestRoleFirstSizing:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_building_footprint_matches_role_size_range(
        self, size_class,
    ):
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            for b in site.buildings:
                role = _role_of(b)
                spec = ARCHETYPE_CONFIG[role]
                lo, hi = spec.size_range
                assert lo <= b.base_rect.width <= hi, (
                    f"seed={seed} {size_class}: {b.id} role={role} "
                    f"width={b.base_rect.width} not in "
                    f"[{lo}, {hi}]"
                )
                assert lo <= b.base_rect.height <= hi, (
                    f"seed={seed} {size_class}: {b.id} role={role} "
                    f"height={b.base_rect.height} not in "
                    f"[{lo}, {hi}]"
                )


class TestPerRolePartitioning:
    def test_inn_has_multiple_rooms(self):
        """inn archetype partitions with rect_bsp doorway mode —
        ground floor must have ≥ 3 rooms, not the 1-2 a divided
        partitioner would produce on the same footprint."""
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            inn = next(
                (b for b in site.buildings if _role_of(b) == "inn"),
                None,
            )
            if inn is None:
                continue
            assert len(inn.ground.rooms) >= 3, (
                f"seed={seed}: inn {inn.id} has "
                f"{len(inn.ground.rooms)} rooms — rect_bsp doorway "
                "should carve ≥ 3"
            )

    def test_shop_has_multiple_rooms(self):
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            shop = next(
                (b for b in site.buildings if _role_of(b) == "shop"),
                None,
            )
            if shop is None:
                continue
            assert len(shop.ground.rooms) >= 3, (
                f"seed={seed}: shop {shop.id} has "
                f"{len(shop.ground.rooms)} rooms — rect_bsp doorway "
                "should carve ≥ 3"
            )

    def test_temple_has_nave_and_chapels(self):
        """Temple partitioner carves a large nave + at least two
        flanking chapels (≥ 3 rooms total)."""
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            temple = next(
                (b for b in site.buildings
                 if _role_of(b) == "temple"),
                None,
            )
            if temple is None:
                continue
            assert len(temple.ground.rooms) >= 3, (
                f"seed={seed}: temple {temple.id} has "
                f"{len(temple.ground.rooms)} rooms — expected "
                "nave + ≥ 2 chapels"
            )
