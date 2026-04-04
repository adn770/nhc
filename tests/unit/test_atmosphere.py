"""Tests for level atmosphere messages."""

from __future__ import annotations

import pytest

from nhc.i18n import init as i18n_init, t


THEMES = ["dungeon", "crypt", "cave", "castle", "abyss"]


@pytest.fixture(autouse=True)
def _init_i18n():
    i18n_init("en")


class TestAtmosphereEntries:
    """Every theme must have exactly 12 atmosphere sentences."""

    @pytest.mark.parametrize("theme", THEMES)
    def test_theme_has_12_entries(self, theme):
        for i in range(1, 13):
            key = f"atmosphere.{theme}.{i}"
            result = t(key)
            assert result != key, (
                f"Missing i18n key: {key}"
            )

    @pytest.mark.parametrize("theme", THEMES)
    def test_entries_are_non_empty_strings(self, theme):
        for i in range(1, 13):
            result = t(f"atmosphere.{theme}.{i}")
            assert len(result) > 10, (
                f"atmosphere.{theme}.{i} is too short: {result!r}"
            )

    @pytest.mark.parametrize("theme", THEMES)
    def test_entries_are_unique_per_theme(self, theme):
        entries = [t(f"atmosphere.{theme}.{i}") for i in range(1, 13)]
        assert len(set(entries)) == 12, (
            f"Duplicate atmosphere entries in theme '{theme}'"
        )


class TestAtmosphereLocales:
    """All three locales must have atmosphere entries."""

    @pytest.mark.parametrize("lang", ["en", "ca", "es"])
    def test_locale_has_all_themes(self, lang):
        i18n_init(lang)
        for theme in THEMES:
            for i in range(1, 13):
                key = f"atmosphere.{theme}.{i}"
                result = t(key)
                assert result != key, (
                    f"Missing {lang} key: {key}"
                )


class TestAtmosphereRoll:
    """The 1d12 roll selects a valid entry."""

    def test_roll_range_covers_all_entries(self):
        from nhc.utils.rng import roll_dice, set_seed
        results = set()
        for seed in range(200):
            set_seed(seed)
            roll = roll_dice("1d12")
            results.add(roll)
        assert results == set(range(1, 13)), (
            f"1d12 should produce 1-12, got {sorted(results)}"
        )
