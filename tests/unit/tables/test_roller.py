"""Tests for nhc.tables.roller — weighted pick + context gating."""

import random
from collections import Counter
from pathlib import Path

import pytest

from nhc.tables.loader import load_table_file

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tables" / "roller"


def _load(name: str):
    return load_table_file(FIXTURES / name)[0]


class TestRoll:

    def test_roll_single_entry_always_returns_it(self):
        from nhc.tables.roller import roll

        table = _load("single.yaml")
        rng = random.Random(42)
        entry = roll(table, rng, {})
        assert entry.id == "only_one"

    def test_roll_respects_weights_over_10000_rolls(self):
        from nhc.tables.roller import roll

        table = _load("weighted.yaml")
        rng = random.Random(99)
        counts = Counter(
            roll(table, rng, {}).id for _ in range(10_000)
        )
        ratio = counts["common"] / counts["rare"]
        # Weight ratio is 3:1; allow ±20% tolerance
        assert 2.0 < ratio < 4.5, f"ratio {ratio:.2f} outside tolerance"

    def test_roll_same_seed_same_entry(self):
        from nhc.tables.roller import roll

        table = _load("weighted.yaml")
        a = roll(table, random.Random(123), {})
        b = roll(table, random.Random(123), {})
        assert a.id == b.id

    def test_roll_different_seed_eventually_different(self):
        from nhc.tables.roller import roll

        table = _load("weighted.yaml")
        ids = {roll(table, random.Random(i), {}).id for i in range(50)}
        assert len(ids) > 1

    def test_only_if_entry_level_filters(self):
        from nhc.tables.roller import roll

        table = _load("gated.yaml")
        rng = random.Random(42)
        ctx = {"terrain": "forest", "season": "summer"}
        # mushroom requires season=autumn, so it should never appear
        ids = {roll(table, rng, ctx).id for _ in range(200)}
        assert "mushroom" not in ids
        assert ids <= {"birdsong", "moss"}

    def test_only_if_table_level_filters(self):
        from nhc.tables.roller import NoMatchingEntriesError, roll

        table = _load("gated.yaml")
        rng = random.Random(42)
        # Table requires terrain=forest, passing desert
        with pytest.raises(NoMatchingEntriesError, match="roller.gated_table"):
            roll(table, rng, {"terrain": "desert"})

    def test_no_matching_entries_raises(self):
        from nhc.tables.roller import NoMatchingEntriesError, roll

        table = _load("all_gated.yaml")
        rng = random.Random(42)
        # No season matches
        with pytest.raises(NoMatchingEntriesError, match="roller.all_gated"):
            roll(table, rng, {"season": "summer"})
