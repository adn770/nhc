"""Tests for the `errand` AI behavior — town NPCs wandering streets.

See design/town_life.md (TODO). Errand NPCs roam walkable street
tiles on the town surface, occasionally hovering near building doors
to simulate visits, and never step onto door features (which would
teleport them to building interiors).
"""

from __future__ import annotations

from nhc.ai.behavior import decide_action
from nhc.core.actions import HoldAction, MoveAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Errand,
    Health,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _street_level(width: int = 12, height: int = 12) -> Level:
    tiles = [
        [
            Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.STREET,
            )
            for _ in range(width)
        ]
        for _ in range(height)
    ]
    return Level(
        id="town_surface",
        name="Town",
        depth=0,
        width=width,
        height=height,
        tiles=tiles,
        rooms=[],
        corridors=[],
        entities=[],
    )


def _make_villager(
    world: World,
    x: int,
    y: int,
    target: tuple[int, int] | None = None,
    idle: int = 0,
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=0, dexterity=1),
        "Health": Health(current=4, maximum=4),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Villager"),
        "Errand": Errand(
            target_x=target[0] if target else None,
            target_y=target[1] if target else None,
            idle_turns_remaining=idle,
        ),
    })


def _make_player(world: World, x: int = 0, y: int = 0) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Player": Player(),
        "Stats": Stats(strength=2, dexterity=2, wisdom=1),
        "Health": Health(current=20, maximum=20),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


class TestErrandMovement:
    def test_villager_moves_toward_target(self):
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 0, 0)
        vid = _make_villager(world, 1, 1, target=(5, 5))

        action = decide_action(vid, world, level, pid)

        assert isinstance(action, MoveAction)
        pos = world.get_component(vid, "Position")
        nx, ny = pos.x + action.dx, pos.y + action.dy
        # Step reduces chebyshev distance to target
        before = max(abs(pos.x - 5), abs(pos.y - 5))
        after = max(abs(nx - 5), abs(ny - 5))
        assert after < before

    def test_villager_idles_on_arrival(self):
        """Reaching target flips to idle and clears target."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 0, 0)
        vid = _make_villager(world, 5, 5, target=(5, 5))

        action = decide_action(vid, world, level, pid)

        assert isinstance(action, HoldAction)
        errand = world.get_component(vid, "Errand")
        assert errand.idle_turns_remaining > 0
        assert errand.target_x is None
        assert errand.target_y is None

    def test_idle_counter_decrements(self):
        """Idle villager holds and counter ticks down."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 0, 0)
        vid = _make_villager(world, 5, 5, idle=3)

        action = decide_action(vid, world, level, pid)

        assert isinstance(action, HoldAction)
        errand = world.get_component(vid, "Errand")
        assert errand.idle_turns_remaining == 2

    def test_picks_new_target_when_none(self):
        """With no target and no idle turns, villager picks a fresh
        destination and starts moving toward it."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 0, 0)
        vid = _make_villager(world, 5, 5)

        decide_action(vid, world, level, pid)
        errand = world.get_component(vid, "Errand")

        assert errand.target_x is not None
        assert errand.target_y is not None


class TestErrandDoorAvoidance:
    def test_villager_refuses_door_tile(self):
        """Villager never steps onto a door tile (would teleport
        into the building interior). On a narrow passage the only
        step is a door tile — the villager must hold or route
        elsewhere."""
        i18n_init("en")
        set_seed(42)
        world = World()
        # Only three walkable tiles; middle one is a closed door.
        # Villager at x=0, target at x=2 — cannot cross.
        level = Level(
            id="town_surface", name="T", depth=0,
            width=3, height=1,
            tiles=[[
                Tile(
                    terrain=Terrain.FLOOR,
                    surface_type=SurfaceType.STREET,
                ),
                Tile(
                    terrain=Terrain.FLOOR,
                    surface_type=SurfaceType.STREET,
                    feature="door_closed",
                ),
                Tile(
                    terrain=Terrain.FLOOR,
                    surface_type=SurfaceType.STREET,
                ),
            ]],
            rooms=[], corridors=[], entities=[],
        )
        pid = _make_player(world, 0, 0)
        # Place villager out of range so the player's Position
        # does not collide.
        pos = world.get_component(pid, "Position")
        pos.x = 0
        pos.y = 0
        vid = _make_villager(world, 0, 0, target=(2, 0))
        # Move villager off player tile — villager lives at x=0
        # also, but in this contrived setup the player sits on the
        # same tile. Bump the villager to (0,0) conflicts; re-wire.
        vpos = world.get_component(vid, "Position")
        # Give villager its own row-0 position; player sits elsewhere
        vpos.x = 0
        vpos.y = 0
        # Put the player somewhere else so the A* "don't step on
        # blockers" guard does not fire.
        pos.x = 2
        pos.y = 0

        action = decide_action(vid, world, level, pid)

        # Villager should NOT move onto the door at x=1
        if isinstance(action, MoveAction):
            nx = vpos.x + action.dx
            ny = vpos.y + action.dy
            assert (nx, ny) != (1, 0), (
                "errand villager stepped onto door tile"
            )


class TestErrandAdjacentPlayer:
    def test_villager_does_not_attack_adjacent_player(self):
        """Errand is non-combat: an adjacent player gets ignored
        (no MeleeAttackAction). The villager just continues its
        errand loop."""
        i18n_init("en")
        set_seed(42)
        world = World()
        level = _street_level()
        pid = _make_player(world, 5, 5)
        vid = _make_villager(world, 5, 6, target=(8, 8))

        action = decide_action(vid, world, level, pid)

        # Any outcome is fine *except* an attack
        from nhc.core.actions import MeleeAttackAction
        assert not isinstance(action, MeleeAttackAction)
