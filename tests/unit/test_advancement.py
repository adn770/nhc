"""Tests for XP and level-up system."""

import pytest

from nhc.core.ecs import World
from nhc.entities.components import Health, Player, Stats
from nhc.rules.advancement import (
    award_xp,
    check_level_up,
    xp_for_level,
    _pick_lowest_ability,
)
from nhc.utils.rng import set_seed


class TestXPFormula:
    def test_xp_for_level_2(self):
        assert xp_for_level(2) == 20

    def test_xp_for_level_3(self):
        assert xp_for_level(3) == 60

    def test_xp_for_level_4(self):
        assert xp_for_level(4) == 120


class TestAwardXP:
    def test_award_xp_based_on_max_hp(self):
        world = World()
        pid = world.create_entity({
            "Player": Player(xp=0, level=1, xp_to_next=20),
        })
        cid = world.create_entity({
            "Health": Health(current=0, maximum=6),
        })

        xp = award_xp(world, pid, cid)
        assert xp == 30  # 6 * 5
        assert world.get_component(pid, "Player").xp == 30

    def test_no_xp_without_player_component(self):
        world = World()
        pid = world.create_entity({})
        cid = world.create_entity({
            "Health": Health(current=0, maximum=4),
        })

        xp = award_xp(world, pid, cid)
        assert xp == 0


class TestLevelUp:
    def test_level_up_increases_hp(self):
        set_seed(42)
        world = World()
        pid = world.create_entity({
            "Player": Player(xp=25, level=1, xp_to_next=20),
            "Health": Health(current=12, maximum=12),
            "Stats": Stats(strength=2, dexterity=2, constitution=2,
                           intelligence=1, wisdom=1, charisma=0),
        })

        msgs = check_level_up(world, pid)
        assert len(msgs) >= 1
        assert "Level 2" in msgs[0]

        player = world.get_component(pid, "Player")
        assert player.level == 2

        health = world.get_component(pid, "Health")
        assert health.maximum > 12

    def test_no_level_up_when_not_enough_xp(self):
        world = World()
        pid = world.create_entity({
            "Player": Player(xp=10, level=1, xp_to_next=20),
            "Health": Health(current=12, maximum=12),
            "Stats": Stats(),
        })

        msgs = check_level_up(world, pid)
        assert len(msgs) == 0

    def test_multiple_level_ups(self):
        set_seed(42)
        world = World()
        pid = world.create_entity({
            "Player": Player(xp=200, level=1, xp_to_next=20),
            "Health": Health(current=12, maximum=12),
            "Stats": Stats(strength=2, dexterity=2, constitution=2),
        })

        msgs = check_level_up(world, pid)
        player = world.get_component(pid, "Player")
        assert player.level > 2  # Should have leveled up multiple times


class TestPickLowestAbility:
    def test_picks_lowest(self):
        stats = Stats(strength=3, dexterity=2, constitution=1,
                      intelligence=2, wisdom=2, charisma=2)
        assert _pick_lowest_ability(stats) == "constitution"

    def test_tie_breaks_by_order(self):
        stats = Stats(strength=0, dexterity=0, constitution=0,
                      intelligence=0, wisdom=0, charisma=0)
        # Should pick first in order (strength)
        assert _pick_lowest_ability(stats) == "strength"
