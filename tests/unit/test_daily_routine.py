"""Town life M2: schedule-aware errand via DailyRoutine.

A citizen carrying a ``DailyRoutine`` biases its errand wandering
toward the anchor for the *current* town segment (read from
``World.time_of_day``), so the same NPC heads to the market at
MIDDAY and the tavern at EVENING. A NIGHT anchor flagged
``despawn`` routes the NPC home and removes it on arrival. With no
routine entry for the active segment, the NPC falls back to its
static ``Errand`` anchor (or free wandering). See
``design/town_life.md``.
"""

from __future__ import annotations

from nhc.ai.behavior import _decide_errand_action
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import (
    AI,
    DailyRoutine,
    Description,
    Errand,
    Health,
    Position,
    Renderable,
    RoutineAnchor,
    Stats,
)
from nhc.hexcrawl.model import TimeOfDay
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _town_surface(width: int = 20, height: int = 20) -> Level:
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


def _make_citizen(
    world: World, x: int, y: int, *,
    routine: DailyRoutine | None = None,
    anchor: tuple[int, int] | None = None,
    anchor_weight: float = 0.0,
) -> int:
    comps = {
        "Position": Position(x=x, y=y, level_id="town_surface"),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=7, faction="human"),
        "Renderable": Renderable(glyph="c", color="white"),
        "Description": Description(name="Citizen"),
        "Errand": Errand(
            anchor_x=anchor[0] if anchor else None,
            anchor_y=anchor[1] if anchor else None,
            anchor_weight=anchor_weight,
        ),
    }
    if routine is not None:
        comps["DailyRoutine"] = routine
    return world.create_entity(comps)


def _collect_picks(world, level, eid, pid, n=20) -> list[tuple[int, int]]:
    errand = world.get_component(eid, "Errand")
    picks: list[tuple[int, int]] = []
    for _ in range(n):
        errand.target_x = None
        errand.target_y = None
        errand.idle_turns_remaining = 0
        _decide_errand_action(eid, world, level, pid)
        if errand.target_x is not None:
            picks.append((errand.target_x, errand.target_y))
    return picks


def _near(pt, anchor, r=3) -> bool:
    return max(abs(pt[0] - anchor[0]), abs(pt[1] - anchor[1])) <= r


# --- segment-dependent anchoring ---------------------------------


def test_midday_anchor_attracts() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    routine = DailyRoutine(anchors={
        TimeOfDay.MIDDAY: RoutineAnchor(x=18, y=18, weight=1.0),
        TimeOfDay.EVENING: RoutineAnchor(x=1, y=1, weight=1.0),
    })
    cid = _make_citizen(world, 10, 10, routine=routine)
    world.time_of_day = TimeOfDay.MIDDAY

    picks = _collect_picks(world, level, cid, 0)
    assert picks
    assert all(_near(p, (18, 18)) for p in picks)


def test_evening_anchor_attracts() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    routine = DailyRoutine(anchors={
        TimeOfDay.MIDDAY: RoutineAnchor(x=18, y=18, weight=1.0),
        TimeOfDay.EVENING: RoutineAnchor(x=1, y=1, weight=1.0),
    })
    cid = _make_citizen(world, 10, 10, routine=routine)
    world.time_of_day = TimeOfDay.EVENING

    picks = _collect_picks(world, level, cid, 0)
    assert picks
    assert all(_near(p, (1, 1)) for p in picks)


def test_routine_overrides_static_errand_anchor() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    routine = DailyRoutine(anchors={
        TimeOfDay.MIDDAY: RoutineAnchor(x=18, y=18, weight=1.0),
    })
    # Static anchor points the opposite way; the routine wins.
    cid = _make_citizen(
        world, 10, 10, routine=routine,
        anchor=(1, 1), anchor_weight=1.0,
    )
    world.time_of_day = TimeOfDay.MIDDAY

    picks = _collect_picks(world, level, cid, 0)
    assert picks
    assert all(_near(p, (18, 18)) for p in picks)


def test_falls_back_to_static_anchor_with_no_entry() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    # Routine only covers MORNING; active segment is MIDDAY.
    routine = DailyRoutine(anchors={
        TimeOfDay.MORNING: RoutineAnchor(x=1, y=1, weight=1.0),
    })
    cid = _make_citizen(
        world, 10, 10, routine=routine,
        anchor=(18, 18), anchor_weight=1.0,
    )
    world.time_of_day = TimeOfDay.MIDDAY

    picks = _collect_picks(world, level, cid, 0)
    assert picks
    assert all(_near(p, (18, 18)) for p in picks)


def test_falls_back_when_time_of_day_none() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    routine = DailyRoutine(anchors={
        TimeOfDay.MIDDAY: RoutineAnchor(x=1, y=1, weight=1.0),
    })
    cid = _make_citizen(
        world, 10, 10, routine=routine,
        anchor=(18, 18), anchor_weight=1.0,
    )
    world.time_of_day = None  # not in a timed site yet

    picks = _collect_picks(world, level, cid, 0)
    assert picks
    assert all(_near(p, (18, 18)) for p in picks)


# --- loiter loop preserved ---------------------------------------


def test_loiter_on_arrival() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    cid = _make_citizen(world, 5, 5)
    errand = world.get_component(cid, "Errand")
    errand.target_x, errand.target_y = 5, 5  # already at target

    action = _decide_errand_action(cid, world, level, 0)
    assert action is not None  # HoldAction, not despawn
    assert errand.idle_turns_remaining > 0
    assert errand.target_x is None


# --- night: route home and despawn -------------------------------


def test_night_routes_to_exact_home() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    routine = DailyRoutine(anchors={
        TimeOfDay.NIGHT: RoutineAnchor(x=5, y=5, despawn=True),
    })
    cid = _make_citizen(world, 12, 12, routine=routine)
    world.time_of_day = TimeOfDay.NIGHT

    errand = world.get_component(cid, "Errand")
    errand.target_x = errand.target_y = None
    errand.idle_turns_remaining = 0
    _decide_errand_action(cid, world, level, 0)
    # Heads to the exact home tile, not a tile merely near it.
    assert (errand.target_x, errand.target_y) == (5, 5)


def test_night_despawns_on_arrival_home() -> None:
    i18n_init("en")
    set_seed(7)
    world = World()
    level = _town_surface()
    routine = DailyRoutine(anchors={
        TimeOfDay.NIGHT: RoutineAnchor(x=5, y=5, despawn=True),
    })
    cid = _make_citizen(world, 5, 5, routine=routine)
    world.time_of_day = TimeOfDay.NIGHT

    errand = world.get_component(cid, "Errand")
    errand.target_x, errand.target_y = 5, 5  # arrived home

    action = _decide_errand_action(cid, world, level, 0)
    assert action is None
    assert world.get_component(cid, "Position") is None  # despawned
