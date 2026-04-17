"""Tests for double gold in character generation.

Milestone W2.
"""

from __future__ import annotations

from nhc.rules.chargen import generate_character


def test_default_gold_range() -> None:
    """Normal gold: 3d6 × 20 ÷ 10 = 6-36 gold."""
    for seed in range(50):
        sheet = generate_character(seed=seed)
        assert 6 <= sheet.gold <= 36, (
            f"seed {seed}: gold {sheet.gold} out of normal range"
        )


def test_double_gold_range() -> None:
    """Double gold: 6d6 × 20 ÷ 10 = 12-72 gold."""
    for seed in range(50):
        sheet = generate_character(seed=seed, double_gold=True)
        assert 12 <= sheet.gold <= 72, (
            f"seed {seed}: gold {sheet.gold} out of double range"
        )


def test_double_gold_higher_average() -> None:
    """Double gold should average significantly higher."""
    normal_total = sum(
        generate_character(seed=s).gold for s in range(100)
    )
    double_total = sum(
        generate_character(seed=s, double_gold=True).gold
        for s in range(100)
    )
    assert double_total > normal_total * 1.5


def test_double_gold_false_is_default() -> None:
    """Explicitly passing double_gold=False matches default."""
    for seed in range(20):
        a = generate_character(seed=seed)
        b = generate_character(seed=seed, double_gold=False)
        assert a.gold == b.gold
