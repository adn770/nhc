"""Tests for XP, leveling, and HP advancement (Knave rules).

Knave advancement rules:
- Every 1000 XP = 1 level (linear)
- HP on level up: roll new_level × d8; if > old max, use it; else max + 1
- 3 different abilities raised by 1 (lowest-first), capped at 10
- Max level 10
"""

from nhc.core.ecs import World
from nhc.entities.components import Health, Inventory, Player, Stats
from nhc.rules.advancement import (
    MAX_ABILITY_BONUS,
    MAX_LEVEL,
    XP_PER_LEVEL,
    award_xp,
    check_level_up,
    xp_for_level,
    _pick_lowest_abilities,
)
from nhc.utils.rng import set_seed


def _make_world(
    xp: int = 0, level: int = 1, hp: int = 8, hp_max: int = 8,
    stats: Stats | None = None,
) -> tuple[World, int]:
    """Create a world with a player entity."""
    world = World()
    player_id = world.create_entity({
        "Player": Player(xp=xp, level=level, xp_to_next=xp_for_level(level + 1)),
        "Health": Health(current=hp, maximum=hp_max),
        "Stats": stats or Stats(
            strength=1, dexterity=2, constitution=2,
            intelligence=1, wisdom=1, charisma=1,
        ),
        "Inventory": Inventory(max_slots=12),
    })
    return world, player_id


def _make_creature(world: World, hp_max: int = 4) -> int:
    return world.create_entity({
        "Health": Health(current=hp_max, maximum=hp_max),
    })


class TestXPFormula:
    def test_level_1_threshold(self):
        assert xp_for_level(1) == 0

    def test_level_2_threshold(self):
        assert xp_for_level(2) == XP_PER_LEVEL

    def test_level_10_threshold(self):
        assert xp_for_level(10) == XP_PER_LEVEL * 9

    def test_linear_scaling(self):
        """Each level costs the same amount of XP."""
        for lv in range(2, MAX_LEVEL + 1):
            assert xp_for_level(lv) - xp_for_level(lv - 1) == XP_PER_LEVEL


class TestAwardXP:
    def test_xp_based_on_creature_hp(self):
        world, pid = _make_world()
        cid = _make_creature(world, hp_max=6)
        xp = award_xp(world, pid, cid)
        assert xp == 30  # 6 * 5
        assert world.get_component(pid, "Player").xp == 30

    def test_xp_accumulates(self):
        world, pid = _make_world(xp=50)
        cid = _make_creature(world, hp_max=4)
        xp = award_xp(world, pid, cid)
        player = world.get_component(pid, "Player")
        assert player.xp == 50 + xp

    def test_no_player_returns_zero(self):
        world = World()
        cid = _make_creature(world, hp_max=4)
        assert award_xp(world, 999, cid) == 0

    def test_no_health_returns_zero(self):
        world, pid = _make_world()
        no_health = world.create_entity({})
        assert award_xp(world, pid, no_health) == 0


class TestLevelUp:
    def test_level_up_increments_level(self):
        set_seed(42)
        world, pid = _make_world(xp=XP_PER_LEVEL)
        msgs = check_level_up(world, pid)
        player = world.get_component(pid, "Player")
        assert player.level == 2
        assert len(msgs) >= 1

    def test_no_xp_no_level_up(self):
        world, pid = _make_world(xp=0)
        msgs = check_level_up(world, pid)
        player = world.get_component(pid, "Player")
        assert player.level == 1
        assert len(msgs) == 0

    def test_hp_at_least_plus_one(self):
        """On level up, max HP increases by at least 1."""
        set_seed(42)
        world, pid = _make_world(xp=XP_PER_LEVEL, hp_max=8)
        old_max = world.get_component(pid, "Health").maximum
        check_level_up(world, pid)
        new_max = world.get_component(pid, "Health").maximum
        assert new_max >= old_max + 1

    def test_hp_knave_reroll_low(self):
        """Knave: roll new_level*d8; if result < old max, max increases by 1."""
        set_seed(42)
        world, pid = _make_world(xp=XP_PER_LEVEL, hp_max=100)
        check_level_up(world, pid)
        health = world.get_component(pid, "Health")
        # 2d8 can't beat 100 — so it should be 101
        assert health.maximum == 101

    def test_current_hp_also_increases(self):
        """Current HP should increase along with max HP."""
        set_seed(42)
        world, pid = _make_world(xp=XP_PER_LEVEL, hp=5, hp_max=8)
        old_current = world.get_component(pid, "Health").current
        check_level_up(world, pid)
        new_current = world.get_component(pid, "Health").current
        assert new_current > old_current

    def test_three_abilities_raised(self):
        """Knave: 3 different abilities increase by 1 on level up."""
        set_seed(42)
        stats = Stats(
            strength=1, dexterity=2, constitution=2,
            intelligence=1, wisdom=1, charisma=1,
        )
        world, pid = _make_world(xp=XP_PER_LEVEL, stats=stats)
        old_total = sum([
            stats.strength, stats.dexterity, stats.constitution,
            stats.intelligence, stats.wisdom, stats.charisma,
        ])
        check_level_up(world, pid)
        new_stats = world.get_component(pid, "Stats")
        new_total = sum([
            new_stats.strength, new_stats.dexterity,
            new_stats.constitution, new_stats.intelligence,
            new_stats.wisdom, new_stats.charisma,
        ])
        assert new_total == old_total + 3

    def test_ability_cap(self):
        """Abilities cannot exceed MAX_ABILITY_BONUS (10)."""
        set_seed(42)
        stats = Stats(
            strength=MAX_ABILITY_BONUS, dexterity=MAX_ABILITY_BONUS,
            constitution=MAX_ABILITY_BONUS,
            intelligence=MAX_ABILITY_BONUS, wisdom=MAX_ABILITY_BONUS,
            charisma=MAX_ABILITY_BONUS,
        )
        world, pid = _make_world(xp=XP_PER_LEVEL, stats=stats)
        check_level_up(world, pid)
        new_stats = world.get_component(pid, "Stats")
        # All capped — none should exceed max
        for attr in ["strength", "dexterity", "constitution",
                     "intelligence", "wisdom", "charisma"]:
            assert getattr(new_stats, attr) == MAX_ABILITY_BONUS

    def test_max_level_cap(self):
        """Player cannot exceed MAX_LEVEL."""
        set_seed(42)
        world, pid = _make_world(
            xp=XP_PER_LEVEL * MAX_LEVEL, level=MAX_LEVEL,
        )
        msgs = check_level_up(world, pid)
        player = world.get_component(pid, "Player")
        assert player.level == MAX_LEVEL
        assert len(msgs) == 0

    def test_multi_level_up(self):
        """Gaining enough XP for multiple levels processes all."""
        set_seed(42)
        world, pid = _make_world(xp=XP_PER_LEVEL * 3)
        msgs = check_level_up(world, pid)
        player = world.get_component(pid, "Player")
        assert player.level >= 4
        assert len(msgs) >= 3

    def test_xp_to_next_updates(self):
        set_seed(42)
        world, pid = _make_world(xp=XP_PER_LEVEL)
        check_level_up(world, pid)
        player = world.get_component(pid, "Player")
        assert player.xp_to_next == xp_for_level(3)

    def test_con_increase_expands_inventory(self):
        """When CON rises, inventory max_slots = CON bonus + 10."""
        stats = Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=1, wisdom=1, charisma=1,
        )
        world, pid = _make_world(xp=XP_PER_LEVEL, stats=stats)
        set_seed(42)
        old_con = stats.constitution
        check_level_up(world, pid)
        new_stats = world.get_component(pid, "Stats")
        inv = world.get_component(pid, "Inventory")
        # Inventory max_slots should match CON defense (bonus + 10)
        assert inv.max_slots == new_stats.constitution + 10


class TestPickLowestAbilities:
    def test_picks_three_lowest(self):
        stats = Stats(
            strength=5, dexterity=3, constitution=1,
            intelligence=4, wisdom=2, charisma=6,
        )
        picked = _pick_lowest_abilities(stats, count=3)
        assert len(picked) == 3
        assert "constitution" in picked
        assert "wisdom" in picked
        assert "dexterity" in picked

    def test_skips_capped(self):
        stats = Stats(
            strength=MAX_ABILITY_BONUS, dexterity=MAX_ABILITY_BONUS,
            constitution=MAX_ABILITY_BONUS,
            intelligence=1, wisdom=2, charisma=3,
        )
        picked = _pick_lowest_abilities(stats, count=3)
        assert len(picked) == 3
        assert "intelligence" in picked
        assert "wisdom" in picked
        assert "charisma" in picked

    def test_fewer_than_requested_when_all_capped(self):
        stats = Stats(
            strength=MAX_ABILITY_BONUS, dexterity=MAX_ABILITY_BONUS,
            constitution=MAX_ABILITY_BONUS,
            intelligence=MAX_ABILITY_BONUS, wisdom=MAX_ABILITY_BONUS,
            charisma=MAX_ABILITY_BONUS,
        )
        picked = _pick_lowest_abilities(stats, count=3)
        assert len(picked) == 0

    def test_tie_breaks_by_priority(self):
        stats = Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=1, wisdom=1, charisma=1,
        )
        picked = _pick_lowest_abilities(stats, count=3)
        assert len(picked) == 3
        # First three in definition order
        assert picked == ["strength", "dexterity", "constitution"]
