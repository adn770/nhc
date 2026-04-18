"""Tests for faction-based creature population."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level, LevelMetadata
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.populator import FACTION_POOLS


class TestFactionPools:
    def test_all_factions_defined(self):
        for faction in ("goblin", "orc", "kobold", "gnoll",
                        "bugbear", "ogre"):
            assert faction in FACTION_POOLS
            assert len(FACTION_POOLS[faction]) > 0

    def test_faction_pool_weights_positive(self):
        for faction, pool in FACTION_POOLS.items():
            for creature_id, weight in pool:
                assert weight > 0, (
                    f"{faction}: {creature_id} has weight {weight}"
                )


class TestFactionPopulation:
    def test_faction_uses_faction_pool(self):
        """Level with faction metadata uses faction creature pool."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
        )
        level = generate_level(params)
        # Clear entities from default population
        level.entities.clear()

        # Set faction and re-populate
        level.metadata.faction = "goblin"
        from nhc.dungeon.populator import populate_level
        populate_level(level, rng=random.Random(42))

        creatures = [
            e for e in level.entities if e.entity_type == "creature"
        ]
        assert len(creatures) > 0
        # Most creatures should be goblins
        goblin_count = sum(
            1 for e in creatures if e.entity_id == "goblin"
        )
        assert goblin_count >= len(creatures) * 0.3

    def test_no_faction_uses_default_pool(self):
        """Level without faction uses standard creature pool."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
        )
        level = generate_level(params)
        creatures = [
            e for e in level.entities if e.entity_type == "creature"
        ]
        assert len(creatures) > 0
        # Should have variety, not dominated by one faction
        creature_ids = {e.entity_id for e in creatures}
        assert len(creature_ids) >= 2
