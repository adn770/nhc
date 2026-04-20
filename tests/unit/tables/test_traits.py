"""M13 trait tables — structural and distribution checks.

These tests verify that the 11 trait tables (physique, face, skin,
hair, clothing, virtue, vice, speech, background, misfortune,
alignment) ship as first-class tables under
``nhc/tables/locales/{en,ca,es}/traits.yaml`` and behave as the
chargen migration plan specifies.
"""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pytest

from nhc.tables.loader import load_lang
from nhc.tables.registry import (
    GenTimeRNGRequiredError,
    TableRegistry,
)
from nhc.tables.validator import validate_all

LOCALES_ROOT = (
    Path(__file__).resolve().parents[3] / "nhc" / "tables" / "locales"
)

TRAIT_TABLE_IDS = (
    "trait.physique",
    "trait.face",
    "trait.skin",
    "trait.hair",
    "trait.clothing",
    "trait.virtue",
    "trait.vice",
    "trait.speech",
    "trait.background",
    "trait.misfortune",
    "trait.alignment",
)

D20_TABLES = tuple(tid for tid in TRAIT_TABLE_IDS if tid != "trait.alignment")


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
def test_all_trait_tables_load(lang: str) -> None:
    tables = load_lang(lang, root=LOCALES_ROOT)
    for table_id in TRAIT_TABLE_IDS:
        assert table_id in tables, (
            f"{lang}: table '{table_id}' not loaded"
        )


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
def test_trait_tables_are_flavor_gen_time_shared(lang: str) -> None:
    tables = load_lang(lang, root=LOCALES_ROOT)
    for table_id in TRAIT_TABLE_IDS:
        t = tables[table_id]
        assert t.kind == "flavor", f"{table_id}: kind={t.kind}"
        assert t.lifetime == "gen_time", (
            f"{table_id}: lifetime={t.lifetime}"
        )
        assert t.shared_structure is True, (
            f"{table_id}: shared_structure={t.shared_structure}"
        )


@pytest.mark.parametrize("table_id", D20_TABLES)
def test_d20_trait_tables_have_20_entries(table_id: str) -> None:
    tables = load_lang("en", root=LOCALES_ROOT)
    assert len(tables[table_id].entries) == 20, (
        f"{table_id}: expected 20 entries"
    )


def test_alignment_table_entries_and_weights() -> None:
    tables = load_lang("en", root=LOCALES_ROOT)
    t = tables["trait.alignment"]
    by_id = {e.id: e for e in t.entries}
    assert set(by_id) == {"lawful", "neutral", "chaotic"}
    assert by_id["lawful"].weight == 5
    assert by_id["neutral"].weight == 10
    assert by_id["chaotic"].weight == 5


def test_cross_language_shared_structure_parity() -> None:
    errors = [
        e for e in validate_all(root=LOCALES_ROOT)
        if e.table_id in TRAIT_TABLE_IDS
    ]
    assert errors == [], "\n".join(e.detail for e in errors)


def test_virtue_text_differs_across_locales() -> None:
    """Virtue has real CA/ES translations in-tree; entry ids shared."""
    TableRegistry._cache.clear()
    try:
        en = TableRegistry.get_or_load("en", root=LOCALES_ROOT)
        ca = TableRegistry.get_or_load("ca", root=LOCALES_ROOT)
        es = TableRegistry.get_or_load("es", root=LOCALES_ROOT)
        en_r = en.render(
            "trait.virtue", entry_id="brave", context={},
        )
        ca_r = ca.render(
            "trait.virtue", entry_id="brave", context={},
        )
        es_r = es.render(
            "trait.virtue", entry_id="brave", context={},
        )
        assert en_r.entry_id == ca_r.entry_id == es_r.entry_id == "brave"
        assert en_r.text == "brave"
        assert ca_r.text == "valent"
        assert es_r.text == "valiente"
    finally:
        TableRegistry._cache.clear()


def test_alignment_distribution_weighted() -> None:
    """Over 10k rolls: lawful ~25%, neutral ~50%, chaotic ~25% (±1%)."""
    TableRegistry._cache.clear()
    try:
        reg = TableRegistry.get_or_load("en", root=LOCALES_ROOT)
        rng = random.Random(0xA11)
        counts: Counter[str] = Counter()
        n = 10_000
        for _ in range(n):
            r = reg.roll("trait.alignment", rng=rng, context={})
            counts[r.entry_id] += 1
        lawful_pct = counts["lawful"] / n
        neutral_pct = counts["neutral"] / n
        chaotic_pct = counts["chaotic"] / n
        assert abs(lawful_pct - 0.25) < 0.01, lawful_pct
        assert abs(neutral_pct - 0.50) < 0.01, neutral_pct
        assert abs(chaotic_pct - 0.25) < 0.01, chaotic_pct
    finally:
        TableRegistry._cache.clear()


@pytest.mark.parametrize("table_id", TRAIT_TABLE_IDS)
def test_trait_roll_without_rng_raises(table_id: str) -> None:
    """gen_time tables must reject unseeded rolls."""
    TableRegistry._cache.clear()
    try:
        reg = TableRegistry.get_or_load("en", root=LOCALES_ROOT)
        with pytest.raises(GenTimeRNGRequiredError):
            reg.roll(table_id, rng=None, context={})
    finally:
        TableRegistry._cache.clear()
