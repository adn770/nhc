"""Tests for nhc.tables.registry — TableRegistry with lifetime enforcement."""

import random
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tables" / "good"


class TestTableRegistry:

    def test_load_lang_caches(self):
        from nhc.tables.registry import TableRegistry

        TableRegistry._cache.clear()
        a = TableRegistry.get_or_load("en", root=FIXTURES)
        b = TableRegistry.get_or_load("en", root=FIXTURES)
        assert a is b
        TableRegistry._cache.clear()

    def test_load_different_langs_isolated(self):
        from nhc.tables.registry import TableRegistry

        TableRegistry._cache.clear()
        en = TableRegistry.get_or_load("en", root=FIXTURES)
        ca = TableRegistry.get_or_load("ca", root=FIXTURES)
        rng = random.Random(42)
        en_result = en.roll("example.greeting", rng=rng, context={})
        rng = random.Random(42)
        ca_result = ca.roll("example.greeting", rng=rng, context={})
        # Same entry_id (shared structure) but different text
        assert en_result.entry_id == ca_result.entry_id
        assert en_result.text != ca_result.text
        TableRegistry._cache.clear()

    def test_roll_unknown_table_raises_unknown_table_error(self):
        from nhc.tables.registry import TableRegistry, UnknownTableError

        TableRegistry._cache.clear()
        reg = TableRegistry.get_or_load("en", root=FIXTURES)
        with pytest.raises(UnknownTableError, match="nonexistent"):
            reg.roll("nonexistent", rng=random.Random(1), context={})
        TableRegistry._cache.clear()

    def test_roll_gen_time_without_seed_raises(self):
        from nhc.tables.registry import GenTimeRNGRequiredError, TableRegistry

        TableRegistry._cache.clear()
        reg = TableRegistry.get_or_load("en", root=FIXTURES)
        # Passing None as rng for a gen_time table should fail
        with pytest.raises(GenTimeRNGRequiredError):
            reg.roll("example.greeting", rng=None, context={})
        TableRegistry._cache.clear()

    def test_roll_ephemeral_accepts_none_rng(self):
        from nhc.tables.registry import TableRegistry

        # Need an ephemeral fixture — use divergent which is ephemeral
        divergent_root = (
            Path(__file__).resolve().parents[2]
            / "fixtures" / "tables" / "divergent"
        )
        TableRegistry._cache.clear()
        reg = TableRegistry.get_or_load("en", root=divergent_root)
        result = reg.roll("names.tavern", rng=None, context={})
        assert result.text in ("The Rusty Sword", "The Golden Goblet")
        TableRegistry._cache.clear()

    def test_render_by_entry_id_is_deterministic_across_langs(self):
        from nhc.tables.registry import TableRegistry

        TableRegistry._cache.clear()
        en = TableRegistry.get_or_load("en", root=FIXTURES)
        ca = TableRegistry.get_or_load("ca", root=FIXTURES)
        en_result = en.render("example.greeting", entry_id="hello", context={})
        ca_result = ca.render("example.greeting", entry_id="hello", context={})
        assert en_result.entry_id == ca_result.entry_id == "hello"
        assert en_result.text != ca_result.text
        assert en_result.text == "Hello, adventurer!"
        assert ca_result.text == "Hola, aventurer!"
        TableRegistry._cache.clear()

    def test_render_unknown_entry_id_raises(self):
        from nhc.tables.registry import TableRegistry

        TableRegistry._cache.clear()
        reg = TableRegistry.get_or_load("en", root=FIXTURES)
        with pytest.raises(KeyError, match="nonexistent"):
            reg.render(
                "example.greeting", entry_id="nonexistent", context={},
            )
        TableRegistry._cache.clear()

    def test_module_level_roll_convenience_wrapper(self):
        from nhc.tables.registry import TableRegistry

        from nhc.tables import roll

        TableRegistry._cache.clear()
        result = roll(
            "example.greeting",
            lang="en",
            rng=random.Random(42),
            context={},
            root=FIXTURES,
        )
        assert result.entry_id in ("hello", "welcome")
        assert result.text in (
            "Hello, adventurer!", "Welcome to the dungeon.",
        )
        TableRegistry._cache.clear()
