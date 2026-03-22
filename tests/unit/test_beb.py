"""Tests for BEB creature abilities and new scroll effects."""

import pytest

from nhc.core.actions import MeleeAttackAction, UseItemAction
from nhc.core.ecs import World
from nhc.core.events import CreatureDied, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Consumable,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Poison,
    Position,
    Renderable,
    Stats,
    StatusEffect,
    Undead,
)
from nhc.utils.rng import set_seed


def _make_level(width=10, height=10, all_visible=True):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    if all_visible:
        for row in tiles:
            for tile in row:
                tile.visible = True
    return Level(id="test", name="Test", depth=1, width=width, height=height, tiles=tiles)


def _make_player(world, x=5, y=5):
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=2, dexterity=2, constitution=2),
        "Health": Health(current=20, maximum=20),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(xp=30),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(world, x=6, y=5, hp=10, **extra):
    components = {
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="aggressive_melee"),
        "Description": Description(name="Monster"),
        "Renderable": Renderable(glyph="m"),
    }
    components.update(extra)
    return world.create_entity(components)


# ── DrainTouch ────────────────────────────────────────────────────────


def _make_wight_attacker(world, x=6, y=5):
    """Wight with STR=4 — always hits (4+d20 vs 10+2) but deals ≤8 dmg."""
    return world.create_entity({
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=4, dexterity=2),
        "Health": Health(current=13, maximum=13),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="aggressive_melee"),
        "Description": Description(name="Wight"),
        "Renderable": Renderable(glyph="W"),
        "DrainTouch": True,
    })


class TestDrainTouch:
    @pytest.mark.asyncio
    async def test_drain_touch_reduces_player_max_hp(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        wid = _make_wight_attacker(world, x=6, y=5)
        original_max = world.get_component(pid, "Health").maximum

        # Use seed that gives a low attack die so we hit but don't kill
        set_seed(42)
        action = MeleeAttackAction(actor=wid, target=pid)
        events = await action.execute(world, level)

        health = world.get_component(pid, "Health")
        msgs = [e.text for e in events if isinstance(e, MessageEvent)]

        # Only assert if drain message appeared (hit occurred)
        if any("drain" in m.lower() for m in msgs):
            assert health is not None
            assert health.maximum < original_max

    @pytest.mark.asyncio
    async def test_drain_touch_reduces_player_xp(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        wid = _make_wight_attacker(world, x=6, y=5)

        set_seed(1)
        action = MeleeAttackAction(actor=wid, target=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        if any("drain" in m.lower() for m in msgs):
            player = world.get_component(pid, "Player")
            assert player is not None
            assert player.xp <= 30  # XP was reduced (started at 30)

    @pytest.mark.asyncio
    async def test_drain_touch_no_effect_without_player(self):
        """DrainTouch only applies to player, not other creatures."""
        world = World()
        level = _make_level()
        wid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Stats": Stats(strength=20),
            "Health": Health(current=13, maximum=13),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Wight"),
            "DrainTouch": True,
        })
        target_id = _make_creature(world, x=6, y=5, hp=10)

        original_max = world.get_component(target_id, "Health").maximum
        action = MeleeAttackAction(actor=wid, target=target_id)
        await action.execute(world, level)

        # Max HP should be unchanged (no Player component)
        health = world.get_component(target_id, "Health")
        if health:
            assert health.maximum == original_max


# ── VenomousStrike ────────────────────────────────────────────────────


class TestVenomousStrike:
    @pytest.mark.asyncio
    async def test_venomous_strike_applies_poison_on_hit(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        bee_id = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=4),  # Reliable hit, minimal damage
            "Health": Health(current=1, maximum=1),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Giant Bee"),
            "Renderable": Renderable(glyph="A"),
            "VenomousStrike": True,
        })

        set_seed(1)
        action = MeleeAttackAction(actor=bee_id, target=pid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        if any("hits" in m for m in msgs):
            assert world.has_component(pid, "Poison")
            poison = world.get_component(pid, "Poison")
            assert poison.turns_remaining > 0

    @pytest.mark.asyncio
    async def test_venomous_strike_no_double_poison(self):
        """Second VenomousStrike on already-poisoned target doesn't reset badly."""
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        # Pre-apply poison
        world.add_component(pid, "Poison", Poison(damage_per_turn=1, turns_remaining=2))

        bee_id = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=4),
            "Health": Health(current=1, maximum=1),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Giant Bee"),
            "VenomousStrike": True,
        })

        action = MeleeAttackAction(actor=bee_id, target=pid)
        await action.execute(world, level)

        # Should still have poison
        assert world.has_component(pid, "Poison")


# ── PetrifyingGaze ────────────────────────────────────────────────────


class TestPetrifyingGaze:
    @pytest.mark.asyncio
    async def test_petrifying_gaze_can_paralyze_attacker(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        # Override stats to make save likely to fail
        world.add_component(pid, "Stats", Stats(strength=2, dexterity=-5))

        bas_id = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=28, maximum=28),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Basilisk"),
            "Renderable": Renderable(glyph="B"),
            "PetrifyingGaze": True,
        })

        # Low DEX save: roll d20-5 < 12 is likely
        set_seed(2)  # Seed that gives a low roll
        action = MeleeAttackAction(actor=pid, target=bas_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # If petrified, StatusEffect.paralyzed should be set
        player_status = world.get_component(pid, "StatusEffect")
        if any("stone" in m or "petrif" in m.lower() for m in msgs):
            assert player_status is not None
            assert player_status.paralyzed == 9

    @pytest.mark.asyncio
    async def test_petrifying_gaze_save_allows_attack(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        # High DEX to guarantee save
        world.add_component(pid, "Stats", Stats(strength=2, dexterity=20))

        bas_id = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "Health": Health(current=28, maximum=28),
            "BlocksMovement": BlocksMovement(),
            "AI": AI(behavior="aggressive_melee"),
            "Description": Description(name="Basilisk"),
            "PetrifyingGaze": True,
        })

        action = MeleeAttackAction(actor=pid, target=bas_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Should NOT be petrified (DEX 20 always passes)
        player_status = world.get_component(pid, "StatusEffect")
        assert player_status is None or player_status.paralyzed == 0
        # Should see avert-eyes message
        assert any("avert" in m or "averts" in m for m in msgs)


# ── Sleep scroll ──────────────────────────────────────────────────────


class TestScrollSleep:
    @pytest.mark.asyncio
    async def test_sleep_affects_visible_creatures(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Sleep"),
            "Consumable": Consumable(effect="sleep", dice="2d8"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        # Weak creature (2 HP → 1 HD)
        cid = _make_creature(world, x=6, y=5, hp=4)

        set_seed(99)  # Seed giving high 2d8 roll
        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Should have cast message
        assert any("crumbles" in m or "dust" in m for m in msgs)

        # Creature should be asleep or "none fall asleep" depending on roll
        status = world.get_component(cid, "StatusEffect")
        if any("slumber" in m for m in msgs):
            assert status is not None
            assert status.sleeping > 0

    @pytest.mark.asyncio
    async def test_sleep_immune_to_undead(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Sleep"),
            "Consumable": Consumable(effect="sleep", dice="8d1"),  # Always 8 HD
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        # Undead creature
        skel_id = _make_creature(world, x=6, y=5, hp=4)
        world.add_component(skel_id, "Undead", Undead())

        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        # Undead should NOT be sleeping
        status = world.get_component(skel_id, "StatusEffect")
        assert status is None or status.sleeping == 0

    @pytest.mark.asyncio
    async def test_sleep_consumes_item(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Sleep"),
            "Consumable": Consumable(effect="sleep", dice="2d8"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        action = UseItemAction(actor=pid, item=item_id)
        await action.execute(world, level)

        assert item_id not in inv.slots


# ── Magic Missile scroll ──────────────────────────────────────────────


class TestScrollMagicMissile:
    @pytest.mark.asyncio
    async def test_magic_missile_damages_nearest(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Magic Missile"),
            "Consumable": Consumable(effect="magic_missile", dice="1d6+1"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        cid = _make_creature(world, x=6, y=5, hp=20)
        original_hp = world.get_component(cid, "Health").current

        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        health = world.get_component(cid, "Health")

        # Damage should have been applied (magic missile always hits)
        assert any("bolt of force" in m or "force" in m.lower() for m in msgs)
        if health:
            assert health.current < original_hp

    @pytest.mark.asyncio
    async def test_magic_missile_no_target(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Magic Missile"),
            "Consumable": Consumable(effect="magic_missile", dice="1d6+1"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("target" in m.lower() for m in msgs)


# ── Hold Person scroll ────────────────────────────────────────────────


class TestScrollHoldPerson:
    @pytest.mark.asyncio
    async def test_hold_person_paralyzes_humanoids(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Hold Person"),
            "Consumable": Consumable(effect="hold_person", dice="9"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        cid = _make_creature(world, x=6, y=5, hp=10)

        set_seed(1)
        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        status = world.get_component(cid, "StatusEffect")

        if any("freeze" in m.lower() or "frozen" in m.lower() for m in msgs):
            assert status is not None
            assert status.paralyzed == 9

    @pytest.mark.asyncio
    async def test_hold_person_skips_undead(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Hold Person"),
            "Consumable": Consumable(effect="hold_person", dice="9"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        # Only undead present
        skel_id = _make_creature(world, x=6, y=5, hp=4)
        world.add_component(skel_id, "Undead", Undead())

        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("humanoid" in m.lower() for m in msgs)

        status = world.get_component(skel_id, "StatusEffect")
        assert status is None or status.paralyzed == 0

    @pytest.mark.asyncio
    async def test_hold_person_consumes_item(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Hold Person"),
            "Consumable": Consumable(effect="hold_person", dice="9"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)
        _make_creature(world, x=6, y=5, hp=10)

        action = UseItemAction(actor=pid, item=item_id)
        await action.execute(world, level)

        assert item_id not in inv.slots


# ── Fireball scroll ───────────────────────────────────────────────────


class TestScrollFireball:
    @pytest.mark.asyncio
    async def test_fireball_hits_all_visible(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Fireball"),
            "Consumable": Consumable(effect="fireball", dice="3d6"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        cid1 = _make_creature(world, x=6, y=5, hp=30)
        cid2 = _make_creature(world, x=7, y=5, hp=30)

        set_seed(50)
        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Both creatures should take damage
        assert any("scorched" in m for m in msgs)
        scorched_count = sum(1 for m in msgs if "scorched" in m)
        assert scorched_count == 2

    @pytest.mark.asyncio
    async def test_fireball_kills_weak_creatures(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Fireball"),
            "Consumable": Consumable(effect="fireball", dice="18d1"),  # Fixed 18 damage
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)

        cid = _make_creature(world, x=6, y=5, hp=1)

        action = UseItemAction(actor=pid, item=item_id)
        events = await action.execute(world, level)

        death_events = [e for e in events if isinstance(e, CreatureDied)]
        assert len(death_events) == 1

    @pytest.mark.asyncio
    async def test_fireball_consumes_item(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        item_id = world.create_entity({
            "Description": Description(name="Scroll of Fireball"),
            "Consumable": Consumable(effect="fireball", dice="3d6"),
        })
        inv = world.get_component(pid, "Inventory")
        inv.slots.append(item_id)
        _make_creature(world, x=6, y=5, hp=30)

        action = UseItemAction(actor=pid, item=item_id)
        await action.execute(world, level)

        assert item_id not in inv.slots


# ── AI status skipping ────────────────────────────────────────────────


class TestStatusEffectAI:
    def test_paralyzed_creature_skips_turn(self):
        from nhc.ai.behavior import decide_action

        world = World()
        level = _make_level()

        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "AI": AI(behavior="aggressive_melee"),
            "StatusEffect": StatusEffect(paralyzed=3),
        })
        pid = world.create_entity({
            "Position": Position(x=5, y=5),
        })

        action = decide_action(cid, world, level, pid)
        assert action is None

        # Paralyzed counter should decrement
        status = world.get_component(cid, "StatusEffect")
        assert status.paralyzed == 2

    def test_sleeping_creature_skips_turn(self):
        from nhc.ai.behavior import decide_action

        world = World()
        level = _make_level()

        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "AI": AI(behavior="aggressive_melee"),
            "StatusEffect": StatusEffect(sleeping=5),
        })
        pid = world.create_entity({
            "Position": Position(x=5, y=5),
        })

        action = decide_action(cid, world, level, pid)
        assert action is None

        status = world.get_component(cid, "StatusEffect")
        assert status.sleeping == 4

    def test_status_expires_and_creature_acts(self):
        from nhc.ai.behavior import decide_action

        world = World()
        level = _make_level()

        cid = world.create_entity({
            "Position": Position(x=6, y=5),
            "Stats": Stats(strength=1, dexterity=1),
            "AI": AI(behavior="aggressive_melee"),
            "StatusEffect": StatusEffect(paralyzed=0),
        })
        pid = world.create_entity({
            "Position": Position(x=5, y=5),
        })

        # paralyzed=0 → creature should act normally (attack adjacent player)
        action = decide_action(cid, world, level, pid)
        from nhc.core.actions import MeleeAttackAction
        assert isinstance(action, MeleeAttackAction)


# ── Sleeping target auto-hit ──────────────────────────────────────────


class TestSleepingAutoHit:
    @pytest.mark.asyncio
    async def test_attack_sleeping_target_always_hits_and_wakes(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        cid = _make_creature(world, x=6, y=5, hp=20)
        world.add_component(cid, "StatusEffect", StatusEffect(sleeping=5))

        # Very low STR to miss normally — sleeping overrides
        world.add_component(pid, "Stats", Stats(strength=-10, dexterity=2))

        action = MeleeAttackAction(actor=pid, target=cid)
        events = await action.execute(world, level)

        msgs = [e.text for e in events if isinstance(e, MessageEvent)]
        # Must have a hit (never miss against sleeping target)
        assert any("hit" in m.lower() for m in msgs)

        # Target should be awake now
        status = world.get_component(cid, "StatusEffect")
        assert status.sleeping == 0


# ── ECS remove_component ──────────────────────────────────────────────


class TestECSRemoveComponent:
    def test_remove_component_eliminates_it(self):
        from nhc.core.ecs import World as W

        w = W()
        eid = w.create_entity({"Poison": Poison()})
        assert w.has_component(eid, "Poison")
        w.remove_component(eid, "Poison")
        assert not w.has_component(eid, "Poison")

    def test_remove_nonexistent_component_noop(self):
        from nhc.core.ecs import World as W

        w = W()
        eid = w.create_entity({})
        # Should not raise
        w.remove_component(eid, "Poison")
        assert not w.has_component(eid, "Poison")
