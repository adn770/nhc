"""TableRegistry — central entry point for the tables subsystem.

Lazy per-language loading, cached. Exposes roll() for normal
weighted rolls and render() for deterministic re-rendering of
a known entry_id.
"""

from __future__ import annotations

import random
from pathlib import Path

from nhc.tables.formatter import StrFormatFormatter
from nhc.tables.loader import load_lang
from nhc.tables.roller import roll as _roll_entry
from nhc.tables.types import Table, TableEffect, TableResult


class UnknownTableError(Exception):
    """Raised when a table ID is not found in the registry."""


class GenTimeRNGRequiredError(Exception):
    """Raised when a gen_time table is rolled without a seeded RNG."""


_formatter = StrFormatFormatter()


class TableRegistry:
    """Per-language table registry with lazy loading and caching."""

    _cache: dict[str, TableRegistry] = {}

    def __init__(self, tables: dict[str, Table]):
        self._tables = tables

    @classmethod
    def get_or_load(
        cls,
        lang: str,
        root: Path | None = None,
    ) -> TableRegistry:
        """Return cached registry for *lang*, loading if needed."""
        cache_key = f"{lang}:{root or 'default'}"
        if cache_key not in cls._cache:
            tables = load_lang(lang, root=root)
            cls._cache[cache_key] = cls(tables)
        return cls._cache[cache_key]

    def roll(
        self,
        table_id: str,
        *,
        rng: random.Random | None,
        context: dict,
    ) -> TableResult:
        """Roll a random entry from *table_id*."""
        table = self._get_table(table_id)

        if table.lifetime == "gen_time":
            if not isinstance(rng, random.Random):
                raise GenTimeRNGRequiredError(
                    f"Table '{table_id}' has lifetime 'gen_time' "
                    f"and requires a seeded random.Random instance"
                )

        if rng is None:
            rng = random.Random()

        entry = _roll_entry(table, rng, context)
        text = self._format_entry(entry, table_id, rng, context)
        effect = self._parse_effect(entry.effect)
        return TableResult(text=text, entry_id=entry.id, effect=effect)

    def render(
        self,
        table_id: str,
        *,
        entry_id: str,
        context: dict,
    ) -> TableResult:
        """Render a known entry by ID (no RNG, deterministic)."""
        table = self._get_table(table_id)
        entry_map = {e.id: e for e in table.entries}
        if entry_id not in entry_map:
            raise KeyError(
                f"Entry '{entry_id}' not found in table '{table_id}'"
            )
        entry = entry_map[entry_id]
        text = _formatter.format(entry, context=context, roll_subtable=None)
        effect = self._parse_effect(entry.effect)
        return TableResult(text=text, entry_id=entry.id, effect=effect)

    def _get_table(self, table_id: str) -> Table:
        if table_id not in self._tables:
            raise UnknownTableError(
                f"Unknown table '{table_id}' "
                f"({len(self._tables)} tables loaded)"
            )
        return self._tables[table_id]

    def _format_entry(
        self,
        entry,
        table_id: str,
        rng: random.Random,
        context: dict,
    ) -> str:
        def roll_subtable(sub_id, ctx):
            sub_table = self._get_table(sub_id)
            sub_entry = _roll_entry(sub_table, rng, ctx)
            return sub_entry, sub_entry.id

        return _formatter.format(
            entry, context=context, roll_subtable=roll_subtable,
        )

    @staticmethod
    def _parse_effect(raw: dict | None) -> TableEffect | None:
        if raw is None:
            return None
        return TableEffect(kind=raw["kind"], payload=raw.get("payload", {}))
