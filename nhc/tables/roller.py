"""Weighted roller with context gating for random tables."""

from __future__ import annotations

import random

from nhc.tables.types import Table, TableEntry


class NoMatchingEntriesError(Exception):
    """Raised when all entries are filtered out by only_if."""


def roll(table: Table, rng: random.Random, context: dict) -> TableEntry:
    """Pick a weighted-random entry from *table*, honoring only_if gates.

    Raises NoMatchingEntriesError when every entry is filtered out.
    """
    if table.only_if and not _matches_only_if(table.only_if, context):
        raise NoMatchingEntriesError(
            f"Table '{table.id}': table-level only_if not satisfied"
        )

    candidates = [
        e for e in table.entries
        if not e.only_if or _matches_only_if(e.only_if, context)
    ]

    if not candidates:
        raise NoMatchingEntriesError(
            f"Table '{table.id}': no entries match the given context"
        )

    weights = [e.weight for e in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _matches_only_if(constraint: dict, context: dict) -> bool:
    """Check if *context* satisfies all *constraint* conditions.

    Supports scalar equality and list membership (value in list).
    """
    for key, expected in constraint.items():
        actual = context.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True
