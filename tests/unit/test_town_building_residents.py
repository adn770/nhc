"""Town life: residents sprinkled inside buildings.

Beyond the service NPC on a shop/inn/temple ground floor, buildings
get a few resident villagers in their interiors (upper floors of
service buildings; any floor of homes), so stepping inside finds the
place lived-in rather than empty. Residents land on walkable,
feature-free floor tiles and never crowd the service ground floor.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Terrain
from nhc.sites.town import assemble_town

SERVICE_IDS = {"merchant", "innkeeper", "priest"}


def _building_floor_creatures(site):
    """(building, floor_index, placement) for every creature placed
    on a building floor."""
    out = []
    for b in site.buildings:
        for fi, floor in enumerate(b.floors):
            for e in floor.entities:
                if e.entity_type == "creature":
                    out.append((b, fi, e))
    return out


def test_buildings_get_resident_villagers() -> None:
    site = assemble_town("t1", random.Random(4), size_class="city")
    residents = [
        e for (_b, _fi, e) in _building_floor_creatures(site)
        if e.entity_id == "villager"
    ]
    assert residents, "no resident villagers placed inside buildings"


def test_residents_on_walkable_feature_free_tiles() -> None:
    site = assemble_town("t1", random.Random(4), size_class="city")
    for b, fi, e in _building_floor_creatures(site):
        if e.entity_id != "villager":
            continue
        tile = b.floors[fi].tile_at(e.x, e.y)
        assert tile is not None
        assert tile.terrain is Terrain.FLOOR
        assert tile.feature is None  # never on a door or stairs


def test_service_ground_floor_not_crowded_by_residents() -> None:
    """A floor holding a service NPC (the shop/inn/temple counter)
    gets no resident villagers added on top of it."""
    site = assemble_town("t1", random.Random(7), size_class="city")
    for b in site.buildings:
        for floor in b.floors:
            ids = [
                e.entity_id for e in floor.entities
                if e.entity_type == "creature"
            ]
            if SERVICE_IDS & set(ids):
                assert "villager" not in ids


def test_no_two_residents_share_a_tile() -> None:
    site = assemble_town("t1", random.Random(11), size_class="city")
    for b in site.buildings:
        for floor in b.floors:
            spots = [
                (e.x, e.y) for e in floor.entities
                if e.entity_type == "creature"
            ]
            assert len(spots) == len(set(spots))


def test_resident_placement_is_deterministic() -> None:
    a = assemble_town("t1", random.Random(3), size_class="town")
    b = assemble_town("t1", random.Random(3), size_class="town")
    na = len([
        e for (_x, _fi, e) in _building_floor_creatures(a)
        if e.entity_id == "villager"
    ])
    nb = len([
        e for (_x, _fi, e) in _building_floor_creatures(b)
        if e.entity_id == "villager"
    ])
    assert na == nb
