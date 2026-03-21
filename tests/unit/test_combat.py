"""Tests for combat resolution."""

import random

from nhc.entities.components import Health, Stats
from nhc.rules.combat import apply_damage, heal, is_dead, resolve_melee_attack


class TestMeleeAttack:
    def test_natural_20_always_hits(self):
        attacker = Stats(strength=0)
        target = Stats(dexterity=10)  # Armor defense 20
        # Seed that produces a 20 on first d20
        rng = random.Random()
        hit_count = 0
        for seed in range(1000):
            rng.seed(seed)
            if rng.randint(1, 20) == 20:
                rng.seed(seed)
                hit, dmg = resolve_melee_attack(
                    attacker, target, "1d6", rng,
                )
                assert hit
                assert dmg > 0
                hit_count += 1
        assert hit_count > 0  # Ensure we tested at least one crit

    def test_natural_1_always_misses(self):
        attacker = Stats(strength=10)
        target = Stats(dexterity=0)  # Armor defense 10
        rng = random.Random()
        for seed in range(1000):
            rng.seed(seed)
            if rng.randint(1, 20) == 1:
                rng.seed(seed)
                hit, dmg = resolve_melee_attack(
                    attacker, target, "1d6", rng,
                )
                assert not hit
                assert dmg == 0
                return
        assert False, "No natural 1 found"

    def test_high_str_hits_more(self):
        strong = Stats(strength=5)
        weak = Stats(strength=0)
        target = Stats(dexterity=2)
        rng = random.Random(42)

        strong_hits = sum(
            resolve_melee_attack(strong, target, "1d6", random.Random(s))[0]
            for s in range(200)
        )
        weak_hits = sum(
            resolve_melee_attack(weak, target, "1d6", random.Random(s))[0]
            for s in range(200)
        )
        assert strong_hits > weak_hits

    def test_damage_minimum_1(self):
        attacker = Stats(strength=0)
        target = Stats(dexterity=0)
        rng = random.Random(42)
        for _ in range(100):
            hit, dmg = resolve_melee_attack(
                attacker, target, "1d4", rng,
            )
            if hit:
                assert dmg >= 1


class TestHealthHelpers:
    def test_apply_damage(self):
        h = Health(current=10, maximum=10)
        actual = apply_damage(h, 3)
        assert actual == 3
        assert h.current == 7

    def test_apply_damage_overkill(self):
        h = Health(current=3, maximum=10)
        actual = apply_damage(h, 10)
        assert actual == 3
        assert h.current == 0

    def test_heal(self):
        h = Health(current=5, maximum=10)
        actual = heal(h, 3)
        assert actual == 3
        assert h.current == 8

    def test_heal_capped_at_max(self):
        h = Health(current=8, maximum=10)
        actual = heal(h, 5)
        assert actual == 2
        assert h.current == 10

    def test_is_dead(self):
        assert is_dead(Health(current=0, maximum=10))
        assert not is_dead(Health(current=1, maximum=10))
