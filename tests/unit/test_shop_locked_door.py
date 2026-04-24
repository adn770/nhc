"""Shop-backroom locked-door rule (M17).

One ``door_locked`` per shop max, no locked doors elsewhere. See
``design/building_interiors.md`` — the lock gates a small
backroom (smallest BSP leaf) behind the shop counter.
"""

from __future__ import annotations

import random

from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.sites.town import assemble_town


def _doors_by_kind(site) -> dict[str, dict[str, int]]:
    """Count ``door_closed`` / ``door_locked`` per building id."""
    out: dict[str, dict[str, int]] = {}
    for b in site.buildings:
        counts = {"door_closed": 0, "door_locked": 0}
        for floor in b.floors:
            for row in floor.tiles:
                for t in row:
                    if t.feature in counts:
                        counts[t.feature] += 1
        out[b.id] = counts
    return out


class TestShopLockedDoor:
    def test_locked_door_rate_gate(self):
        """When ``locked_door_rate`` is positive, some seed must
        produce a shop with at least one ``door_locked``. We loop
        seeds until we find one — the rate is 0.08, so a few
        dozen seeds is plenty."""
        rate = ARCHETYPE_CONFIG["shop"].locked_door_rate
        assert rate > 0, (
            "shop archetype must carry a non-zero locked_door_rate "
            "for the rule to ever fire"
        )
        found = False
        for seed in range(200):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            counts = _doors_by_kind(site)
            locked = sum(
                v["door_locked"] for v in counts.values()
            )
            if locked > 0:
                found = True
                break
        assert found, "no seed in 200 produced a locked shop door"

    def test_only_shop_buildings_get_locked_doors(self):
        """For every seed, locked doors live only on shop-role
        buildings."""
        for seed in range(100):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            counts = _doors_by_kind(site)
            shop_ids = {
                b.id for b in site.buildings
                if "shop" in b.ground.rooms[0].tags
            }
            for bid, c in counts.items():
                if c["door_locked"] > 0:
                    assert bid in shop_ids, (
                        f"seed {seed}: locked door on non-shop "
                        f"building {bid}"
                    )

    def test_at_most_one_locked_door_per_shop(self):
        for seed in range(100):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            counts = _doors_by_kind(site)
            for bid, c in counts.items():
                assert c["door_locked"] <= 1, (
                    f"seed {seed}: {c['door_locked']} locked "
                    f"doors on building {bid}"
                )
