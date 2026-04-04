"""Tests for the internationalization system."""

import pytest

from nhc.i18n import init, t, current_lang
from nhc.i18n.manager import TranslationManager


class TestTranslationManager:
    def test_load_english(self):
        mgr = TranslationManager()
        mgr.load("en")
        assert mgr.lang == "en"

    def test_resolve_simple_key(self):
        mgr = TranslationManager()
        mgr.load("en")
        result = mgr.get("game.game_saved")
        assert result == "Game saved."

    def test_resolve_with_interpolation(self):
        mgr = TranslationManager()
        mgr.load("en")
        result = mgr.get("game.welcome", name="Test Dungeon")
        assert result == "Welcome to Test Dungeon."

    def test_missing_key_returns_key(self):
        mgr = TranslationManager()
        mgr.load("en")
        result = mgr.get("nonexistent.key")
        assert result == "nonexistent.key"

    def test_nested_key(self):
        mgr = TranslationManager()
        mgr.load("en")
        result = mgr.get("creature.goblin.name")
        assert result == "Goblin"

    def test_fallback_to_english(self):
        """Non-English locale falls back to English for missing keys."""
        mgr = TranslationManager()
        mgr.load("ca")
        # This key should exist in Catalan
        result = mgr.get("game.game_saved")
        assert result == "Partida desada."

    def test_unknown_locale_falls_back(self):
        """Unknown locale code falls back entirely to English."""
        mgr = TranslationManager()
        mgr.load("xx")  # Non-existent locale
        result = mgr.get("game.game_saved")
        assert result == "Game saved."


class TestGlobalInterface:
    def test_init_and_translate(self):
        init("en")
        assert current_lang() == "en"
        assert t("game.died") == "You have died!"

    def test_switch_to_catalan(self):
        init("ca")
        assert current_lang() == "ca"
        assert t("game.died") == "Has mort!"
        assert t("creature.goblin.name") == "goblin"
        assert t("creature.skeleton.name") == "esquelet"

    def test_switch_to_spanish(self):
        init("es")
        assert current_lang() == "es"
        assert t("game.died") == "¡Has muerto!"
        assert t("creature.skeleton.name") == "Esqueleto"

    def test_interpolation_catalan(self):
        init("ca")
        result = t("combat.hit", attacker="Tu", target="Goblin",
                   damage=5)
        assert "Tu" in result
        assert "Goblin" in result
        assert "5" in result

    def test_interpolation_spanish(self):
        init("es")
        result = t("item.picked_up", item="Espada")
        assert "Espada" in result

    def test_player_variants_catalan(self):
        """Player-perspective variants produce 2nd person Catalan."""
        init("ca")
        # Player attacks
        result = t("combat.you_hit", target="goblin", damage=5)
        assert "Colpeges" in result
        assert "goblin" in result
        # Player is attacked
        result = t("combat.hit_you", attacker="Esquelet", damage=3)
        assert "et colpeja" in result
        assert "Esquelet" in result
        # Player opens door
        result = t("explore.you_open_door")
        assert "Obres" in result
        # Trap variants
        result = t("trap.you_triggered", trap="Trampa", damage=4)
        assert "Actives" in result

    def test_player_variants_english(self):
        """Player-perspective variants produce natural English."""
        init("en")
        result = t("combat.you_hit", target="Goblin", damage=5)
        assert "You hit Goblin" in result
        result = t("combat.hit_you", attacker="Skeleton", damage=3)
        assert "Skeleton hits you" in result
        result = t("combat.you_slain", target="Goblin")
        assert "You slay Goblin" in result

    def test_corpse_translation(self):
        """Corpse names are translated."""
        init("ca")
        result = t("combat.corpse", name="Goblin")
        assert result == "cadàver de Goblin"
        init("en")
        result = t("combat.corpse", name="Goblin")
        assert result == "Goblin corpse"

    def test_armor_class_label_translated(self):
        """AC label should be CA in Catalan and Spanish."""
        init("en")
        assert t("ui.ac") == "AC"
        init("ca")
        assert t("ui.ac") == "CA"
        init("es")
        assert t("ui.ac") == "CA"

    def test_all_locales_have_combat_keys(self):
        """All locales must have the core combat message keys."""
        keys = [
            "combat.hit", "combat.miss", "combat.slain",
            "combat.you_hit", "combat.you_miss", "combat.you_slain",
            "combat.hit_you", "combat.miss_you", "combat.slain_you",
            "combat.corpse",
            "explore.open_door", "explore.you_open_door",
            "explore.nothing_special",
            "game.welcome", "game.died",
            "item.picked_up", "item.equipped",
        ]
        for lang in ("en", "ca", "es"):
            init(lang)
            for key in keys:
                result = t(key)
                assert result != key, (
                    f"Missing key '{key}' in locale '{lang}'"
                )

    def test_all_creature_descriptions(self):
        """All locales have creature name/short/long."""
        creatures = ["goblin", "skeleton", "giant_rat", "orc", "zombie"]
        for lang in ("en", "ca", "es"):
            init(lang)
            for cid in creatures:
                for field in ("name", "short", "long"):
                    key = f"creature.{cid}.{field}"
                    result = t(key)
                    assert result != key, (
                        f"Missing '{key}' in locale '{lang}'"
                    )

    def test_all_item_descriptions(self):
        """All locales have item name/short/long."""
        items = [
            "sword", "dagger", "short_sword",
            "healing_potion", "gold", "shield", "scroll_lightning",
        ]
        for lang in ("en", "ca", "es"):
            init(lang)
            for iid in items:
                for field in ("name", "short", "long"):
                    key = f"items.{iid}.{field}"
                    result = t(key)
                    assert result != key, (
                        f"Missing '{key}' in locale '{lang}'"
                    )


class TestThreadIsolation:
    def test_concurrent_languages_dont_interfere(self):
        """Each thread gets its own language — no cross-talk."""
        import threading

        init("en")
        results = {}

        def _use_catalan():
            init("ca")
            results["ca_lang"] = current_lang()
            results["ca_died"] = t("game.died")

        thread = threading.Thread(target=_use_catalan)
        thread.start()
        thread.join()

        # Main thread should still be English
        assert current_lang() == "en"
        assert t("game.died") == "You have died!"
        # The other thread used Catalan
        assert results["ca_lang"] == "ca"
        assert results["ca_died"] == "Has mort!"


# Reset to English after all tests in this module
@pytest.fixture(autouse=True, scope="module")
def _reset_lang():
    yield
    init("en")
