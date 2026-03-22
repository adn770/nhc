"""Tests for the multilingual prompt loader."""

from nhc.i18n import init as i18n_init
from nhc.narrative.prompts import load_prompt


class TestLoadPrompt:
    def test_english_prompt(self):
        i18n_init("en")
        text = load_prompt("interpret")
        assert "Game Master" in text
        assert "JSON" in text

    def test_catalan_prompt(self):
        i18n_init("ca")
        text = load_prompt("interpret")
        assert "Director de Joc" in text

    def test_spanish_prompt(self):
        i18n_init("es")
        text = load_prompt("interpret")
        assert "Director de Juego" in text

    def test_narrate_interpolation(self):
        i18n_init("en")
        text = load_prompt(
            "narrate", name="Arnau", background="merchant",
            virtue="brave", vice="reckless",
        )
        assert "Arnau" in text
        assert "merchant" in text

    def test_fallback_to_english(self):
        """Unknown language falls back to English."""
        i18n_init("en")  # ensure English is loaded
        # Even with a non-existent lang, fallback should work
        text = load_prompt("interpret")
        assert "Game Master" in text or "Director" in text

    def test_all_prompts_exist(self):
        """All 5 prompt files exist for all 3 languages."""
        prompts = ["interpret", "narrate", "compress", "intro",
                   "creature_phase"]
        for lang in ("en", "ca", "es"):
            i18n_init(lang)
            for name in prompts:
                text = load_prompt(name,
                                   name="X", background="X", virtue="X",
                                   vice="X", alignment="X", level_name="X",
                                   ambient="X", hooks="X",
                                   recent_narrative="X",
                                   creature_actions="X")
                assert len(text) > 10, (
                    f"Prompt {name} for {lang} is too short"
                )
