"""Tests for henchman AI avoiding visible (unhidden) traps."""

import pytest

from nhc.ai.henchman_ai import (
    _has_visible_trap,
    decide_henchman_action,
    decide_unhired_wander_action,
)
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Room, Rect, Terrain, Tile
from nhc.entities.components import (
    AI, BlocksMovement, Health, Henchman, Inventory,
    Player, Position, Renderable, Stats, Trap,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level(width: int = 10, height: int = 10) -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(width)]
             for _ in range(height)]
    for row in tiles:
        for t in row:
            t.visible = True
    room = Room(id="r0", rect=Rect(0, 0, width, height))
    return Level(
        id="t", name="T", depth=1, width=width, height=height,
        tiles=tiles, rooms=[room], corridors=[], entities=[],
    )


def _make_henchman(
    world: World, x: int, y: int, *, hired: bool = True,
) -> int:
    comps = {
        "Position": Position(x=x, y=y, level_id="t"),
        "Renderable": Renderable(glyph="@", color="cyan"),
        "Health": Health(current=20, maximum=20),
        "Stats": Stats(dexterity=2),
        "Henchman": Henchman(hired=hired),
        "AI": AI(behavior="henchman"),
        "Inventory": Inventory(max_slots=5),
    }
    return world.create_entity(comps)


def _make_player(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Renderable": Renderable(glyph="@", color="white"),
        "Health": Health(current=20, maximum=20),
        "Stats": Stats(),
        "Player": Player(),
        "BlocksMovement": BlocksMovement(),
        "Inventory": Inventory(max_slots=10),
    })


def _place_trap(
    world: World, x: int, y: int, *, hidden: bool = False,
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Renderable": Renderable(glyph="^", color="red"),
        "Trap": Trap(effect="fire", hidden=hidden, dc=12),
    })


class TestHasVisibleTrap:
    def test_no_trap(self):
        world = World()
        assert _has_visible_trap(world, 3, 4) is False

    def test_hidden_trap_not_detected(self):
        world = World()
        _place_trap(world, 3, 4, hidden=True)
        assert _has_visible_trap(world, 3, 4) is False

    def test_visible_trap_detected(self):
        world = World()
        _place_trap(world, 3, 4, hidden=False)
        assert _has_visible_trap(world, 3, 4) is True

    def test_triggered_trap_ignored(self):
        """Already-triggered traps are not dangerous."""
        world = World()
        eid = _place_trap(world, 3, 4, hidden=False)
        trap = world.get_component(eid, "Trap")
        trap.triggered = True
        assert _has_visible_trap(world, 3, 4) is False


class TestHiredHenchmanAvoidsTraps:
    def test_wander_avoids_visible_trap(self):
        """Hired henchman wandering in a room skips trap tiles."""
        i18n_init("en")
        world = World()
        level = _make_level(5, 5)
        pid = _make_player(world, 2, 2)
        hid = _make_henchman(world, 2, 3)

        # Place visible traps on all adjacent tiles except (1, 3)
        for dx, dy in [(-1, -1), (0, -1), (1, -1),
                       (1, 0), (1, 1), (0, 1), (-1, 1)]:
            _place_trap(world, 2 + dx, 3 + dy, hidden=False)

        # Only (1, 3) is trap-free and not the player tile (2,2)
        # Run many seeds to confirm the henchman never steps onto
        # a trap tile when a safe option exists
        for seed in range(50):
            set_seed(seed)
            action = decide_henchman_action(hid, world, level, pid)
            if action is None:
                continue
            if hasattr(action, "dx"):
                nx = 2 + action.dx
                ny = 3 + action.dy
                assert not _has_visible_trap(world, nx, ny), (
                    f"seed={seed}: henchman stepped onto trap at "
                    f"({nx}, {ny})"
                )


class TestUnhiredHenchmanAvoidsTraps:
    def test_wander_avoids_visible_trap(self):
        """Unhired adventurer drifting avoids visible trap tiles."""
        i18n_init("en")
        world = World()
        level = _make_level(5, 5)
        pid = _make_player(world, 0, 0)  # far away
        hid = _make_henchman(world, 2, 2, hired=False)

        # Surround with traps except (1, 2)
        for dx, dy in [(-1, -1), (0, -1), (1, -1),
                       (1, 0), (1, 1), (0, 1), (-1, 1)]:
            _place_trap(world, 2 + dx, 2 + dy, hidden=False)

        for seed in range(50):
            set_seed(seed)
            action = decide_unhired_wander_action(
                hid, world, level, pid,
            )
            if action is None:
                continue
            if hasattr(action, "dx"):
                nx = 2 + action.dx
                ny = 2 + action.dy
                assert not _has_visible_trap(world, nx, ny), (
                    f"seed={seed}: unhired stepped onto trap at "
                    f"({nx}, {ny})"
                )

    def test_hidden_traps_not_avoided(self):
        """Unhired adventurer does not avoid hidden traps."""
        i18n_init("en")
        world = World()
        level = _make_level(3, 3)
        hid = _make_henchman(world, 1, 1, hired=False)

        # Place hidden traps everywhere around
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (dx, dy) != (0, 0):
                    _place_trap(world, 1 + dx, 1 + dy, hidden=True)

        # Should still be able to move (traps are hidden)
        moved = False
        for seed in range(50):
            set_seed(seed)
            action = decide_unhired_wander_action(
                hid, world, level, None,
            )
            if action and hasattr(action, "dx"):
                moved = True
                break
        assert moved, "Should be able to walk onto hidden traps"
