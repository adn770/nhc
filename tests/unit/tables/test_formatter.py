"""Tests for nhc.tables.formatter — template resolution."""

import pytest

from nhc.tables.types import TableEntry


def _entry(text, forms=None):
    return TableEntry(id="test", text=text, forms=forms or {})


class TestStrFormatFormatter:

    def test_plain_context_substitution(self):
        from nhc.tables.formatter import StrFormatFormatter

        fmt = StrFormatFormatter()
        result = fmt.format(
            _entry("You found {q} gold coins."),
            context={"q": 5},
            roll_subtable=None,
        )
        assert result == "You found 5 gold coins."

    def test_missing_context_key_raises_missing_context_error(self):
        from nhc.tables.formatter import MissingContextError, StrFormatFormatter

        fmt = StrFormatFormatter()
        with pytest.raises(MissingContextError, match="hex_name"):
            fmt.format(
                _entry("Near {hex_name}."),
                context={},
                roll_subtable=None,
            )

    def test_subtable_marker_resolves(self):
        from nhc.tables.formatter import StrFormatFormatter

        fmt = StrFormatFormatter()

        def mock_roll(table_id, context):
            return _entry("dark"), "dark"

        result = fmt.format(
            _entry("The room is {@room.adj}."),
            context={},
            roll_subtable=mock_roll,
        )
        assert result == "The room is dark."

    def test_nested_subtable_two_levels(self):
        from nhc.tables.formatter import StrFormatFormatter

        fmt = StrFormatFormatter()
        call_count = 0

        def mock_roll(table_id, context):
            nonlocal call_count
            call_count += 1
            if table_id == "outer":
                return _entry("a {@inner} thing"), "o1"
            return _entry("shiny"), "i1"

        result = fmt.format(
            _entry("You see {@outer}."),
            context={},
            roll_subtable=mock_roll,
        )
        assert result == "You see a shiny thing."

    def test_recursion_cycle_raises_recursion_too_deep(self):
        from nhc.tables.formatter import RecursionTooDeepError, StrFormatFormatter

        fmt = StrFormatFormatter()

        def cyclic_roll(table_id, context):
            return _entry("{@" + table_id + "}"), "loop"

        with pytest.raises(RecursionTooDeepError):
            fmt.format(
                _entry("{@cycle}"),
                context={},
                roll_subtable=cyclic_roll,
            )

    def test_agreement_picks_form_by_gender(self):
        from nhc.tables.formatter import StrFormatFormatter

        fmt = StrFormatFormatter()

        adj_entry = _entry("grand", forms={"f": "gran", "m": "grand"})

        def mock_roll(table_id, context):
            return adj_entry, "adj1"

        result = fmt.format(
            _entry("Una {@adj:agree=creature} bèstia."),
            context={"creature": {"gender": "f"}},
            roll_subtable=mock_roll,
        )
        assert result == "Una gran bèstia."

    def test_agreement_missing_slot_falls_back_to_text(self):
        from nhc.tables.formatter import StrFormatFormatter

        fmt = StrFormatFormatter()

        adj_entry = _entry("grand", forms={"f": "gran", "m": "grand"})

        def mock_roll(table_id, context):
            return adj_entry, "adj1"

        # no 'creature' in context -> fall back to default text
        result = fmt.format(
            _entry("A {@adj:agree=creature} beast."),
            context={},
            roll_subtable=mock_roll,
        )
        assert result == "A grand beast."

    def test_agreement_missing_form_tag_falls_back_to_text(self):
        from nhc.tables.formatter import StrFormatFormatter

        fmt = StrFormatFormatter()

        adj_entry = _entry("grand", forms={"m": "grand"})

        def mock_roll(table_id, context):
            return adj_entry, "adj1"

        # creature has gender "f" but entry has no "f" form
        result = fmt.format(
            _entry("A {@adj:agree=creature} beast."),
            context={"creature": {"gender": "f"}},
            roll_subtable=mock_roll,
        )
        assert result == "A grand beast."
