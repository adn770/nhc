"""Tests for ring passive effects and the ring drop bug fix."""

from __future__ import annotations

import pytest

from nhc.core import game_ticks
from nhc.core.actions import DropAction
from nhc.core.actions._helpers import has_ring_effect
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Ring,
    Stats,
    StatusEffect,
    Trap,
)
from nhc.i18n import init as i18n_init


# ── Helpers ────────────────────────────────────────────────────────

def _make_world():
    i18n_init("en")
    world = World()
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    level = Level(id="t", name="T", depth=1, width=10, height=10,
                  tiles=tiles, rooms=[], corridors=[], entities=[])
    pid = world.create_entity({
        "Position": Position(x=5, y=5, level_id="t"),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=8, maximum=10),
        "Inventory": Inventory(max_slots=12),
        "Player": Player(),
        "Equipment": Equipment(),
        "Description": Description(name="Hero"),
    })
    return world, level, pid


def _equip_ring(world, pid, effect, slot="ring_left"):
    ring_id = world.create_entity({
        "Ring": Ring(effect=effect),
        "Description": Description(name=f"Ring of {effect}"),
    })
    world.get_component(pid, "Inventory").slots.append(ring_id)
    setattr(world.get_component(pid, "Equipment"), slot, ring_id)
    return ring_id


class FakeRenderer:
    def __init__(self):
        self.messages = []

    def add_message(self, text):
        self.messages.append(text)


class FakeGame:
    """Minimal Game stub for tick_rings testing."""

    def __init__(self, world, level, player_id, turn=0):
        self.world = world
        self.level = level
        self.player_id = player_id
        self.turn = turn
        self.renderer = FakeRenderer()


# ── has_ring_effect helper ─────────────────────────────────────────

class TestHasRingEffect:
    def test_returns_true_when_equipped(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "mending")
        assert has_ring_effect(w, pid, "mending")

    def test_returns_false_when_not_equipped(self):
        w, l, pid = _make_world()
        assert not has_ring_effect(w, pid, "mending")

    def test_returns_false_for_wrong_effect(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "detection")
        assert not has_ring_effect(w, pid, "mending")

    def test_works_in_right_slot(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "accuracy", slot="ring_right")
        assert has_ring_effect(w, pid, "accuracy")


# ── Mending ring ───────────────────────────────────────────────────

class TestMendingRing:
    def test_heals_on_turn_5(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "mending")
        game = FakeGame(w, l, pid, turn=5)
        health = w.get_component(pid, "Health")
        assert health.current == 8

        game_ticks.tick_rings(game)

        assert health.current == 9

    def test_no_heal_at_max(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "mending")
        health = w.get_component(pid, "Health")
        health.current = health.maximum
        game = FakeGame(w, l, pid, turn=5)

        game_ticks.tick_rings(game)

        assert health.current == health.maximum

    def test_no_heal_on_non_multiple_of_5(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "mending")
        game = FakeGame(w, l, pid, turn=3)
        health = w.get_component(pid, "Health")
        before = health.current

        game_ticks.tick_rings(game)

        assert health.current == before

    def test_heals_from_right_slot(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "mending", slot="ring_right")
        game = FakeGame(w, l, pid, turn=10)
        health = w.get_component(pid, "Health")

        game_ticks.tick_rings(game)

        assert health.current == 9


# ── Detection ring ─────────────────────────────────────────────────

class TestDetectionRing:
    def test_reveals_secret_doors(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "detection")
        l.tiles[3][3].feature = "door_secret"
        l.tiles[3][3].visible = True
        game = FakeGame(w, l, pid)

        game_ticks.tick_rings(game)

        assert l.tiles[3][3].feature == "door_closed"

    def test_reveals_hidden_traps(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "detection")
        trap_id = w.create_entity({
            "Trap": Trap(hidden=True),
            "Position": Position(x=4, y=4, level_id="t"),
        })
        l.tiles[4][4].visible = True
        game = FakeGame(w, l, pid)

        game_ticks.tick_rings(game)

        trap = w.get_component(trap_id, "Trap")
        assert not trap.hidden

    def test_ignores_non_visible_tiles(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "detection")
        l.tiles[3][3].feature = "door_secret"
        l.tiles[3][3].visible = False
        game = FakeGame(w, l, pid)

        game_ticks.tick_rings(game)

        assert l.tiles[3][3].feature == "door_secret"


# ── Haste ring ─────────────────────────────────────────────────────

class TestHasteRing:
    def test_sets_hasted_status(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "haste")
        game = FakeGame(w, l, pid)

        game_ticks.tick_rings(game)

        status = w.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.hasted == 1

    def test_maintains_hasted_on_existing_status(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "haste")
        w.add_component(pid, "StatusEffect", StatusEffect(hasted=0))
        game = FakeGame(w, l, pid)

        game_ticks.tick_rings(game)

        assert w.get_component(pid, "StatusEffect").hasted == 1


# ── Ring drop bug fix ──────────────────────────────────────────────

class TestRingDropUnequips:
    @pytest.mark.asyncio
    async def test_drop_unequips_ring_left(self):
        w, l, pid = _make_world()
        ring_id = _equip_ring(w, pid, "mending")
        equip = w.get_component(pid, "Equipment")
        assert equip.ring_left == ring_id

        action = DropAction(actor=pid, item=ring_id)
        assert await action.validate(w, l)
        await action.execute(w, l)

        assert equip.ring_left is None

    @pytest.mark.asyncio
    async def test_drop_unequips_ring_right(self):
        w, l, pid = _make_world()
        ring_id = _equip_ring(w, pid, "detection", slot="ring_right")
        equip = w.get_component(pid, "Equipment")
        assert equip.ring_right == ring_id

        action = DropAction(actor=pid, item=ring_id)
        assert await action.validate(w, l)
        await action.execute(w, l)

        assert equip.ring_right is None


# ── Shadows ring ───────────────────────────────────────────────────

class TestShadowsRing:
    def test_has_ring_effect_shadows(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "shadows")
        assert has_ring_effect(w, pid, "shadows")


# ── Elements ring ──────────────────────────────────────────────────

class TestElementsRing:
    def test_has_ring_effect_elements(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "elements")
        assert has_ring_effect(w, pid, "elements")


# ── Accuracy ring ──────────────────────────────────────────────────

class TestAccuracyRing:
    def test_has_ring_effect_accuracy(self):
        w, l, pid = _make_world()
        _equip_ring(w, pid, "accuracy")
        assert has_ring_effect(w, pid, "accuracy")
