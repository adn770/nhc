"""Town life M7: the event director (scheduled spectacle).

On town entry the director deterministically rolls ambient
spectacle — a market day (extra vendors + a crowd at the plaza) or a
procession — surfaced as a log line plus live extra entities tagged
``EventSpawn`` so they never accumulate across visits. Spectacle is
daytime only. See ``design/town_life.md``.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from nhc.core.ecs import World
from nhc.core.game import Game
from nhc.dungeon.model import (
    EntityPlacement, Level, SurfaceType, Terrain, Tile,
)
from nhc.entities.components import EventSpawn, Position
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


# --- director rolls ----------------------------------------------


def test_no_market_day_in_hamlet() -> None:
    level = _town_surface()
    for seed in range(40):
        res = roll_town_events(
            level, "hamlet", TimeOfDay.MIDDAY, random.Random(seed),
        )
        assert "town.event.market_day" not in res.messages


def test_market_day_can_fire_in_city() -> None:
    level = _town_surface()
    fired = any(
        "town.event.market_day" in roll_town_events(
            level, "city", TimeOfDay.MIDDAY, random.Random(seed),
        ).messages
        for seed in range(40)
    )
    assert fired


def test_no_spectacle_at_night() -> None:
    level = _town_surface()
    for seed in range(40):
        res = roll_town_events(
            level, "city", TimeOfDay.NIGHT, random.Random(seed),
        )
        assert res.messages == []
        assert res.placements == []


def test_deterministic_for_same_seed() -> None:
    level = _town_surface()
    a = roll_town_events(level, "city", TimeOfDay.MIDDAY, random.Random(7))
    b = roll_town_events(level, "city", TimeOfDay.MIDDAY, random.Random(7))
    assert a.messages == b.messages
    assert len(a.placements) == len(b.placements)


def test_market_spawns_are_tagged_and_on_street() -> None:
    level = _town_surface()
    # Find a seed where the market fires, then inspect its spawns.
    for seed in range(40):
        res = roll_town_events(
            level, "city", TimeOfDay.MIDDAY, random.Random(seed),
        )
        if "town.event.market_day" not in res.messages:
            continue
        assert res.placements
        for p in res.placements:
            assert isinstance(p, EntityPlacement)
            assert p.entity_type == "creature"
            assert p.extra.get("event_spawn") is True
            tile = level.tile_at(p.x, p.y)
            assert tile.walkable
            assert tile.surface_type == SurfaceType.STREET
        return
    raise AssertionError("market day never fired across 40 seeds")


# --- locale ------------------------------------------------------


def test_event_lines_resolve() -> None:
    for lang in ("en", "ca", "es"):
        i18n_init(lang)
        for key in ("town.event.market_day", "town.event.procession"):
            val = t(key)
            assert val and not val.startswith("town.")


# --- entry hook: no accumulation ---------------------------------


def _town_game(segment: TimeOfDay) -> tuple[Game, list[str]]:
    level = _town_surface()
    g = Game.__new__(Game)
    g.world_type = WorldType.HEXCRAWL
    g.world = World()
    g.level = level
    g.seed = 1
    g._active_site = SimpleNamespace(surface=level)
    g._active_site_sub = None
    messages: list[str] = []
    g.renderer = SimpleNamespace(add_message=messages.append)
    g.hex_world = SimpleNamespace(time=segment, day=1)
    return g, messages


def test_run_town_events_clears_stale_event_spawns() -> None:
    i18n_init("en")
    g, _ = _town_game(TimeOfDay.MIDDAY)
    stale = g.world.create_entity({
        "EventSpawn": EventSpawn(),
        "Position": Position(x=1, y=1, level_id="town_surface"),
    })
    cell = SimpleNamespace(
        dungeon=SimpleNamespace(size_class="city"),
    )

    g._run_town_events(cell)

    # The stale event entity is gone (re-rolled, not accumulated).
    assert g.world.get_component(stale, "Position") is None


def test_run_town_events_no_spawn_at_night() -> None:
    i18n_init("en")
    g, messages = _town_game(TimeOfDay.NIGHT)
    cell = SimpleNamespace(dungeon=SimpleNamespace(size_class="city"))

    g._run_town_events(cell)

    assert messages == []
    spawned = g.world.query("EventSpawn")
    assert spawned == []
