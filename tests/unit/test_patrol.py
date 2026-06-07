"""Town life M3: the `patrol` behaviour.

Guards and the town crier follow a fixed loop of waypoints. The
route is interruptible — an incident can divert a patroller, who
investigates and then resumes from the nearest waypoint. Patrollers
never hunt the player (chase radius 0, peaceful). See
``design/town_life.md``.
"""

from __future__ import annotations

from nhc.ai.behavior import (
    CHASE_RADIUS,
    PEACEFUL_BEHAVIORS,
    _decide_patrol_action,
    decide_action,
    divert_patrol,
)
from nhc.core.actions import HoldAction, MoveAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    Description,
    Health,
    PatrolRoute,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed
from nhc.utils.spatial import chebyshev


def _town_surface(width: int = 12, height: int = 12) -> Level:
    tiles = [
        [
            Tile(terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET)
            for _ in range(width)
        ]
        for _ in range(height)
    ]
    level = Level(
        id="town_surface", name="Town", depth=0,
        width=width, height=height,
        _tiles=tiles, rooms=[], corridors=[], entities=[],
    )
    level.metadata.theme = "town"
    return level


def _make_guard(
    world: World, x: int, y: int, *,
    waypoints: list[tuple[int, int]], loop: bool = True,
    cursor: int = 0,
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=10, maximum=10),
        "AI": AI(behavior="patrol", morale=9, faction="human"),
        "Renderable": Renderable(glyph="G", color="blue"),
        "Description": Description(name="Guard"),
        "PatrolRoute": PatrolRoute(
            waypoints=list(waypoints), loop=loop, cursor=cursor,
        ),
    })


def _make_player(world: World, x: int = 0, y: int = 0) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Player": Player(),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=20, maximum=20),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


# --- classification ----------------------------------------------


def test_patrol_is_peaceful_and_never_chases() -> None:
    assert "patrol" in PEACEFUL_BEHAVIORS
    assert CHASE_RADIUS["patrol"] == 0


# --- route following ---------------------------------------------


def test_walks_toward_current_waypoint() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    gid = _make_guard(world, 2, 2, waypoints=[(2, 8), (8, 8)])

    action = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(action, MoveAction)
    nx, ny = 2 + action.dx, 2 + action.dy
    assert chebyshev(nx, ny, 2, 8) < chebyshev(2, 2, 2, 8)


def test_advances_cursor_and_loops() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    # Sitting on waypoint 0 -> arrival advances to waypoint 1.
    gid = _make_guard(world, 2, 8, waypoints=[(2, 8), (8, 8)], cursor=0)
    route = world.get_component(gid, "PatrolRoute")

    action = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(action, HoldAction)
    assert route.cursor == 1

    # Jump to the last waypoint; arrival wraps back to 0.
    pos = world.get_component(gid, "Position")
    pos.x, pos.y = 8, 8
    route.pause_remaining = 0
    _decide_patrol_action(gid, world, level, 0)
    assert route.cursor == 0


def test_no_loop_clamps_at_last_waypoint() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    gid = _make_guard(
        world, 8, 8, waypoints=[(2, 8), (8, 8)], cursor=1, loop=False,
    )
    route = world.get_component(gid, "PatrolRoute")

    _decide_patrol_action(gid, world, level, 0)
    assert route.cursor == 1  # stays put, no wrap


def test_pause_holds_then_resumes() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    gid = _make_guard(world, 2, 2, waypoints=[(2, 8)])
    route = world.get_component(gid, "PatrolRoute")
    route.pause_remaining = 2

    a1 = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(a1, HoldAction)
    assert route.pause_remaining == 1
    a2 = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(a2, HoldAction)
    assert route.pause_remaining == 0
    a3 = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(a3, MoveAction)  # back on route


def test_no_waypoints_holds() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    gid = _make_guard(world, 2, 2, waypoints=[])

    assert isinstance(
        _decide_patrol_action(gid, world, level, 0), HoldAction,
    )


# --- interruption / diversion ------------------------------------


def test_divert_breaks_off_route() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    gid = _make_guard(world, 2, 2, waypoints=[(2, 8)])
    divert_patrol(world, gid, 9, 2)

    action = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(action, MoveAction)
    nx, ny = 2 + action.dx, 2 + action.dy
    # Heading toward the incident (9,2), not the waypoint (2,8).
    assert chebyshev(nx, ny, 9, 2) < chebyshev(2, 2, 9, 2)


def test_divert_resumes_nearest_waypoint_on_arrival() -> None:
    set_seed(1)
    world = World()
    level = _town_surface()
    gid = _make_guard(
        world, 9, 2, waypoints=[(2, 2), (9, 4)], cursor=0,
    )
    route = world.get_component(gid, "PatrolRoute")
    route.divert_x, route.divert_y = 9, 2  # already at the incident

    action = _decide_patrol_action(gid, world, level, 0)
    assert isinstance(action, HoldAction)
    assert route.divert_x is None and route.divert_y is None
    # Nearest waypoint to (9,2) is (9,4) at index 1 (dist 2 vs 7).
    assert route.cursor == 1


def test_divert_patrol_helper_sets_target() -> None:
    world = World()
    gid = _make_guard(world, 0, 0, waypoints=[(1, 1)])
    divert_patrol(world, gid, 5, 6)
    route = world.get_component(gid, "PatrolRoute")
    assert (route.divert_x, route.divert_y) == (5, 6)


# --- dispatch ----------------------------------------------------


def test_dispatch_routes_patrol_behavior() -> None:
    i18n_init("en")
    set_seed(1)
    world = World()
    level = _town_surface()
    pid = _make_player(world, 0, 0)
    gid = _make_guard(world, 2, 2, waypoints=[(2, 8)])

    action = decide_action(gid, world, level, pid)
    assert isinstance(action, MoveAction)
    nx, ny = 2 + action.dx, 2 + action.dy
    assert chebyshev(nx, ny, 2, 8) < chebyshev(2, 2, 2, 8)
