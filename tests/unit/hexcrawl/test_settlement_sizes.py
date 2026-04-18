"""Tests for settlement size-class variation in feature placement."""

from __future__ import annotations

import random

from nhc.hexcrawl._features import _pick_village_size_class


class TestVillageSizeClassPick:
    def test_returns_one_of_three_classes(self):
        rng = random.Random(0)
        for _ in range(50):
            sc = _pick_village_size_class(rng)
            assert sc in {"hamlet", "village", "town"}

    def test_distribution_covers_all_classes(self):
        """Over many rolls, every size class should appear."""
        rng = random.Random(42)
        seen: set[str] = set()
        for _ in range(500):
            seen.add(_pick_village_size_class(rng))
        assert seen == {"hamlet", "village", "town"}

    def test_hamlet_and_village_dominate_town(self):
        """Towns are rarer than hamlets or villages."""
        rng = random.Random(42)
        counts = {"hamlet": 0, "village": 0, "town": 0}
        for _ in range(2000):
            counts[_pick_village_size_class(rng)] += 1
        assert counts["town"] < counts["village"]
        assert counts["town"] < counts["hamlet"]
