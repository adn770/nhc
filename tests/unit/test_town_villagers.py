"""Tests for villager placement on town surfaces."""

from __future__ import annotations

import random

from nhc.dungeon.sites.town import (
    TOWN_VILLAGER_COUNT, assemble_town,
)


class TestVillagerSpawnCount:
    def test_hamlet_gets_hamlet_count(self):
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="hamlet",
            )
            villagers = [
                e for e in site.surface.entities
                if e.entity_id == "villager"
            ]
            assert len(villagers) == TOWN_VILLAGER_COUNT["hamlet"]

    def test_city_gets_city_count(self):
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="city",
            )
            villagers = [
                e for e in site.surface.entities
                if e.entity_id == "villager"
            ]
            assert len(villagers) == TOWN_VILLAGER_COUNT["city"]


class TestVillagerPlacement:
    def test_villagers_land_on_walkable_street(self):
        """Every villager placement lands on a walkable street tile
        without a stamped feature."""
        from nhc.dungeon.model import SurfaceType

        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="town",
            )
            for placement in site.surface.entities:
                if placement.entity_id != "villager":
                    continue
                tile = site.surface.tiles[placement.y][placement.x]
                assert tile.walkable, (
                    f"villager on non-walkable tile seed={seed}"
                )
                assert tile.surface_type == SurfaceType.STREET, (
                    f"villager off street seed={seed}"
                )
                assert tile.feature is None, (
                    f"villager on feature tile seed={seed}"
                )

    def test_villagers_at_unique_positions(self):
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            coords = [
                (p.x, p.y) for p in site.surface.entities
                if p.entity_id == "villager"
            ]
            assert len(coords) == len(set(coords)), (
                f"duplicate villager positions seed={seed}"
            )


class TestVillagerDoesNotDisplaceServiceNPCs:
    """Villagers live on the surface; merchants/innkeepers/priests
    live on building ground floors. The two lists must stay
    disjoint — placing villagers must not append to building
    entity lists."""

    def test_building_floors_have_no_villagers(self):
        for seed in range(10):
            site = assemble_town(
                "t1", random.Random(seed), size_class="town",
            )
            for b in site.buildings:
                for floor in b.floors:
                    for placement in floor.entities:
                        assert placement.entity_id != "villager", (
                            f"villager stamped inside building "
                            f"{b.id} seed={seed}"
                        )
