"""Tests for Milestone 9: new scroll effects and M9 combat modifiers."""

import pytest

from nhc.core.actions import MeleeAttackAction, UseItemAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent
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
    Position,
    Renderable,
    Stats,
    StatusEffect,
)
from nhc.entities.registry import EntityRegistry
from nhc.utils.rng import set_seed, set_seed as _ss


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
        "Player": Player(xp=30),
        "Description": Description(name="You"),
        "Equipment": Equipment(),
        "Renderable": Renderable(glyph="@"),
    })


def _make_creature(world, x=6, y=5, hp=10, **extra):
    comps = {
        "Position": Position(x=x, y=y),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=hp, maximum=hp),
        "BlocksMovement": BlocksMovement(),
        "AI": AI(behavior="aggressive_melee"),
        "Description": Description(name="Monster"),
        "Renderable": Renderable(glyph="m"),
    }
    comps.update(extra)
    return world.create_entity(comps)


def _add_item(world, player_id, effect: str, dice: str) -> int:
    item_id = world.create_entity({
        "Consumable": Consumable(effect=effect, dice=dice, slots=1),
        "Description": Description(name="Scroll"),
    })
    inv = world.get_component(player_id, "Inventory")
    inv.slots.append(item_id)
    return item_id


# ── Registry: all M9 scrolls load without error ──────────────────────

M9_SCROLL_IDS = [
    "scroll_web", "scroll_charm_person", "scroll_bless",
    "scroll_mirror_image", "scroll_invisibility",
    "scroll_haste", "scroll_cure_wounds", "scroll_protection_evil",
]


class TestM9ScrollRegistry:
    def setup_method(self):
        EntityRegistry.discover_all()

    @pytest.mark.parametrize("scroll_id", M9_SCROLL_IDS)
    def test_scroll_loads(self, scroll_id):
        comps = EntityRegistry.get_item(scroll_id)
        assert "Consumable" in comps
        assert "Renderable" in comps
        assert "Description" in comps

    @pytest.mark.parametrize("scroll_id", M9_SCROLL_IDS)
    def test_scroll_has_effect(self, scroll_id):
        comps = EntityRegistry.get_item(scroll_id)
        assert comps["Consumable"].effect


# ── scroll_web ────────────────────────────────────────────────────────

class TestScrollWeb:
    @pytest.mark.asyncio
    async def test_web_immobilizes_creatures(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        c1 = _make_creature(world, x=6, y=5)
        c2 = _make_creature(world, x=7, y=5)
        item_id = _add_item(world, player_id, "web", "1d4+1")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        events = await action.execute(world, level)

        s1 = world.get_component(c1, "StatusEffect")
        s2 = world.get_component(c2, "StatusEffect")
        assert s1 is not None and s1.webbed > 0
        assert s2 is not None and s2.webbed > 0

    @pytest.mark.asyncio
    async def test_web_no_target_message(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "web", "1d4+1")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("no" in t.lower() or "nothing" in t.lower()
                   or "target" in t.lower() for t in texts)


# ── scroll_charm_person ───────────────────────────────────────────────

class TestScrollCharmPerson:
    @pytest.mark.asyncio
    async def test_charm_sets_charmed_status(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        c = _make_creature(world, x=6, y=5)
        item_id = _add_item(world, player_id, "charm_person", "9")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(c, "StatusEffect")
        assert status is not None and status.charmed > 0

    @pytest.mark.asyncio
    async def test_charm_duration_equals_dice(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        c = _make_creature(world, x=6, y=5)
        item_id = _add_item(world, player_id, "charm_person", "9")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(c, "StatusEffect")
        assert status.charmed == 9


# ── scroll_bless ──────────────────────────────────────────────────────

class TestScrollBless:
    @pytest.mark.asyncio
    async def test_bless_sets_blessed_on_player(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "bless", "6")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        assert status is not None and status.blessed == 6

    @pytest.mark.asyncio
    async def test_bless_overwrites_existing(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        world.add_component(player_id, "StatusEffect", StatusEffect(blessed=10))
        item_id = _add_item(world, player_id, "bless", "6")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        assert status.blessed == 6


# ── scroll_mirror_image ───────────────────────────────────────────────

class TestScrollMirrorImage:
    @pytest.mark.asyncio
    async def test_mirror_image_sets_images(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "mirror_image", "1d4")

        set_seed(42)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        assert status is not None
        assert 1 <= status.mirror_images <= 4

    @pytest.mark.asyncio
    async def test_mirror_image_message_shows_count(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "mirror_image", "1d4")

        set_seed(42)
        action = UseItemAction(actor=player_id, item=item_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        status = world.get_component(player_id, "StatusEffect")
        assert any(str(status.mirror_images) in t for t in texts)


# ── scroll_invisibility ───────────────────────────────────────────────

class TestScrollInvisibility:
    @pytest.mark.asyncio
    async def test_invisibility_sets_status(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "invisibility", "6")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        assert status is not None and status.invisible == 6


# ── scroll_haste ──────────────────────────────────────────────────────

class TestScrollHaste:
    @pytest.mark.asyncio
    async def test_haste_sets_status(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "haste", "3")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        assert status is not None and status.hasted == 3


# ── scroll_cure_wounds ────────────────────────────────────────────────

class TestScrollCureWounds:
    @pytest.mark.asyncio
    async def test_cure_wounds_heals_player(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world, hp=20)
        health = world.get_component(player_id, "Health")
        health.current = 10
        item_id = _add_item(world, player_id, "heal", "1d6+1")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        health = world.get_component(player_id, "Health")
        assert health.current > 10

    @pytest.mark.asyncio
    async def test_cure_wounds_does_not_exceed_max(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world, hp=20)
        item_id = _add_item(world, player_id, "heal", "1d6+1")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        health = world.get_component(player_id, "Health")
        assert health.current <= health.maximum


# ── scroll_protection_evil ────────────────────────────────────────────

class TestScrollProtectionEvil:
    @pytest.mark.asyncio
    async def test_protection_evil_sets_protected(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world)
        item_id = _add_item(world, player_id, "protection_evil", "12")

        set_seed(1)
        action = UseItemAction(actor=player_id, item=item_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        assert status is not None and status.protected == 12


# ── M9 combat modifiers ───────────────────────────────────────────────

class TestInvisibility:
    @pytest.mark.asyncio
    async def test_invisible_target_causes_miss(self):
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        target_id = _make_creature(world, x=6, y=5, hp=20)
        world.add_component(target_id, "StatusEffect", StatusEffect(invisible=3))

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        assert any("invisible" in t.lower() for t in texts)
        health = world.get_component(target_id, "Health")
        assert health.current == 20  # no damage

    @pytest.mark.asyncio
    async def test_attacking_while_invisible_breaks_invisibility(self):
        world = World()
        level = _make_level()
        player_id = _make_player(world, x=5, y=5)
        world.add_component(player_id, "StatusEffect", StatusEffect(invisible=3))
        target_id = _make_creature(world, x=6, y=5, hp=100)

        set_seed(99)
        action = MeleeAttackAction(actor=player_id, target=target_id)
        await action.execute(world, level)

        status = world.get_component(player_id, "StatusEffect")
        # invisible is cleared on a hit
        assert status is None or status.invisible == 0


class TestMirrorImage:
    @pytest.mark.asyncio
    async def test_mirror_image_protects_hp(self):
        """With mirror images active, a hit is absorbed — real HP is never reduced."""
        world = World()
        level = _make_level()
        # Attacker has very high STR to guarantee a hit roll succeeds
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20
        target_id = _make_creature(world, x=6, y=5, hp=20)
        world.add_component(target_id, "StatusEffect", StatusEffect(mirror_images=3))

        # Run several attacks; with STR=20, at least one should be a hit attempt
        for seed in range(10):
            set_seed(seed)
            w2 = World()
            att = _make_creature(w2, x=5, y=5, hp=20)
            s = w2.get_component(att, "Stats")
            s.strength = 20
            tgt = _make_creature(w2, x=6, y=5, hp=20)
            w2.add_component(tgt, "StatusEffect", StatusEffect(mirror_images=1))
            action = MeleeAttackAction(actor=att, target=tgt)
            events = await action.execute(w2, level)
            health = w2.get_component(tgt, "Health")
            # HP must not decrease: either miss or image absorbed
            assert health.current == 20

    @pytest.mark.asyncio
    async def test_mirror_image_decrements_count(self):
        """High-STR attacker always hits; mirror image absorbs and decrements."""
        world = World()
        level = _make_level()
        attacker_id = _make_creature(world, x=5, y=5, hp=20)
        a_stats = world.get_component(attacker_id, "Stats")
        a_stats.strength = 20  # guaranteed hit
        target_id = _make_creature(world, x=6, y=5, hp=20)
        world.add_component(target_id, "StatusEffect",
                            StatusEffect(mirror_images=2))

        set_seed(1)
        action = MeleeAttackAction(actor=attacker_id, target=target_id)
        events = await action.execute(world, level)

        texts = [e.text for e in events if isinstance(e, MessageEvent)]
        status = world.get_component(target_id, "StatusEffect")
        assert any("image" in t.lower() or "mirror" in t.lower()
                   or "shatters" in t.lower() for t in texts)
        assert status.mirror_images == 1


class TestBlessedCombat:
    @pytest.mark.asyncio
    async def test_blessed_attacker_bonus_damage(self):
        """Blessed attacker deals +1 damage on a hit."""
        world = World()
        level = _make_level()
        player_id = _make_player(world, x=5, y=5)
        # Give strong stats to ensure hits
        s = world.get_component(player_id, "Stats")
        s.strength = 10
        target_id = _make_creature(world, x=6, y=5, hp=100)
        world.add_component(player_id, "StatusEffect", StatusEffect(blessed=5))

        # Run many attacks and check average damage is higher
        total_blessed = 0
        hits_blessed = 0
        for seed in range(50, 100):
            w2 = World()
            p2 = _make_player(w2, x=5, y=5)
            st = w2.get_component(p2, "Stats")
            st.strength = 10
            t2 = _make_creature(w2, x=6, y=5, hp=100)
            w2.add_component(p2, "StatusEffect", StatusEffect(blessed=5))
            _ss(seed)
            ev = await MeleeAttackAction(actor=p2, target=t2).execute(w2, level)
            h = w2.get_component(t2, "Health")
            dmg = 100 - h.current
            if dmg > 0:
                total_blessed += dmg
                hits_blessed += 1

        total_unblessed = 0
        hits_unblessed = 0
        for seed in range(50, 100):
            w3 = World()
            p3 = _make_player(w3, x=5, y=5)
            st3 = w3.get_component(p3, "Stats")
            st3.strength = 10
            t3 = _make_creature(w3, x=6, y=5, hp=100)
            _ss(seed)
            ev = await MeleeAttackAction(actor=p3, target=t3).execute(w3, level)
            h3 = w3.get_component(t3, "Health")
            dmg3 = 100 - h3.current
            if dmg3 > 0:
                total_unblessed += dmg3
                hits_unblessed += 1

        if hits_blessed > 0 and hits_unblessed > 0:
            avg_blessed = total_blessed / hits_blessed
            avg_unblessed = total_unblessed / hits_unblessed
            assert avg_blessed > avg_unblessed
