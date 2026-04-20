"""M15 — chargen name generation via name.person.full TableRegistry."""

from __future__ import annotations

import random
import re
from collections import Counter

import pytest

from nhc.rules.chargen import generate_character
from nhc.tables.registry import TableRegistry


def test_generate_character_uses_name_person_full() -> None:
    """The name is rolled against name.person.full, not Python constants."""
    original_roll = TableRegistry.roll
    observed: list[str] = []

    def spy(self, table_id, **kwargs):
        observed.append(table_id)
        return original_roll(self, table_id, **kwargs)

    TableRegistry._cache.clear()
    try:
        TableRegistry.roll = spy  # type: ignore[assignment]
        generate_character(seed=42, lang="en")
    finally:
        TableRegistry.roll = original_roll  # type: ignore[assignment]
        TableRegistry._cache.clear()

    assert "name.person.full" in observed


def test_name_deterministic_per_seed_and_lang() -> None:
    a = generate_character(seed=777, lang="en")
    b = generate_character(seed=777, lang="en")
    assert a.name == b.name


def test_name_differs_across_langs_for_same_seed() -> None:
    en = generate_character(seed=1234, lang="en")
    ca = generate_character(seed=1234, lang="ca")
    es = generate_character(seed=1234, lang="es")
    # With shared_structure: false, different pools → different names
    assert len({en.name, ca.name, es.name}) == 3, (
        f"en={en.name} ca={ca.name} es={es.name}"
    )


def test_ca_name_contains_catalan_marker() -> None:
    """Sampling CA names should hit at least one Catalan-specific char."""
    ca_markers = re.compile(r"[çàèéíïòóúü·]|l·l", re.IGNORECASE)
    has_marker = False
    for seed in range(200):
        name = generate_character(seed=seed, lang="ca").name
        if ca_markers.search(name):
            has_marker = True
            break
    assert has_marker, "no CA name in 200 seeds contained a Catalan marker"


def test_gender_distribution_roughly_50_50() -> None:
    """Male/female first-name coin flip remains ~50/50."""
    male_markers: set[str] = set()
    female_markers: set[str] = set()
    from nhc.tables.loader import load_lang
    from pathlib import Path

    tables = load_lang(
        "en",
        root=Path(__file__).resolve().parents[2]
        / "nhc" / "tables" / "locales",
    )
    for e in tables["name.given.male"].entries:
        male_markers.add(e.text)
    for e in tables["name.given.female"].entries:
        female_markers.add(e.text)

    counts = Counter({"m": 0, "f": 0})
    for seed in range(2_000):
        name = generate_character(seed=seed, lang="en").name
        first = name.split()[0]
        if first in male_markers:
            counts["m"] += 1
        elif first in female_markers:
            counts["f"] += 1
    total = counts["m"] + counts["f"]
    assert total > 1_900, f"too few categorized names: {counts}"
    assert abs(counts["m"] / total - 0.5) < 0.05, counts


def test_legacy_name_constants_are_gone() -> None:
    import nhc.rules.chargen as chargen

    for name in ("NAMES_MALE", "NAMES_FEMALE", "SURNAMES"):
        assert not hasattr(chargen, name), (
            f"chargen.py still exposes legacy symbol '{name}'"
        )
