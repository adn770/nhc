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
from nhc.tables.types import Table, TableEffect, TableEntry, TableResult


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
        variant_index = _pick_variant_index(entry, rng)

        def pick_variant(e: TableEntry) -> str:
            if e is entry:
                return _variant_text(e, variant_index)
            # Sub-entry: pick uniformly at random. Variant is not
            # persisted — sub-entry variants are ephemeral.
            return _variant_text(e, _pick_variant_index(e, rng))

        text = self._format_entry(entry, rng, context, pick_variant)
        effect = self._parse_effect(entry.effect)
        return TableResult(
            text=text,
            entry_id=entry.id,
            effect=effect,
            variant_index=variant_index,
        )

    def render(
        self,
        table_id: str,
        *,
        entry_id: str,
        context: dict,
        variant: int | None = None,
    ) -> TableResult:
        """Render a known entry by ID (no RNG, deterministic).

        For list-valued text, pass *variant* to select a specific
        variant. When omitted, defaults to variant 0 — used by
        legacy saves written before M16a.
        """
        table = self._get_table(table_id)
        entry_map = {e.id: e for e in table.entries}
        if entry_id not in entry_map:
            raise KeyError(
                f"Entry '{entry_id}' not found in table '{table_id}'"
            )
        entry = entry_map[entry_id]

        is_list = isinstance(entry.text, list)
        effective_variant = variant if is_list else None
        if is_list:
            if effective_variant is None:
                effective_variant = 0
            if not 0 <= effective_variant < len(entry.text):
                raise IndexError(
                    f"variant {effective_variant} out of range for "
                    f"entry '{entry_id}' "
                    f"(len={len(entry.text)})"
                )

        def pick_variant(e: TableEntry) -> str:
            if e is entry:
                return _variant_text(e, effective_variant)
            return _variant_text(e, None)

        text = _formatter.format(
            entry,
            context=context,
            roll_subtable=None,
            pick_variant=pick_variant,
        )
        effect = self._parse_effect(entry.effect)
        return TableResult(
            text=text,
            entry_id=entry.id,
            effect=effect,
            variant_index=effective_variant,
        )

    def _get_table(self, table_id: str) -> Table:
        if table_id not in self._tables:
            raise UnknownTableError(
                f"Unknown table '{table_id}' "
                f"({len(self._tables)} tables loaded)"
            )
        return self._tables[table_id]

    def _format_entry(
        self,
        entry: TableEntry,
        rng: random.Random,
        context: dict,
        pick_variant,
    ) -> str:
        def roll_subtable(sub_id, ctx):
            sub_table = self._get_table(sub_id)
            sub_entry = _roll_entry(sub_table, rng, ctx)
            return sub_entry, sub_entry.id

        return _formatter.format(
            entry,
            context=context,
            roll_subtable=roll_subtable,
            pick_variant=pick_variant,
        )

    @staticmethod
    def _parse_effect(raw: dict | None) -> TableEffect | None:
        if raw is None:
            return None
        return TableEffect(kind=raw["kind"], payload=raw.get("payload", {}))


def _pick_variant_index(
    entry: TableEntry, rng: random.Random,
) -> int | None:
    """Choose a variant index for an entry, or None if text is a str."""
    if isinstance(entry.text, list):
        return rng.randrange(len(entry.text))
    return None


def _variant_text(entry: TableEntry, variant: int | None) -> str:
    text = entry.text
    if isinstance(text, list):
        idx = 0 if variant is None else variant
        return text[idx]
    return text
