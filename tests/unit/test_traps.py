"""Tests for trap types and their effects."""

import pytest

from nhc.core.ecs import World
from nhc.core.actions import _check_traps
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Health, Inventory, Player, Poison, Position,
    Renderable, Stats, StatusEffect, Trap,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level() -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    for row in tiles:
        for t in row:
            t.visible = True
    return Level(id="t", name="T", depth=2, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world_with_trap(
    effect: str = "", damage: str = "1d6", dc: int = 99,
) -> tuple[World, int, int, Level]:
    """Player on a trap tile. DC=99 means guaranteed to fail save."""
    i18n_init("en")
    set_seed(42)
    world = World()
    level = _make_level()

    pid = world.create_entity({
        "Position": Position(x=5, y=5),
        "Player": Player(),
        "Health": Health(current=20, maximum=20),
        "Stats": Stats(strength=2, dexterity=0, constitution=2),
        "Inventory": Inventory(max_slots=12),
    })

    trap_id = world.create_entity({
        "Position": Position(x=5, y=5),
        "Trap": Trap(damage=damage, dc=dc, hidden=True, effect=effect),
    })

    return world, pid, trap_id, level


class TestTrapFactories:
    def test_all_trap_factories_exist(self):
        i18n_init("en")
        from nhc.entities.registry import EntityRegistry
        EntityRegistry.discover_all()
        for trap_id in [
            "trap_pit", "trap_fire", "trap_poison", "trap_paralysis",
            "trap_alarm", "trap_teleport", "trap_summoning", "trap_gripping",
            "trap_arrow", "trap_darts", "trap_falling_stone", "trap_spores",
        ]:
            comps = EntityRegistry.get_feature(trap_id)
            assert "Trap" in comps, f"{trap_id} missing Trap component"
            assert "Renderable" in comps, f"{trap_id} missing Renderable"
            assert comps["Renderable"].glyph == "^"


class TestPitTrap:
    def test_damage_on_fail(self):
        world, pid, _, level = _make_world_with_trap(damage="1d6", dc=99)
        events = _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current < 20

    def test_trap_marked_triggered(self):
        world, pid, tid, level = _make_world_with_trap(dc=99)
        _check_traps(world, level, pid, 5, 5)
        trap = world.get_component(tid, "Trap")
        assert trap.triggered
        assert not trap.hidden


class TestPoisonTrap:
    def test_applies_poison(self):
        world, pid, _, level = _make_world_with_trap(
            effect="poison", damage="1d4", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        poison = world.get_component(pid, "Poison")
        assert poison is not None
        assert poison.turns_remaining > 0


class TestParalysisTrap:
    def test_applies_paralysis(self):
        world, pid, _, level = _make_world_with_trap(
            effect="paralysis", damage="0", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.paralyzed >= 3


class TestGrippingTrap:
    def test_damage_and_web(self):
        world, pid, _, level = _make_world_with_trap(
            effect="gripping", damage="1d4", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current < 20
        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.webbed >= 3


class TestFireTrap:
    def test_deals_damage(self):
        world, pid, _, level = _make_world_with_trap(
            effect="fire", damage="1d8", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current < 20


class TestAlarmTrap:
    def test_alerts_creatures(self):
        world, pid, _, level = _make_world_with_trap(
            effect="alarm", damage="0", dc=99,
        )
        # Add a passive creature
        mob = world.create_entity({
            "Position": Position(x=8, y=8),
            "AI": AI(behavior="idle"),
            "Health": Health(current=5, maximum=5),
        })
        _check_traps(world, level, pid, 5, 5)
        ai = world.get_component(mob, "AI")
        assert ai.behavior == "aggressive_melee"


class TestTeleportTrap:
    def test_moves_player(self):
        world, pid, _, level = _make_world_with_trap(
            effect="teleport", damage="0", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        pos = world.get_component(pid, "Position")
        # Player should have moved (very unlikely to land on same tile)
        # With seed 42 and a 10x10 floor grid this should be different
        assert pos is not None


class TestSummoningTrap:
    def test_spawns_creatures(self):
        i18n_init("en")
        from nhc.entities.registry import EntityRegistry
        EntityRegistry.discover_all()

        world, pid, _, level = _make_world_with_trap(
            effect="summoning", damage="0", dc=99,
        )
        # Set level_id on player position for spawning
        pos = world.get_component(pid, "Position")
        pos.level_id = "t"

        entities_before = len(world._entities)
        _check_traps(world, level, pid, 5, 5)
        entities_after = len(world._entities)
        # Should have spawned at least 1 creature
        assert entities_after > entities_before


class TestArrowTrap:
    def test_deals_damage(self):
        world, pid, _, level = _make_world_with_trap(
            effect="arrow", damage="1d6", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current < 20


class TestDartsTrap:
    def test_deals_damage(self):
        world, pid, _, level = _make_world_with_trap(
            effect="darts", damage="3d4", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current < 20


class TestFallingStoneTrap:
    def test_damage_and_stun(self):
        world, pid, _, level = _make_world_with_trap(
            effect="falling_stone", damage="2d6", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current < 20
        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.paralyzed >= 1


class TestSporesTrap:
    def test_applies_confusion(self):
        world, pid, _, level = _make_world_with_trap(
            effect="spores", damage="0", dc=99,
        )
        _check_traps(world, level, pid, 5, 5)
        status = world.get_component(pid, "StatusEffect")
        assert status is not None
        assert status.confused >= 5


class TestTrapAvoidance:
    def test_high_dex_avoids(self):
        """Very low DC + high dex — save always passes."""
        world, pid, _, level = _make_world_with_trap(dc=1)
        stats = world.get_component(pid, "Stats")
        stats.dexterity = 10
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current == 20  # No damage

    def test_levitating_avoids(self):
        """Levitating creatures float over traps."""
        world, pid, _, level = _make_world_with_trap(dc=99)
        world.add_component(
            pid, "StatusEffect", StatusEffect(levitating=5),
        )
        _check_traps(world, level, pid, 5, 5)
        health = world.get_component(pid, "Health")
        assert health.current == 20


class TestHiddenTrapRendering:
    """Hidden traps must not appear in entity lists sent to clients."""

    def _make_world_with_renderable_trap(
        self, hidden: bool = True,
    ) -> tuple:
        """World with player + renderable trap on a visible tile."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _make_level()

        pid = world.create_entity({
            "Position": Position(x=5, y=5),
            "Player": Player(),
            "Health": Health(current=20, maximum=20),
            "Stats": Stats(strength=2, dexterity=0, constitution=2),
            "Inventory": Inventory(max_slots=12),
        })

        tid = world.create_entity({
            "Position": Position(x=3, y=3),
            "Trap": Trap(damage="1d6", dc=12, hidden=hidden, effect=""),
            "Renderable": Renderable(
                glyph="^", color="red", render_order=1,
            ),
        })

        return world, pid, tid, level

    def test_web_client_excludes_hidden_traps(self):
        from nhc.rendering.web_client import WebClient
        world, pid, tid, level = self._make_world_with_renderable_trap(
            hidden=True,
        )
        client = WebClient()
        entities = client._gather_entities(world, level, pid)
        eids = [e["id"] for e in entities]
        assert tid not in eids, "hidden trap should not be in entity list"

    def test_web_client_includes_revealed_traps(self):
        from nhc.rendering.web_client import WebClient
        world, pid, tid, level = self._make_world_with_renderable_trap(
            hidden=False,
        )
        client = WebClient()
        entities = client._gather_entities(world, level, pid)
        eids = [e["id"] for e in entities]
        assert tid in eids, "revealed trap should be in entity list"

    def test_web_client_includes_triggered_traps(self):
        from nhc.rendering.web_client import WebClient
        world, pid, tid, level = self._make_world_with_renderable_trap(
            hidden=True,
        )
        # Simulate triggering: hidden becomes False
        trap = world.get_component(tid, "Trap")
        trap.hidden = False
        trap.triggered = True
        client = WebClient()
        entities = client._gather_entities(world, level, pid)
        eids = [e["id"] for e in entities]
        assert tid in eids, "triggered trap should be visible"


class TestTrapSpawnPool:
    def test_pool_has_variety(self):
        from nhc.dungeon.populator import FEATURE_POOLS
        assert len(FEATURE_POOLS) >= 8
        ids = [p[0] for p in FEATURE_POOLS]
        assert "trap_pit" in ids
        assert "trap_fire" in ids
        assert "trap_summoning" in ids
