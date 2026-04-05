"""Tests for dice roller and RNG."""

import random
from unittest.mock import MagicMock

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


class TestThreadIsolation:
    def test_concurrent_seeds_dont_interfere(self):
        """Each thread gets its own RNG — seeds don't cross threads."""
        import threading
        from nhc.utils.rng import get_rng, set_seed

        set_seed(100)
        results = {}

        def _other_thread():
            set_seed(999)
            results["other_rng"] = get_rng().randint(0, 10000)

        thread = threading.Thread(target=_other_thread)
        thread.start()
        thread.join()

        # Main thread RNG should be unaffected by the other thread
        main_val = get_rng().randint(0, 10000)
        set_seed(100)
        expected = get_rng().randint(0, 10000)
        assert main_val == expected


class TestGameSeedPreservation:
    """Game.seed must always hold the effective seed after init."""

    def test_seed_preserved_when_explicit(self, tmp_path):
        """When a seed is passed, Game.seed keeps that value."""
        from nhc.core.game import Game
        client = MagicMock()
        game = Game(client, seed=12345, save_dir=tmp_path)
        game.initialize(generate=True)
        assert game.seed == 12345

    def test_seed_preserved_when_none(self, tmp_path):
        """When no seed is passed, Game.seed stores the auto-generated
        seed so it can be included in debug exports."""
        from nhc.core.game import Game
        client = MagicMock()
        game = Game(client, seed=None, save_dir=tmp_path)
        game.initialize(generate=True)
        assert game.seed is not None
        assert isinstance(game.seed, int)

    def test_seed_survives_autosave_roundtrip(self, tmp_path):
        """Seed must be preserved through autosave/restore."""
        from nhc.core.autosave import auto_restore, autosave
        from nhc.core.game import Game
        client = MagicMock()
        game = Game(client, seed=99999, save_dir=tmp_path)
        game.initialize(generate=True)
        assert game.seed == 99999

        autosave(game, tmp_path, blocking=True)

        game2 = Game(client, seed=None, save_dir=tmp_path)
        assert auto_restore(game2, tmp_path)
        assert game2.seed == 99999
