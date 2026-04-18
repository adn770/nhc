"""Tests for nhc.tables.loader — YAML loading and schema validation."""

from pathlib import Path

import pytest

from nhc.tables.types import SchemaError, Table, TableEntry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tables"


class TestLoadTableFile:
    """Load a single YAML file into Table objects."""

    def test_load_happy_path(self):
        from nhc.tables.loader import load_table_file

        tables = load_table_file(FIXTURES / "good" / "en" / "ex.yaml")
        assert len(tables) == 1
        t = tables[0]
        assert isinstance(t, Table)
        assert t.id == "example.greeting"
        assert t.kind == "flavor"
        assert t.lifetime == "gen_time"
        assert t.shared_structure is True
        assert len(t.entries) == 2
        assert t.entries[0].id == "hello"
        assert t.entries[0].weight == 2
        assert t.entries[1].id == "welcome"
        assert t.entries[1].text == "Welcome to the dungeon."

    @pytest.mark.parametrize("fixture,field", [
        ("missing_id.yaml", "id"),
        ("missing_kind.yaml", "kind"),
        ("missing_lifetime.yaml", "lifetime"),
    ])
    def test_load_missing_required_field_raises(self, fixture, field):
        from nhc.tables.loader import load_table_file

        with pytest.raises(SchemaError, match=field):
            load_table_file(FIXTURES / "bad_schema" / fixture)

    def test_load_bad_kind_enum_raises(self):
        from nhc.tables.loader import load_table_file

        with pytest.raises(SchemaError, match="kind"):
            load_table_file(FIXTURES / "bad_schema" / "bad_kind.yaml")

    def test_load_bad_lifetime_enum_raises(self):
        from nhc.tables.loader import load_table_file

        with pytest.raises(SchemaError, match="lifetime"):
            load_table_file(FIXTURES / "bad_schema" / "bad_lifetime.yaml")

    def test_load_weight_default_is_one(self):
        from nhc.tables.loader import load_table_file

        tables = load_table_file(FIXTURES / "good" / "en" / "ex.yaml")
        welcome = tables[0].entries[1]
        assert welcome.weight == 1

    def test_load_only_if_table_level_and_entry_level_parse(self):
        from nhc.tables.loader import load_table_file

        tables = load_table_file(FIXTURES / "good" / "en" / "gated.yaml")
        t = tables[0]
        assert t.only_if == {"room_type": ["barracks", "crypt"]}
        damp = t.entries[0]
        assert damp.only_if == {"has_water": True}
        dusty = t.entries[1]
        assert dusty.only_if == {}


class TestLoadLang:
    """Load all tables for a language directory."""

    def test_load_lang_returns_dict_keyed_by_table_id(self):
        from nhc.tables.loader import load_lang

        tables = load_lang("en", root=FIXTURES / "good")
        assert "example.greeting" in tables
        assert "example.gated" in tables
        assert isinstance(tables["example.greeting"], Table)
