"""Town life: mundane clutter scattered inside buildings.

Beyond residents, buildings get a few scattered floor items, food and
lootable containers so stepping inside finds a lived-in home or a
shop's storeroom rather than bare floor. The mix is role-aware — homes
lean to food and household objects, shops and inns to storage crates
and barrels — and reserved buildings (stable / training) stay empty.

Clutter lands on walkable, feature-free floor tiles and never shares a
tile with a resident, a service NPC or another piece of clutter.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Terrain
from nhc.sites.town import (
    _CONTAINER_IDS,
    _clutter_pool_for_role,
    assemble_town,
)


def _building_floor_clutter(site):
    """(building, floor_index, placement) for every item / feature
    placed on a building floor."""
    out = []
    for b in site.buildings:
        for fi, floor in enumerate(b.floors):
            for e in floor.entities:
                if e.entity_type in ("item", "feature"):
                    out.append((b, fi, e))
    return out


def test_buildings_get_scattered_clutter() -> None:
    site = assemble_town("t1", random.Random(4), size_class="city")
    clutter = _building_floor_clutter(site)
    assert clutter, "no clutter scattered inside buildings"


def test_clutter_on_walkable_feature_free_tiles() -> None:
    site = assemble_town("t1", random.Random(4), size_class="city")
    for b, fi, e in _building_floor_clutter(site):
        tile = b.floors[fi].tile_at(e.x, e.y)
        assert tile is not None
        assert tile.terrain is Terrain.FLOOR
        assert tile.feature is None  # never on a door or stairs


def test_no_two_entities_share_a_building_tile() -> None:
    """Clutter never lands on a resident, a service NPC or another
    piece of clutter."""
    site = assemble_town("t1", random.Random(7), size_class="city")
    for b in site.buildings:
        for floor in b.floors:
            spots = [(e.x, e.y) for e in floor.entities]
            assert len(spots) == len(set(spots))


def test_containers_are_lootable_kinds() -> None:
    """Every placed feature is one of the known lootable containers
    (its factory carries the LootTable, so it spawns with loot)."""
    site = assemble_town("t1", random.Random(4), size_class="city")
    for _b, _fi, e in _building_floor_clutter(site):
        if e.entity_type == "feature":
            assert e.entity_id in _CONTAINER_IDS


def test_clutter_is_deterministic() -> None:
    a = assemble_town("t1", random.Random(3), size_class="town")
    b = assemble_town("t1", random.Random(3), size_class="town")
    spots_a = sorted(
        (bd.id, fi, e.entity_id, e.x, e.y)
        for (bd, fi, e) in _building_floor_clutter(a)
    )
    spots_b = sorted(
        (bd.id, fi, e.entity_id, e.x, e.y)
        for (bd, fi, e) in _building_floor_clutter(b)
    )
    assert spots_a == spots_b


# ── Role-aware pool selection (pure helper) ──

def test_reserved_roles_get_no_clutter() -> None:
    assert _clutter_pool_for_role("stable") == []
    assert _clutter_pool_for_role("training") == []


def test_unknown_role_falls_back_to_residential() -> None:
    assert (
        _clutter_pool_for_role("residential")
        == _clutter_pool_for_role("some-future-role")
    )


def test_residential_pool_mixes_food_and_objects() -> None:
    ids = {eid for (_et, eid, _w) in _clutter_pool_for_role("residential")}
    assert {"bread", "apple"} & ids  # food
    assert {"candles", "bucket", "sack"} & ids  # household objects


def test_shop_pool_emphasises_containers() -> None:
    pool = _clutter_pool_for_role("shop")
    container_weight = sum(
        w for (et, _eid, w) in pool if et == "feature"
    )
    other_weight = sum(w for (et, _eid, w) in pool if et != "feature")
    assert container_weight > other_weight
