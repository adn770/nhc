"""Tests for the Knave / Basic D&D morale check primitive."""

import random

import pytest

from nhc.ai.tactics import morale_check


pytestmark = pytest.mark.rules


class TestMoraleCheck:
    """2d6 ≤ morale → pass (creature holds courage)."""

    def test_morale_12_always_passes(self):
        """A morale of 12 cannot fail (max 2d6 = 12)."""
        for seed in range(100):
            rng = random.Random(seed)
            assert morale_check(12, rng) is True

    def test_morale_1_always_fails(self):
        """A morale of 1 cannot pass (min 2d6 = 2)."""
        for seed in range(100):
            rng = random.Random(seed)
            assert morale_check(1, rng) is False

    def test_morale_2_passes_only_on_snake_eyes(self):
        """Morale 2 passes only when 2d6 = 2 (both dice show 1)."""
        passes = 0
        for seed in range(2000):
            rng = random.Random(seed)
            if morale_check(2, rng):
                passes += 1
        # Snake eyes is 1/36, so ~55 successes expected in 2000 rolls.
        assert 30 <= passes <= 90

    def test_morale_7_roughly_balanced(self):
        """Morale 7 is the median — passes ~58% of the time
        (P[2d6 ≤ 7] = 21/36)."""
        passes = 0
        trials = 5000
        for seed in range(trials):
            rng = random.Random(seed)
            if morale_check(7, rng):
                passes += 1
        ratio = passes / trials
        assert 0.53 <= ratio <= 0.63

    def test_returns_bool(self):
        """Function returns a real bool, not an int."""
        rng = random.Random(0)
        result = morale_check(7, rng)
        assert isinstance(result, bool)

    def test_uses_thread_local_rng_when_none(self):
        """Passing rng=None uses the seeded thread-local RNG."""
        from nhc.utils.rng import set_seed

        set_seed(12345)
        a = morale_check(7)
        set_seed(12345)
        b = morale_check(7)
        assert a == b
