"""Random tables subsystem — multilingual, weighted, composable."""

from __future__ import annotations

import random
from pathlib import Path

from nhc.tables.registry import TableRegistry
from nhc.tables.types import TableResult

__all__ = ["TableRegistry", "TableResult", "roll", "roll_ephemeral"]


def roll(
    table_id: str,
    *,
    lang: str,
    rng: random.Random | None,
    context: dict | None = None,
    root: Path | None = None,
) -> TableResult:
    """Convenience wrapper: load registry for *lang* and roll."""
    return TableRegistry.get_or_load(lang, root=root).roll(
        table_id, rng=rng, context=context or {},
    )


def roll_ephemeral(
    table_id: str,
    *,
    lang: str,
    context: dict | None = None,
) -> TableResult:
    """Roll an ephemeral table (no seed, not persisted)."""
    return TableRegistry.get_or_load(lang).roll(
        table_id, rng=None, context=context or {},
    )
