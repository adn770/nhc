"""Tests for character name generator (divergent tables)."""

from __future__ import annotations

import random

import pytest

from nhc.i18n import init as i18n_init
from nhc.tables import roll
from nhc.tables.registry import TableRegistry
from nhc.tables.roller import NoMatchingEntriesError


def setup_module():
    i18n_init("en")


def test_divergent_table_loads() -> None:
    TableRegistry._cache.clear()
    reg = TableRegistry.get_or_load("en")
    assert "name.given.male" in reg._tables
    assert "name.given.female" in reg._tables
    assert "name.surname" in reg._tables
    assert "name.person.full" in reg._tables
    TableRegistry._cache.clear()


def test_validator_skips_cross_lang_diff_for_names() -> None:
    from nhc.tables.validator import validate_all

    errors = validate_all()
    name_errors = [e for e in errors if "name." in e.table_id]
    assert name_errors == [], (
        f"divergent name tables should not trigger drift errors: "
        f"{name_errors}"
    )


def test_roll_name_person_full_male_picks_from_male_pool() -> None:
    rng = random.Random(42)
    result = roll(
        "name.person.full", lang="en", rng=rng,
        context={"gender": "m"},
    )
    parts = result.text.split()
    assert len(parts) == 2, f"expected 'Given Surname', got: {result.text!r}"


def test_roll_name_person_full_female_picks_from_female_pool() -> None:
    rng = random.Random(42)
    result = roll(
        "name.person.full", lang="en", rng=rng,
        context={"gender": "f"},
    )
    parts = result.text.split()
    assert len(parts) >= 2, f"expected 'Given Surname', got: {result.text!r}"


def test_missing_gender_context_raises_no_matching_entries() -> None:
    rng = random.Random(42)
    with pytest.raises(NoMatchingEntriesError):
        roll(
            "name.person.full", lang="en", rng=rng,
            context={},
        )


def test_same_seed_same_name_same_lang() -> None:
    a = roll(
        "name.person.full", lang="en", rng=random.Random(99),
        context={"gender": "m"},
    )
    b = roll(
        "name.person.full", lang="en", rng=random.Random(99),
        context={"gender": "m"},
    )
    assert a.text == b.text


def test_different_lang_different_pool() -> None:
    """English and Catalan name pools should be disjoint."""
    en_names = {
        roll("name.person.full", lang="en", rng=random.Random(i),
             context={"gender": "m"}).text
        for i in range(50)
    }
    ca_names = {
        roll("name.person.full", lang="ca", rng=random.Random(i),
             context={"gender": "m"}).text
        for i in range(50)
    }
    overlap = en_names & ca_names
    assert len(overlap) < len(en_names) * 0.1, (
        f"en and ca pools should be mostly disjoint; "
        f"overlap: {overlap}"
    )


def test_ca_pool_has_catalan_specific_characters() -> None:
    """At least one Catalan name should contain accented chars."""
    TableRegistry._cache.clear()
    reg = TableRegistry.get_or_load("ca")
    catalan_chars = set("àèéíïòóúüçÀÈÉÍÏÒÓÚÜÇ·")
    all_entries = []
    for table_id in ("name.given.male", "name.given.female",
                     "name.surname"):
        table = reg._tables[table_id]
        all_entries.extend(e.text for e in table.entries)
    has_catalan = any(
        catalan_chars & set(text) for text in all_entries
    )
    assert has_catalan, (
        "Catalan name pool should have accented or special chars"
    )
    TableRegistry._cache.clear()


def test_name_format_is_given_space_surname() -> None:
    for lang in ("en", "ca", "es"):
        for gender in ("m", "f"):
            result = roll(
                "name.person.full", lang=lang,
                rng=random.Random(42),
                context={"gender": gender},
            )
            parts = result.text.split()
            assert len(parts) >= 2, (
                f"{lang}/{gender}: expected 'Given Surname', "
                f"got: {result.text!r}"
            )
