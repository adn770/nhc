"""M13 chargen integration — traits rolled via TableRegistry."""

from __future__ import annotations

from collections import Counter
from unittest.mock import patch

from nhc.rules.chargen import generate_character
from nhc.tables.registry import TableRegistry


def test_generate_character_goes_through_table_registry() -> None:
    with patch.object(
        TableRegistry, "get_or_load", wraps=TableRegistry.get_or_load,
    ) as spy:
        generate_character(seed=42)
    assert spy.called, "chargen did not load a TableRegistry"


def test_generated_alignment_in_expected_set() -> None:
    for seed in range(50):
        char = generate_character(seed=seed)
        assert char.alignment in ("lawful", "neutral", "chaotic")


def test_alignment_weighting_matches_5_10_5() -> None:
    """Over many seeded rolls alignment follows 25/50/25 (±3%)."""
    counts: Counter[str] = Counter()
    n = 2_000
    for seed in range(n):
        char = generate_character(seed=seed)
        counts[char.alignment] += 1
    assert abs(counts["lawful"] / n - 0.25) < 0.03, counts
    assert abs(counts["neutral"] / n - 0.50) < 0.03, counts
    assert abs(counts["chaotic"] / n - 0.25) < 0.03, counts


def test_generated_traits_are_known_entry_ids() -> None:
    from nhc.tables.loader import load_lang
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "nhc" / "tables" / "locales"
    tables = load_lang("en", root=root)
    axis_to_table = {
        "physique": "trait.physique",
        "face": "trait.face",
        "skin": "trait.skin",
        "hair": "trait.hair",
        "clothing": "trait.clothing",
        "virtue": "trait.virtue",
        "vice": "trait.vice",
        "speech": "trait.speech",
        "background": "trait.background",
        "misfortune": "trait.misfortune",
        "alignment": "trait.alignment",
    }
    for seed in range(10):
        char = generate_character(seed=seed)
        for axis, table_id in axis_to_table.items():
            value = getattr(char, axis)
            ids = {e.id for e in tables[table_id].entries}
            assert value in ids, (
                f"seed {seed}: {axis}={value!r} not in {table_id}"
            )


def test_deterministic_traits_after_migration() -> None:
    a = generate_character(seed=12345)
    b = generate_character(seed=12345)
    for trait in (
        "physique", "face", "skin", "hair", "clothing",
        "virtue", "vice", "speech", "background",
        "misfortune", "alignment",
    ):
        assert getattr(a, trait) == getattr(b, trait), trait
