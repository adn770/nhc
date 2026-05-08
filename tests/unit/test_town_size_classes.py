"""Tests for town assembler size classes + service-building NPCs.

Four ``size_class`` presets tune the town assembler's building
count, surface size, and palisade presence: ``hamlet`` (3-4
buildings, no palisade) through ``city`` (12-16 buildings, walled).
Every size tags at least ``shop``, ``inn``, and ``temple``
buildings and places the associated NPC placements on each
building's ground floor.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites._site import Site
from nhc.sites.town import (
    SERVICE_ROLES_WITH_NPCS,
    _SIZE_CLASSES,
    assemble_town,
)


def _npc_ids(site: Site) -> list[str]:
    """IDs of every building-interior service NPC.

    Does not include surface-level townsfolk (villagers, pickpockets,
    adventurers) — those live on ``site.surface.entities`` and are
    tested separately.
    """
    out: list[str] = []
    for b in site.buildings:
        for p in b.ground.entities:
            out.append(p.entity_id)
    return out


def _surface_npc_ids(site: Site) -> list[str]:
    return [p.entity_id for p in site.surface.entities]


class TestSizeClassBuildingCounts:
    def test_hamlet_has_three_or_four_buildings(self):
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class="hamlet",
            )
            assert 3 <= len(site.buildings) <= 4

    def test_village_is_default(self):
        default = assemble_town("t1", random.Random(42))
        village = assemble_town(
            "t1", random.Random(42), size_class="village",
        )
        assert len(default.buildings) == len(village.buildings)

    def test_town_has_eight_to_ten_buildings(self):
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="town",
            )
            assert 8 <= len(site.buildings) <= 10

    def test_city_has_thirty_to_fortyeight_buildings(self):
        """City draws 40-48 candidate buildings; rejection sampling
        on the dense (12-16 cluster, 4-member-cap) packing drops
        a few when the courtyard exhausts its placement attempts.
        Observed range across 50 seeds is [30, 46]."""
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="city",
            )
            assert 30 <= len(site.buildings) <= 48

    def test_unknown_size_class_raises(self):
        with pytest.raises(ValueError):
            assemble_town(
                "t1", random.Random(1), size_class="megalopolis",
            )


class TestHamletHasNoPalisade:
    def test_hamlet_enclosure_is_none(self):
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="hamlet",
            )
            assert site.enclosure is None

    def test_larger_settlements_have_an_enclosure(self):
        """Village + town wrap a wood palisade; city upgrades to a
        stone fortification (matching the keep treatment) so the
        urban tier reads visually distinct from its smaller
        predecessors."""
        expected_kind = {
            "village": "palisade",
            "town": "palisade",
            "city": "fortification",
        }
        for size, kind in expected_kind.items():
            site = assemble_town(
                "t1", random.Random(1), size_class=size,
            )
            assert site.enclosure is not None
            assert site.enclosure.kind == kind, (
                f"{size}: enclosure kind {site.enclosure.kind!r} "
                f"(expected {kind!r})"
            )


class TestServiceRoleAssignment:
    def test_hamlet_tags_three_service_buildings(self):
        """Hamlets have 3-4 buildings; the three NPC-bearing roles
        always occupy the first three."""
        for seed in range(30):
            site = assemble_town(
                "t1", random.Random(seed), size_class="hamlet",
            )
            for role in SERVICE_ROLES_WITH_NPCS:
                tagged = [
                    b for b in site.buildings
                    if role in b.ground.rooms[0].tags
                ]
                assert len(tagged) == 1, (
                    f"seed={seed} expected one {role} building, "
                    f"found {len(tagged)}"
                )

    def test_town_tags_all_five_service_roles(self):
        """Towns have enough buildings to fill every service slot
        (shop, inn, temple, stable, training)."""
        site = assemble_town(
            "t1", random.Random(1), size_class="town",
        )
        for role in (
            "shop", "inn", "temple", "stable", "training",
        ):
            tagged = [
                b for b in site.buildings
                if role in b.ground.rooms[0].tags
            ]
            assert len(tagged) == 1


class TestServiceNpcPlacement:
    def test_hamlet_places_merchant_priest_innkeeper_adventurer(self):
        site = assemble_town(
            "t1", random.Random(1), size_class="hamlet",
        )
        ids = _npc_ids(site)
        assert ids.count("merchant") == 1
        assert ids.count("priest") == 1
        assert ids.count("innkeeper") == 1
        # The adventurer now loiters on the street near the inn
        # instead of inside it, so they show up in surface.entities.
        assert _surface_npc_ids(site).count("adventurer") == 1

    def test_merchant_lives_in_shop_building(self):
        site = assemble_town(
            "t1", random.Random(1), size_class="hamlet",
        )
        shop = next(
            b for b in site.buildings
            if "shop" in b.ground.rooms[0].tags
        )
        merchants = [
            p for p in shop.ground.entities
            if p.entity_id == "merchant"
        ]
        assert len(merchants) == 1
        p = merchants[0]
        rect = shop.base_rect
        assert rect.x <= p.x < rect.x + rect.width
        assert rect.y <= p.y < rect.y + rect.height
        assert p.extra.get("shop_stock"), (
            "merchant needs a non-empty stock"
        )

    def test_priest_lives_in_temple_building(self):
        site = assemble_town(
            "t1", random.Random(1), size_class="hamlet",
        )
        temple = next(
            b for b in site.buildings
            if "temple" in b.ground.rooms[0].tags
        )
        priests = [
            p for p in temple.ground.entities
            if p.entity_id == "priest"
        ]
        assert len(priests) == 1
        assert priests[0].extra.get("temple_services"), (
            "priest needs temple_services set"
        )

    def test_inn_has_innkeeper_not_adventurer(self):
        site = assemble_town(
            "t1", random.Random(1), size_class="hamlet",
        )
        inn = next(
            b for b in site.buildings
            if "inn" in b.ground.rooms[0].tags
        )
        ids = [p.entity_id for p in inn.ground.entities]
        assert "innkeeper" in ids
        assert "adventurer" not in ids

    def test_adventurer_on_surface_with_inn_anchor(self):
        """The unhired hireling lives on the street and carries the
        inn door as its errand anchor so the player can find them."""
        site = assemble_town(
            "t1", random.Random(1), size_class="hamlet",
        )
        inn = next(
            b for b in site.buildings
            if "inn" in b.ground.rooms[0].tags
        )
        # Resolve the inn's surface-side door.
        inn_door = next(
            sxy for sxy, (bid, _, _) in site.building_doors.items()
            if bid == inn.id
        )
        adv = next(
            p for p in site.surface.entities
            if p.entity_id == "adventurer"
        )
        assert adv.extra.get("adventurer_level", 0) >= 1
        assert adv.extra.get("errand_anchor") == inn_door
        assert 0 < adv.extra.get("errand_weight", 0) <= 1.0

    def test_stable_and_training_buildings_empty(self):
        site = assemble_town(
            "t1", random.Random(1), size_class="town",
        )
        for role in ("stable", "training"):
            reserved = next(
                (
                    b for b in site.buildings
                    if role in b.ground.rooms[0].tags
                ),
                None,
            )
            if reserved is None:
                continue
            assert reserved.ground.entities == []
