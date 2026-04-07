"""Tests for potion/scroll/ring/wand identification system."""
import pytest
from nhc.i18n import init as i18n_init
from nhc.rules.identification import (
    ItemKnowledge, POTION_IDS, SCROLL_IDS, RING_IDS, WAND_IDS,
    ALL_IDS, POTION_APPEARANCES, SCROLL_APPEARANCES,
    RING_APPEARANCES, WAND_APPEARANCES,
)
from nhc.utils.rng import set_seed
import random


class TestItemKnowledge:
    def test_all_items_have_appearance(self):
        set_seed(42)
        k = ItemKnowledge(rng=random.Random(42))
        for item_id in ALL_IDS:
            assert k.is_identifiable(item_id), f"{item_id} not identifiable"

    def test_nothing_identified_initially(self):
        k = ItemKnowledge(rng=random.Random(42))
        for item_id in ALL_IDS:
            assert not k.is_identified(item_id)

    def test_identify_marks_item(self):
        k = ItemKnowledge(rng=random.Random(42))
        k.identify("potion_healing")
        assert k.is_identified("potion_healing")
        assert not k.is_identified("potion_frost")

    def test_display_name_unidentified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("potion_healing")
        # Should be a color-based name, not "Healing Potion"
        assert "Healing Potion" not in name
        assert "potion" in name.lower()

    def test_display_name_identified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        k.identify("potion_healing")
        assert k.display_name("potion_healing") == "Healing Potion"

    def test_display_short_unidentified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        short = k.display_short("potion_healing")
        assert "Healing Potion" not in short

    def test_display_short_identified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        k.identify("potion_healing")
        short = k.display_short("potion_healing")
        assert "crimson" in short.lower()  # "a crimson potion"


class TestAppearanceShuffling:
    def test_different_seeds_different_appearances(self):
        k1 = ItemKnowledge(rng=random.Random(1))
        k2 = ItemKnowledge(rng=random.Random(2))
        # Very unlikely all potions get the same appearance
        appearances_1 = [k1.appearance(pid) for pid in POTION_IDS]
        appearances_2 = [k2.appearance(pid) for pid in POTION_IDS]
        assert appearances_1 != appearances_2

    def test_same_seed_same_appearances(self):
        k1 = ItemKnowledge(rng=random.Random(42))
        k2 = ItemKnowledge(rng=random.Random(42))
        for item_id in ALL_IDS:
            assert k1.appearance(item_id) == k2.appearance(item_id)


class TestRingAppearances:
    def test_ring_prefix(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("ring_mending")
        assert "ring" in name.lower()

    def test_ring_identified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        k.identify("ring_mending")
        assert k.display_name("ring_mending") == "Ring of Mending"


class TestWandAppearances:
    def test_wand_prefix(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("wand_firebolt")
        assert "wand" in name.lower()

    def test_wand_identified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        k.identify("wand_firebolt")
        assert k.display_name("wand_firebolt") == "Wand of Firebolt"


class TestScrollAppearances:
    def test_scroll_cryptic_label(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("scroll_fireball")
        assert "scroll" in name.lower()
        assert "labeled" in name.lower()

    def test_scroll_identified(self):
        i18n_init("en")
        k = ItemKnowledge(rng=random.Random(42))
        k.identify("scroll_fireball")
        assert "Fireball" in k.display_name("scroll_fireball")


class TestCatalanAppearances:
    def test_potion_catalan(self):
        i18n_init("ca")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("potion_healing")
        assert "poció" in name.lower()

    def test_ring_catalan(self):
        i18n_init("ca")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("ring_mending")
        assert "anell" in name.lower()

    def test_wand_catalan(self):
        i18n_init("ca")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("wand_firebolt")
        assert "vareta" in name.lower()

    def test_scroll_catalan(self):
        i18n_init("ca")
        k = ItemKnowledge(rng=random.Random(42))
        name = k.display_name("scroll_fireball")
        assert "pergamí" in name.lower()
