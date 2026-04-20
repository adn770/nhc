"""Template formatter with sub-table composition and agreement.

Resolves template strings via str.format with a pre-pass for
{@id} sub-table markers and {@id:agree=slot} agreement hints.
Cycle-guarded at depth 8.
"""

from __future__ import annotations

import re
from typing import Callable

from nhc.tables.types import TableEntry

_MAX_DEPTH = 8

# Matches {@table_id} and {@table_id:agree=slot}
_SUBTABLE_RE = re.compile(r"\{@([a-zA-Z0-9_.]+)(?::agree=([a-zA-Z0-9_]+))?\}")


class MissingContextError(Exception):
    """Raised when a required context variable is missing."""


class RecursionTooDeepError(Exception):
    """Raised when sub-table resolution exceeds max depth."""


# roll_subtable signature: (table_id, context) -> (TableEntry, entry_id)
RollSubtable = Callable[[str, dict], tuple[TableEntry, str]]

# pick_variant resolves an entry's text to a single string.
# Called both for the top-level entry and for each sub-entry.
PickVariant = Callable[[TableEntry], str]


def _pick_first_variant(entry: TableEntry) -> str:
    """Default variant picker: pass-through str, list → first item."""
    text = entry.text
    if isinstance(text, list):
        return text[0]
    return text


class StrFormatFormatter:
    """Format table entry templates using str.format_map."""

    def format(
        self,
        entry: TableEntry,
        context: dict,
        roll_subtable: RollSubtable | None,
        pick_variant: PickVariant | None = None,
    ) -> str:
        picker = pick_variant or _pick_first_variant
        template = picker(entry)
        template = self._resolve_subtables(
            template, roll_subtable, picker, context, depth=0,
        )
        return template.format_map(_ContextMap(context))

    def _resolve_subtables(
        self,
        template: str,
        roll_subtable: RollSubtable | None,
        pick_variant: PickVariant,
        context: dict,
        depth: int,
    ) -> str:
        if depth > _MAX_DEPTH:
            raise RecursionTooDeepError(
                f"Sub-table resolution exceeded depth {_MAX_DEPTH}"
            )

        def _replace(match: re.Match) -> str:
            table_id = match.group(1)
            agree_slot = match.group(2)

            sub_entry, _ = roll_subtable(table_id, context)
            sub_text = pick_variant(sub_entry)
            sub_text = self._resolve_subtables(
                sub_text, roll_subtable, pick_variant, context, depth + 1,
            )

            if agree_slot and sub_entry.forms:
                slot_meta = context.get(agree_slot)
                if isinstance(slot_meta, dict):
                    tag = slot_meta.get("gender") or slot_meta.get("number")
                    if tag and tag in sub_entry.forms:
                        return sub_entry.forms[tag]

            return sub_text

        if roll_subtable is None:
            return template

        return _SUBTABLE_RE.sub(_replace, template)


class _ContextMap(dict):
    """Dict wrapper that raises MissingContextError on missing keys."""

    def __init__(self, context: dict):
        super().__init__()
        self._context = context

    def __getitem__(self, key: str) -> str:
        try:
            return self._context[key]
        except KeyError:
            raise MissingContextError(
                f"Missing context variable '{key}'"
            ) from None

    def __contains__(self, key: object) -> bool:
        return key in self._context
