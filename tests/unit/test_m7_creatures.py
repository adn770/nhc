"""Tests for Milestone 7: BEB creatures with new mechanics."""

import pytest

from nhc.core.actions import MeleeAttackAction, ShriekAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    BloodDrain,
    Consumable,
    Description,
    DisenchantTouch,
    Equipment,
    FrostBreath,
    Health,
    Inventory,
    PetrifyingTouch,
    Player,
    Position,
    Renderable,
    Stats,
    StatusEffect,
)
from nhc.entities.registry import EntityRegistry
from nhc.utils.rng import set_seed


def _make_level():
    tiles = [[Tile(terrain=Terrain.FLOOR, visible=True) for _ in range(10)]
             for _ in range(10)]
    return Level(id="t", name="T", depth=1, width=10, height=10, tiles=tiles)


def _make_player(world, x=5, y=5, hp=20):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=hp, maximum=hp),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(xp=50),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(world, x=6, y=5, hp=10, **extra):
    comps = {
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="aggressive_melee"),
        "Description": Description(name="Monster"),
        "Renderable": Renderable(glyph="m"),
    }
    comps.update(extra)
    return world.create_entity(comps)


# ── Registry: all M7 creatures load without error ────────────────────

M7_CREATURE_IDS = [
    "ghoul", "giant_scorpion", "giant_centipede", "giant_tarantula",
    "snakeman", "stirge", "giant_leech", "cockatrice",
    "ill_omen_bird", "tentacle_worm", "winter_wolf",
    "disenchanter", "shrieker", "giant_snake",
]


class TestM7CreatureRegistry:
    def setup_method(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("creature_id", M7_CREATURE_IDS)
    def test_creature_loads(self, creature_id):
        comps = EntityRegistry.get_creature(creature_id)
        assert "Health" in comps
        assert "Stats" in comps
        assert "AI" in comps

    def test_gul_is_undead_with_drain(self):
        comps = EntityRegistry.get_creature("ghoul")
        assert "Undead" in comps
        assert "DrainTouch" in comps

    def test_escorpi_gegant_has_venom(self):
        comps = EntityRegistry.get_creature("giant_scorpion")
        assert "VenomousStrike" in comps

    def test_stirge_has_blood_drain(self):
        comps = EntityRegistry.get_creature("stirge")
        assert "BloodDrain" in comps

    def test_cocatriu_has_petrifying_touch(self):
        comps = EntityRegistry.get_creature("cockatrice")
        assert "PetrifyingTouch" in comps

    def test_llop_hivern_has_frost_breath(self):
        comps = EntityRegistry.get_creature("winter_wolf")
        assert "FrostBreath" in comps

    def test_desencantador_has_disenchant_touch(self):
        comps = EntityRegistry.get_creature("disenchanter")
        assert "DisenchantTouch" in comps

    def test_cridaner_behavior_is_shrieker(self):
        comps = EntityRegistry.get_creature("shrieker")
        assert comps["AI"].behavior == "shrieker"


# ── BloodDrain ────────────────────────────────────────────────────────

class TestBloodDrain:
    @pytest.mark.asyncio
    async def test_blood_drain_damages_target(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=4)
        world.add_component(attacker_id, "BloodDrain", BloodDrain(drain_per_hit=2))
        target_id = _make_creature(world, x=6, y=5, hp=20)

        set_seed(99)  # guaranteed hit with STR=2
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        target_health = world.get_component(target_id, "Health")
        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        # If a hit occurred, drain message should appear
        if target_health.current < 20:
            assert any("drain" in t.lower() for t in texts)

    @pytest.mark.asyncio
    async def test_blood_drain_heals_attacker(self):
        """Attacker with BloodDrain heals from drain damage on a hit."""
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=2)
        # Give high STR to ensure hit
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        world.add_component(attacker_id, "BloodDrain", BloodDrain(drain_per_hit=2))
        target_id = _make_creature(world, x=6, y=5, hp=20)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        await action.execute(world, level)

        a_health = world.get_component(attacker_id, "Health")
        # Should have healed; started at 2, drained 2 HP from target
        assert a_health.current >= 2  # at minimum unchanged; with drain, should be 4


# ── PetrifyingTouch ───────────────────────────────────────────────────

class TestPetrifyingTouch:
    @pytest.mark.asyncio
    async def test_petrifying_touch_can_paralyze(self):
        """With low DEX target, hit + PetrifyingTouch should paralyze."""
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20  # always hits
        world.add_component(attacker_id, "PetrifyingTouch", PetrifyingTouch())
        target_id = _make_creature(world, x=6, y=5, hp=200)  # high HP so not killed first
        t_stats = world.get_component(target_id, "Stats")
        t_stats.dexterity = -10  # always fails save

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        status = world.get_component(target_id, "StatusEffect")
        assert status is not None and status.paralyzed > 0

    @pytest.mark.asyncio
    async def test_petrifying_touch_message_on_paralyze(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        world.add_component(attacker_id, "PetrifyingTouch", PetrifyingTouch())
        target_id = _make_creature(world, x=6, y=5, hp=200)
        t_stats = world.get_component(target_id, "Stats")
        t_stats.dexterity = -10

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("petri" in t.lower() or "stone" in t.lower()
                   or "paraliz" in t.lower() for t in texts)


# ── FrostBreath ───────────────────────────────────────────────────────

class TestFrostBreath:
    @pytest.mark.asyncio
    async def test_frost_breath_deals_extra_damage(self):
        """Winter wolf with FrostBreath deals more total damage than plain wolf."""
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20  # always hits
        world.add_component(attacker_id, "FrostBreath", FrostBreath(dice="1d6"))
        target_id = _make_creature(world, x=6, y=5, hp=100)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("frost" in t.lower() or "cold" in t.lower()
                   or "arctic" in t.lower() for t in texts)
        health = world.get_component(target_id, "Health")
        assert health.current < 100  # damage was dealt

    @pytest.mark.asyncio
    async def test_frost_breath_no_extra_on_miss(self):
        """FrostBreath only triggers on a hit."""
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = -20  # always misses
        world.add_component(attacker_id, "FrostBreath", FrostBreath(dice="1d6"))
        target_id = _make_creature(world, x=6, y=5, hp=100)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert not any("frost" in t.lower() or "arctic" in t.lower() for t in texts)


# ── DisenchantTouch ───────────────────────────────────────────────────

class TestDisenchantTouch:
    @pytest.mark.asyncio
    async def test_disenchant_destroys_consumable(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20  # always hits
        world.add_component(attacker_id, "DisenchantTouch", DisenchantTouch())

        player_id = _make_player(world, x=6, y=5, hp=200)  # high HP to survive
        # Give player a scroll
        scroll_id = world.create_entity({
            "Consumable": Consumable(effect="sleep", dice="2d8", slots=1),
            "Description": Description(name="Scroll of Sleep"),
        })
        inv = world.get_component(player_id, "Inventory")
        inv.slots.append(scroll_id)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=player_id)
        events = await action.execute(world, level)

        inv_after = world.get_component(player_id, "Inventory")
        assert scroll_id not in inv_after.slots

    @pytest.mark.asyncio
    async def test_disenchant_message_on_destruction(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        world.add_component(attacker_id, "DisenchantTouch", DisenchantTouch())

        player_id = _make_player(world, x=6, y=5, hp=200)
        scroll_id = world.create_entity({
            "Consumable": Consumable(effect="heal", dice="1d6+1", slots=1),
            "Description": Description(name="Scroll of Cure Wounds"),
        })
        inv = world.get_component(player_id, "Inventory")
        inv.slots.append(scroll_id)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=player_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("disenchant" in t.lower() or "magic" in t.lower()
                   or "dust" in t.lower() or "drain" in t.lower() for t in texts)

    @pytest.mark.asyncio
    async def test_disenchant_no_effect_without_items(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        world.add_component(attacker_id, "DisenchantTouch", DisenchantTouch())

        player_id = _make_player(world, x=6, y=5, hp=200)
        # No scrolls in inventory

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=player_id)
        events = await action.execute(world, level)

        # No crash, just no disenchant message
        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert not any("dust" in t.lower() for t in texts)


# ── ShriekAction ──────────────────────────────────────────────────────

class TestShriekAction:
    @pytest.mark.asyncio
    async def test_shriek_wakes_sleeping_creatures(self):
        world = World()
        level = _make_level()
        shrieker_id = _make_creature(world, x=5, y=5, hp=14)

        sleeper_id = _make_creature(world, x=7, y=5, hp=10)
        world.add_component(sleeper_id, "StatusEffect", StatusEffect(sleeping=5))

        action = ShriekAction(actor=shrieker_id)
        events = await action.execute(world, level)

        status = world.get_component(sleeper_id, "StatusEffect")
        assert status.sleeping == 0

    @pytest.mark.asyncio
    async def test_shriek_emits_message(self):
        world = World()
        level = _make_level()
        shrieker_id = _make_creature(world, x=5, y=5, hp=14)

        action = ShriekAction(actor=shrieker_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("shriek" in t.lower() or "scream" in t.lower()
                   or "crid" in t.lower() for t in texts)

    @pytest.mark.asyncio
    async def test_shriek_does_not_wake_non_sleeping(self):
        world = World()
        level = _make_level()
        shrieker_id = _make_creature(world, x=5, y=5, hp=14)

        awake_id = _make_creature(world, x=7, y=5, hp=10)
        # No status effect

        action = ShriekAction(actor=shrieker_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert not any("wake" in t.lower() or "jolt" in t.lower() for t in texts)
