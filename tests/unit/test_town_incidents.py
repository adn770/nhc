"""Town life M8: minor incidents with guard reaction.

The director may stage an incident the town reacts to — a caught
pickpocket bolting for the edge, or a tavern brawl. An incident
emits a log line, spawns the offender(s) live, and diverts the
watch to converge on the spot. The player is never the target. See
``design/town_life.md``.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from nhc.core.ecs import World
from nhc.core.game import Game
from nhc.dungeon.model import (
    EntityPlacement, Level, SurfaceType, Terrain, Tile,
)
from nhc.entities.components import (
    AI, Description, Health, PatrolRoute, Position, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import WorldType
from nhc.hexcrawl.model import TimeOfDay
from nhc.i18n import init as i18n_init
from nhc.i18n import t
from nhc.sites._town_events import roll_town_events


def _town_surface(width: int = 24, height: int = 18) -> Level:
    tiles = [
        [
            Tile(terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET)
            for _ in range(width)
        ]
        for _ in range(height)
    ]
    return Level(
        id="town_surface", name="Town", depth=0,
        width=width, height=height,
        _tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _city_incident(level: Level):
    """First seed that stages an incident at MIDDAY in a city."""
    for seed in range(80):
        res = roll_town_events(
            level, "city", TimeOfDay.MIDDAY, random.Random(seed),
        )
        if res.incident is not None:
            return res
    raise AssertionError("no incident across 80 seeds")


# --- director rolls ----------------------------------------------


def test_no_incident_in_hamlet() -> None:
    level = _town_surface()
    for seed in range(60):
        res = roll_town_events(
            level, "hamlet", TimeOfDay.MIDDAY, random.Random(seed),
        )
        assert res.incident is None


def test_incident_can_fire_in_city() -> None:
    level = _town_surface()
    assert _city_incident(level).incident is not None


def test_no_incident_at_night() -> None:
    level = _town_surface()
    for seed in range(60):
        res = roll_town_events(
            level, "city", TimeOfDay.NIGHT, random.Random(seed),
        )
        assert res.incident is None


def test_incident_message_and_location_on_street() -> None:
    level = _town_surface()
    res = _city_incident(level)
    inc = res.incident
    assert inc.message_key.startswith("town.incident.")
    tile = level.tile_at(inc.x, inc.y)
    assert tile.walkable and tile.surface_type == SurfaceType.STREET


def test_incident_offenders_are_event_spawns() -> None:
    level = _town_surface()
    res = _city_incident(level)
    assert res.placements  # offenders staged
    assert all(p.extra.get("event_spawn") for p in res.placements)


def test_incident_lines_resolve() -> None:
    for lang in ("en", "ca", "es"):
        i18n_init(lang)
        for key in ("town.incident.pickpocket", "town.incident.brawl"):
            val = t(key)
            assert val and not val.startswith("town.")


# --- guard reaction ----------------------------------------------


def _guard_game() -> Game:
    level = _town_surface()
    g = Game.__new__(Game)
    g.world_type = WorldType.HEXCRAWL
    g.world = World()
    g.level = level
    g._active_site = SimpleNamespace(surface=level)
    g._active_site_sub = None
    return g


def test_divert_watch_to_redirects_patrollers() -> None:
    g = _guard_game()
    gid = g.world.create_entity({
        "Position": Position(x=2, y=2, level_id="town_surface"),
        "AI": AI(behavior="patrol", faction="human"),
        "PatrolRoute": PatrolRoute(waypoints=[(2, 2), (8, 8)]),
        "Renderable": Renderable(glyph="@"),
        "Description": Description(name="Guard"),
        "Stats": Stats(),
        "Health": Health(current=10, maximum=10),
    })

    g._divert_watch_to(9, 5)

    route = g.world.get_component(gid, "PatrolRoute")
    assert (route.divert_x, route.divert_y) == (9, 5)


def test_pickpocket_offender_spawns_fleeing() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()
    g = _guard_game()
    placement = EntityPlacement(
        entity_type="creature", entity_id="pickpocket", x=3, y=3,
        extra={"event_spawn": True, "flee_to": [0, 0]},
    )

    g._spawn_level_entities([placement])

    thieves = g.world.query("Thief", "Position")
    assert thieves
    eid = thieves[0][0]
    thief = g.world.get_component(eid, "Thief")
    assert thief.fleeing
    assert (thief.flee_target_x, thief.flee_target_y) == (0, 0)
    assert g.world.get_component(eid, "EventSpawn") is not None
