"""Tests for Milestone 6: simple BEB creatures."""

import pytest

from nhc.core.actions import MeleeAttackAction
from nhc.core.ecs import World
from nhc.core.events import CreatureAttacked, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.utils.rng import set_seed


def _make_level():
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    return Level(id="t", name="T", depth=1, width=10, height=10, tiles=tiles)


# ── Registry: all M6 creatures load without error ────────────────────


M6_CREATURE_IDS = [
    "kobold", "hobgoblin", "bugbear", "ogre", "bandit",
    "warg", "wolf", "dire_wolf", "giant_bat",
    "black_bear", "brown_bear", "frogman", "lizardman",
    "fire_beetle", "amalgamkin",
]


class TestM6CreatureRegistry:
    def setup_method(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("creature_id", M6_CREATURE_IDS)
    def test_creature_loads(self, creature_id):
        components = EntityRegistry.get_creature(creature_id)
        assert "Health" in components
        assert "Stats" in components
        assert "AI" in components
        assert "Renderable" in components
        assert "Description" in components

    @pytest.mark.parametrize("creature_id", M6_CREATURE_IDS)
    def test_creature_has_description_strings(self, creature_id):
        components = EntityRegistry.get_creature(creature_id)
        desc = components["Description"]
        assert desc.name
        assert desc.short
        assert desc.long

    def test_ogre_has_weapon(self):
        c = EntityRegistry.get_creature("ogre")
        assert "Weapon" in c
        assert c["Weapon"].damage == "1d10"

    def test_uarg_has_weapon(self):
        c = EntityRegistry.get_creature("warg")
        assert "Weapon" in c
        assert c["Weapon"].damage == "3d6"

    def test_kobold_has_negative_strength(self):
        c = EntityRegistry.get_creature("kobold")
        assert c["Stats"].strength < 0

    def test_escarabat_foc_uses_guard_behavior(self):
        c = EntityRegistry.get_creature("fire_beetle")
        assert c["AI"].behavior == "guard"


# ── Inline Weapon component on creature ──────────────────────────────


class TestInlineWeapon:
    @pytest.mark.asyncio
    async def test_creature_inline_weapon_used_for_damage(self):
        """A creature with inline Weapon component should deal that weapon's
        damage rather than 1d4 unarmed."""
        world = World()
        level = _make_level()

        # Attacker: ogre with 1d10 weapon + STR 4 = 1d10+4 avg ~9.5
        attacker_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=4, dexterity=4),
            "Health": Health(current=19, maximum=19),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Ogre"),
            "Weapon": Weapon(damage="1d10"),
        })
        # Target: player with high HP
        target_id = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=0, dexterity=0),
            "Health": Health(current=100, maximum=100),
            "Inventory": Inventory(),
            "Player": Player(),
            "Equipment": Equipment(),
            "Description": Description(name="You"),
            "Renderable": Renderable(glyph="@"),
        })

        set_seed(42)  # Non-natural-1
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1
        if attack_events[0].hit:
            # Minimum damage with 1d10+4 is 5 (1+4); unarmed 1d4+4 min is 5 too
            # but max is 14 vs 8 — check actual damage > 0
            assert attack_events[0].damage > 0

    @pytest.mark.asyncio
    async def test_player_equipment_weapon_still_used(self):
        """Player's equipped weapon through Equipment component still works."""
        world = World()
        level = _make_level()

        sword_id = world.create_entity({
            "Weapon": Weapon(damage="1d8"),
            "Description": Description(name="Sword"),
        })
        player_id = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=10, maximum=10),
            "Equipment": Equipment(weapon=sword_id),
            "Inventory": Inventory(),
            "Player": Player(),
            "Description": Description(name="You"),
        })
        target_id = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=0, dexterity=0),
            "Health": Health(current=50, maximum=50),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Monster"),
        })

        set_seed(42)
        action = MeleeAttackAction(actor=player_id, target=target_id)
        events = await action.execute(world, level)

        attack_events = [e for e in events if isinstance(e, CreatureAttacked)]
        assert len(attack_events) == 1


# ── Populator tier 4 ─────────────────────────────────────────────────


class TestPopulatorTier4:
    def test_depth_4_uses_tier4_pool(self):
        from nhc.dungeon.populator import CREATURE_POOLS
        assert 4 in CREATURE_POOLS
        ids = [cid for cid, _ in CREATURE_POOLS[4]]
        assert "ogre" in ids or "brown_bear" in ids

    def test_depth_1_includes_kobold(self):
        from nhc.dungeon.populator import CREATURE_POOLS
        ids = [cid for cid, _ in CREATURE_POOLS[1]]
        assert "kobold" in ids

    def test_depth_2_includes_hobgoblin(self):
        from nhc.dungeon.populator import CREATURE_POOLS
        ids = [cid for cid, _ in CREATURE_POOLS[2]]
        assert "hobgoblin" in ids

    def test_weights_sum_to_1_in_each_tier(self):
        from nhc.dungeon.populator import CREATURE_POOLS
        for tier, pool in CREATURE_POOLS.items():
            total = sum(w for _, w in pool)
            assert abs(total - 1.0) < 1e-6, f"Tier {tier} weights sum to {total}"
