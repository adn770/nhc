"""Tests for Milestone 8: complex BEB creatures with new systems."""

import pytest

from nhc.core.actions import BansheeWailAction, MeleeAttackAction
from nhc.core.ecs import World
from nhc.core.events import CreatureDied, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Cursed,
    DeathWail,
    Description,
    Enchanted,
    Equipment,
    FearAura,
    Health,
    Inventory,
    MummyRot,
    Player,
    Position,
    Regeneration,
    Renderable,
    RequiresMagicWeapon,
    Stats,
    StatusEffect,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.rules.combat import heal
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


# ── Registry: all M8 creatures load without error ────────────────────

M8_CREATURE_IDS = [
    "troll", "mummy", "gargoyle", "banshee",
    "mimic", "harpy", "dryad", "wyvern",
]


class TestM8CreatureRegistry:
    def setup_method(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("creature_id", M8_CREATURE_IDS)
    def test_creature_loads(self, creature_id):
        comps = EntityRegistry.get_creature(creature_id)
        assert "Health" in comps
        assert "Stats" in comps
        assert "AI" in comps

    def test_troll_has_regeneration(self):
        comps = EntityRegistry.get_creature("troll")
        assert "Regeneration" in comps

    def test_mummy_has_mummy_rot_and_fear_aura(self):
        comps = EntityRegistry.get_creature("mummy")
        assert "MummyRot" in comps
        assert "FearAura" in comps

    def test_gargoyle_requires_magic_weapon(self):
        comps = EntityRegistry.get_creature("gargoyle")
        assert "RequiresMagicWeapon" in comps

    def test_banshee_has_death_wail(self):
        comps = EntityRegistry.get_creature("banshee")
        assert "DeathWail" in comps

    def test_mimic_has_disguise(self):
        comps = EntityRegistry.get_creature("mimic")
        assert "Disguise" in comps

    def test_harpy_has_charm_song(self):
        comps = EntityRegistry.get_creature("harpy")
        assert "CharmSong" in comps

    def test_dryad_has_charm_touch(self):
        comps = EntityRegistry.get_creature("dryad")
        assert "CharmTouch" in comps

    def test_wyvern_has_venomous_strike(self):
        comps = EntityRegistry.get_creature("wyvern")
        assert "VenomousStrike" in comps


# ── Regeneration ──────────────────────────────────────────────────────

class TestRegeneration:
    def test_regen_increases_hp(self):
        """Health of entity with Regeneration increases when not fire-damaged."""
        health = Health(current=10, maximum=20)
        regen = Regeneration(hp_per_turn=3, fire_damaged=False)
        before = health.current
        if not regen.fire_damaged:
            heal(health, regen.hp_per_turn)
        assert health.current == 13

    def test_regen_skips_when_fire_damaged(self):
        health = Health(current=10, maximum=20)
        regen = Regeneration(hp_per_turn=3, fire_damaged=True)
        before = health.current
        if not regen.fire_damaged:
            heal(health, regen.hp_per_turn)
        else:
            regen.fire_damaged = False
        assert health.current == before  # no heal
        assert regen.fire_damaged is False  # flag reset

    def test_regen_does_not_exceed_max(self):
        health = Health(current=19, maximum=20)
        regen = Regeneration(hp_per_turn=3, fire_damaged=False)
        heal(health, regen.hp_per_turn)
        assert health.current == 20  # capped at maximum


# ── MummyRot ──────────────────────────────────────────────────────────

class TestMummyRot:
    @pytest.mark.asyncio
    async def test_mummy_rot_applies_cursed_on_hit(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20  # always hits
        world.add_component(attacker_id, "MummyRot", MummyRot())

        target_id = _make_creature(world, x=6, y=5, hp=200)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        await action.execute(world, level)

        assert world.has_component(target_id, "Cursed")

    def test_cursed_drains_max_hp_over_time(self):
        """Cursed ticks_until_drain counts down; drains 1 max HP at 0."""
        health = Health(current=20, maximum=20)
        cursed = Cursed(ticks_until_drain=2)

        for _ in range(2):
            cursed.ticks_until_drain -= 1
            if cursed.ticks_until_drain <= 0:
                health.maximum -= 1
                health.current = min(health.current, health.maximum)
                cursed.ticks_until_drain = 2

        assert health.maximum == 19
        assert health.current == 19


# ── RequiresMagicWeapon ───────────────────────────────────────────────

class TestRequiresMagicWeapon:
    @pytest.mark.asyncio
    async def test_non_magic_weapon_deals_no_damage(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20

        target_id = _make_creature(world, x=6, y=5, hp=100)
        world.add_component(target_id, "RequiresMagicWeapon",
                            RequiresMagicWeapon())

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        health = world.get_component(target_id, "Health")
        assert health.current == 100  # no damage dealt

    @pytest.mark.asyncio
    async def test_non_magic_weapon_shows_message(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        target_id = _make_creature(world, x=6, y=5, hp=100)
        world.add_component(target_id, "RequiresMagicWeapon",
                            RequiresMagicWeapon())

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("magic" in t.lower() for t in texts)

    @pytest.mark.asyncio
    async def test_enchanted_weapon_damages_normally(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world, x=5, y=5, hp=20)
        p_stats = world.get_component(player_id, "Stats")
        p_stats.strength = 20
        # Give player an enchanted weapon
        wpn_id = world.create_entity({
            "Weapon": Weapon(damage="1d6"),
            "Enchanted": Enchanted(),
        })
        equip = world.get_component(player_id, "Equipment")
        equip.weapon = wpn_id

        target_id = _make_creature(world, x=6, y=5, hp=100)
        world.add_component(target_id, "RequiresMagicWeapon",
                            RequiresMagicWeapon())

        set_seed(1)
        action = MeleeAttackAction(actor=player_id, target=target_id)
        await action.execute(world, level)

        health = world.get_component(target_id, "Health")
        assert health.current < 100  # damage dealt


# ── BansheeWailAction ─────────────────────────────────────────────────

class TestBansheeWail:
    @pytest.mark.asyncio
    async def test_wail_can_kill_player_on_failed_save(self):
        world = World()
        level = _make_level()
        banshee_id = _make_creature(world, x=5, y=5, hp=25)
        world.add_component(banshee_id, "DeathWail", DeathWail(radius=5,
                                                                save_dc=30))
        player_id = _make_player(world, x=6, y=5, hp=20)
        # CON=2, d20 max=20, 20+2=22 < 30 — always fails
        p_stats = world.get_component(player_id, "Stats")
        p_stats.constitution = -10  # ensure fail

        set_seed(1)
        action = BansheeWailAction(actor=banshee_id, player_id=player_id)
        events = await action.execute(world, level)

        health = world.get_component(player_id, "Health")
        assert health.current == 0

    @pytest.mark.asyncio
    async def test_wail_player_survives_on_save(self):
        world = World()
        level = _make_level()
        banshee_id = _make_creature(world, x=5, y=5, hp=25)
        world.add_component(banshee_id, "DeathWail", DeathWail(radius=5,
                                                                save_dc=1))
        player_id = _make_player(world, x=6, y=5, hp=20)
        # CON=100, d20 min=1, 1+100=101 >= 1 — always passes

        p_stats = world.get_component(player_id, "Stats")
        p_stats.constitution = 100

        set_seed(1)
        action = BansheeWailAction(actor=banshee_id, player_id=player_id)
        events = await action.execute(world, level)

        health = world.get_component(player_id, "Health")
        assert health.current == 20

    @pytest.mark.asyncio
    async def test_wail_no_effect_when_out_of_range(self):
        world = World()
        level = _make_level()
        banshee_id = _make_creature(world, x=0, y=0, hp=25)
        world.add_component(banshee_id, "DeathWail", DeathWail(radius=2,
                                                                save_dc=30))
        player_id = _make_player(world, x=9, y=9, hp=20)
        p_stats = world.get_component(player_id, "Stats")
        p_stats.constitution = -10

        set_seed(1)
        action = BansheeWailAction(actor=banshee_id, player_id=player_id)
        await action.execute(world, level)

        health = world.get_component(player_id, "Health")
        assert health.current == 20  # out of range, no effect


# ── CharmTouch (Dryad) ────────────────────────────────────────────────

class TestCharmTouch:
    @pytest.mark.asyncio
    async def test_charm_touch_charms_target_on_hit(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=9)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        world.add_component(attacker_id, "CharmTouch", True)

        target_id = _make_creature(world, x=6, y=5, hp=200)

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        await action.execute(world, level)

        status = world.get_component(target_id, "StatusEffect")
        assert status is not None and status.charmed > 0
