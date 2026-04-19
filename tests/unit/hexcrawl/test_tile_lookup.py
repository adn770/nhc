"""Biome-keyed tile slot lookup (milestone 2).

Replaces the base+extended tuple structure in tiles.py with an
explicit per-biome dict per feature (see
design/biome_features.md §4). Each (feature, biome) pair now
declares its tile slot list directly.
"""

from __future__ import annotations

from nhc.hexcrawl.tiles import (
    SLOT_NAME,
    assign_tile_slot,
    feature_variants,
)


# ---------------------------------------------------------------------------
# Single-slot biome mappings
# ---------------------------------------------------------------------------


class TestCitySlots:
    def test_city_greenlands_returns_slot_12(self) -> None:
        assert feature_variants("city", "greenlands") == [12]

    def test_city_hills_returns_slot_12(self) -> None:
        assert feature_variants("city", "hills") == [12]


class TestVillageSlots:
    def test_village_mountain_returns_slot_75_mountain_village(
        self,
    ) -> None:
        assert feature_variants("village", "mountain") == [75]
        assert SLOT_NAME[75] == "mountain-Village"


class TestCommunitySlots:
    def test_community_forest_returns_slot_53_hamlet(self) -> None:
        assert feature_variants("community", "forest") == [53]
        assert SLOT_NAME[53] == "hamlet"

    def test_community_mountain_returns_slot_74_lodge(self) -> None:
        assert feature_variants("community", "mountain") == [74]
        assert SLOT_NAME[74] == "mountain-Lodge"


class TestFarmSlots:
    def test_farm_greenlands_returns_slot_26(self) -> None:
        assert feature_variants("farm", "greenlands") == [26]


class TestMansionSlots:
    def test_mansion_greenlands_hills_marsh_returns_slot_52(
        self,
    ) -> None:
        assert feature_variants("mansion", "greenlands") == [52]
        assert feature_variants("mansion", "hills") == [52]
        assert feature_variants("mansion", "marsh") == [52]


class TestCottageSlots:
    def test_cottage_forest_returns_slot_52(self) -> None:
        assert feature_variants("cottage", "forest") == [52]


# ---------------------------------------------------------------------------
# Temple slots, including generated-tile mysterious variants
# ---------------------------------------------------------------------------


class TestTempleSlots:
    def test_temple_mountain_returns_slot_80(self) -> None:
        assert feature_variants("temple", "mountain") == [80]
        assert SLOT_NAME[80] == "mountain-Temple"

    def test_temple_forest_returns_slot_58(self) -> None:
        assert feature_variants("temple", "forest") == [58]
        assert SLOT_NAME[58] == "forest-Temple"

    def test_temple_sandlands_returns_slot_80(self) -> None:
        """Mysterious variant uses the mountain-Temple foundation
        generated onto a sandlands background."""
        assert feature_variants("temple", "sandlands") == [80]

    def test_temple_icelands_returns_slot_58(self) -> None:
        """Mysterious variant uses the forest-Temple foundation
        generated onto an icelands background."""
        assert feature_variants("temple", "icelands") == [58]


# ---------------------------------------------------------------------------
# Ruin: multi-slot on forest, single slot elsewhere
# ---------------------------------------------------------------------------


class TestRuinSlots:
    def test_ruin_forest_returns_either_18_or_55(self) -> None:
        variants = feature_variants("ruin", "forest")
        assert set(variants) == {18, 55}

    def test_ruin_deadlands_returns_slot_18(self) -> None:
        assert feature_variants("ruin", "deadlands") == [18]

    def test_ruin_marsh_returns_slot_18(self) -> None:
        assert feature_variants("ruin", "marsh") == [18]

    def test_ruin_sandlands_returns_slot_18(self) -> None:
        assert feature_variants("ruin", "sandlands") == [18]

    def test_ruin_icelands_returns_slot_18(self) -> None:
        assert feature_variants("ruin", "icelands") == [18]


# ---------------------------------------------------------------------------
# Tower and keep: existing behaviour preserved
# ---------------------------------------------------------------------------


class TestTowerSlotOnVariousBiomes:
    def test_tower_greenlands_returns_slot_13(self) -> None:
        assert feature_variants("tower", "greenlands") == [13]

    def test_tower_mountain_returns_slot_76(self) -> None:
        assert feature_variants("tower", "mountain") == [76]

    def test_tower_forest_returns_slot_54(self) -> None:
        """Forest watchtower replaces the generic tower slot."""
        assert feature_variants("tower", "forest") == [54]

    def test_tower_icelands_falls_back_to_slot_13(self) -> None:
        """Biomes without a custom tower tile use the greenlands
        slot."""
        assert feature_variants("tower", "icelands") == [13]


class TestKeepSlotUnchanged:
    def test_keep_greenlands_returns_slot_22(self) -> None:
        assert feature_variants("keep", "greenlands") == [22]

    def test_keep_hills_returns_slot_22(self) -> None:
        assert feature_variants("keep", "hills") == [22]

    def test_keep_drylands_returns_slot_22(self) -> None:
        assert feature_variants("keep", "drylands") == [22]


# ---------------------------------------------------------------------------
# Determinism & fallback
# ---------------------------------------------------------------------------


class TestTileSelection:
    def test_tile_selection_is_deterministic(self) -> None:
        """Multi-slot features must return the same slot for the
        same (q, r) across calls."""
        for q in range(10):
            for r in range(10):
                a = assign_tile_slot(
                    "forest", "ruin", q, r, has_waterway=False,
                )
                b = assign_tile_slot(
                    "forest", "ruin", q, r, has_waterway=False,
                )
                assert a == b
                assert a in (18, 55)

    def test_unknown_feature_biome_falls_back_cleanly(self) -> None:
        """A feature/biome combo without an explicit entry falls
        back to a greenlands / hills slot without raising."""
        variants = feature_variants("city", "deadlands")
        assert variants is not None
        assert variants
        for slot in variants:
            assert slot in SLOT_NAME
