"""Tests for dice roller and RNG."""

import random

import pytest

from nhc.utils.rng import d20, roll_dice, roll_dice_max


class TestRollDice:
    def test_1d6_in_range(self):
        rng = random.Random(42)
        for _ in range(100):
            result = roll_dice("1d6", rng)
            assert 1 <= result <= 6

    def test_2d6_in_range(self):
        rng = random.Random(42)
        for _ in range(100):
            result = roll_dice("2d6", rng)
            assert 2 <= result <= 12

    def test_modifier_positive(self):
        rng = random.Random(42)
        for _ in range(100):
            result = roll_dice("1d4+2", rng)
            assert 3 <= result <= 6

    def test_modifier_negative(self):
        rng = random.Random(42)
        for _ in range(100):
            result = roll_dice("1d8-1", rng)
            assert 0 <= result <= 7

    def test_seeded_reproducibility(self):
        r1 = roll_dice("3d6", random.Random(123))
        r2 = roll_dice("3d6", random.Random(123))
        assert r1 == r2

    def test_invalid_notation(self):
        with pytest.raises(ValueError):
            roll_dice("abc")

    def test_d20(self):
        rng = random.Random(42)
        for _ in range(100):
            assert 1 <= d20(rng) <= 20


class TestRollDiceMax:
    def test_1d6(self):
        assert roll_dice_max("1d6") == 6

    def test_2d4_plus_2(self):
        assert roll_dice_max("2d4+2") == 10

    def test_1d8_minus_1(self):
        assert roll_dice_max("1d8-1") == 7
