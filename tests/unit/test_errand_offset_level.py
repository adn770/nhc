"""Regression: errand AI on an origin-offset level (building floors).

Building floor Levels are anchored in world space via origin_x /
origin_y, so their tiles use global coordinates. The errand
destination picker must iterate that global space — iterating local
0-based coords leaves a resident with no reachable candidates, so it
idles forever (production bug: building residents never moved while
street folk did).
"""

from __future__ import annotations

from nhc.ai.behavior import _decide_errand_action
from nhc.core.actions import MoveAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Description, Errand, Health, Position, Renderable, Stats,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed

ORIGIN_X, ORIGIN_Y = 35, 22
W, H = 13, 12


def _offset_building_floor() -> Level:
    level = Level.create_empty(
        "b33_f0", "Home", 1, W, H,
        origin_x=ORIGIN_X, origin_y=ORIGIN_Y,
    )
    for y in range(ORIGIN_Y, ORIGIN_Y + H):
        for x in range(ORIGIN_X, ORIGIN_X + W):
            level.set_tile(x, y, Tile(terrain=Terrain.FLOOR))
    return level


def _resident(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="b33_f0"),
        "Stats": Stats(strength=0, dexterity=1),
        "Health": Health(current=4, maximum=4),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Villager"),
        "Errand": Errand(),
    })


def test_resident_moves_on_offset_floor() -> None:
    i18n_init("en")
    set_seed(1)
    world = World()
    level = _offset_building_floor()
    rid = _resident(world, ORIGIN_X + 6, ORIGIN_Y + 5)  # (41, 27)

    action = _decide_errand_action(rid, world, level, 0)

    errand = world.get_component(rid, "Errand")
    assert errand.target_x is not None, "no destination picked (stuck)"
    # The destination lands inside the floor's global bounds.
    assert level.in_bounds(errand.target_x, errand.target_y)
    assert isinstance(action, MoveAction)


def test_resident_keeps_moving_over_several_ticks() -> None:
    i18n_init("en")
    set_seed(2)
    world = World()
    level = _offset_building_floor()
    rid = _resident(world, ORIGIN_X + 6, ORIGIN_Y + 5)
    pos = world.get_component(rid, "Position")

    moved = False
    for _ in range(20):
        action = _decide_errand_action(rid, world, level, 0)
        if isinstance(action, MoveAction):
            pos.x += action.dx
            pos.y += action.dy
            moved = True
        assert level.in_bounds(pos.x, pos.y)
    assert moved
