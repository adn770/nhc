"""Town life M5: the watch and the crier.

Town guards and a watch captain walk patrol routes; a town crier
walks a route and calls out each time-of-day segment as the slow-
drift clock crosses it. Counts scale by size class — guards
everywhere, a crier in town/city, a captain only in cities. See
``design/town_life.md``.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from nhc.core.game import Game
from nhc.core.ecs import World
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.entities.components import Crier, Position
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import WorldType
from nhc.hexcrawl.model import HexWorld, TimeOfDay
from nhc.i18n import init as i18n_init
from nhc.i18n import t
from nhc.sites.town import (
    TOWN_GUARD_COUNT,
    TOWN_HAS_CAPTAIN,
    TOWN_HAS_CRIER,
    assemble_town,
)

WATCH = ("town_guard", "watch_captain", "town_crier")


# --- registry ----------------------------------------------------


@pytest.mark.parametrize("cid", WATCH)
def test_watch_registers_as_patrol(cid: str) -> None:
    EntityRegistry.discover_all()
    comps = EntityRegistry.get_creature(cid)
    assert comps["AI"].behavior == "patrol"
    assert comps["AI"].faction == "human"


def test_crier_carries_marker() -> None:
    EntityRegistry.discover_all()
    assert "Crier" in EntityRegistry.get_creature("town_crier")


# --- locale ------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize("cid", WATCH)
def test_locale_names_resolve(lang: str, cid: str) -> None:
    i18n_init(lang)
    for field in ("name", "short", "long"):
        val = t(f"creature.{cid}.{field}")
        assert val and not val.startswith("creature.")


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize("seg", ["morning", "midday", "evening", "night"])
def test_crier_hour_lines_resolve(lang: str, seg: str) -> None:
    i18n_init(lang)
    val = t(f"town.crier_hour.{seg}")
    assert val and not val.startswith("town.")


# --- population --------------------------------------------------


@pytest.mark.parametrize("size", ["hamlet", "village", "town", "city"])
def test_guard_count_within_range(size: str) -> None:
    lo, hi = TOWN_GUARD_COUNT[size]
    for seed in range(12):
        site = assemble_town("t1", random.Random(seed), size_class=size)
        guards = [
            e for e in site.surface.entities
            if e.entity_id == "town_guard"
        ]
        assert lo <= len(guards) <= hi


@pytest.mark.parametrize("size", ["hamlet", "village", "town", "city"])
def test_crier_and_captain_presence(size: str) -> None:
    site = assemble_town("t1", random.Random(1), size_class=size)
    criers = [e for e in site.surface.entities if e.entity_id == "town_crier"]
    captains = [
        e for e in site.surface.entities if e.entity_id == "watch_captain"
    ]
    assert len(criers) == (1 if size in TOWN_HAS_CRIER else 0)
    assert len(captains) == (1 if size in TOWN_HAS_CAPTAIN else 0)


def test_guards_carry_patrol_route_on_streets() -> None:
    site = assemble_town("t1", random.Random(2), size_class="city")
    surface = site.surface
    guards = [e for e in surface.entities if e.entity_id == "town_guard"]
    assert guards
    for g in guards:
        wp = g.extra.get("patrol_waypoints")
        assert wp and len(wp) >= 2
        for (wx, wy) in wp:
            tile = surface.tile_at(wx, wy)
            assert tile.walkable
            assert tile.surface_type == SurfaceType.STREET


# --- crier hour announcement -------------------------------------


def _town_surface() -> Level:
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(3)]
        for _ in range(3)
    ]
    return Level(
        id="town_surface", name="Town", depth=0, width=3, height=3,
        _tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _crier_game(*, with_crier: bool) -> tuple[Game, list[str]]:
    surface = _town_surface()
    g = Game.__new__(Game)
    g.world_type = WorldType.HEXCRAWL
    g.hex_world = HexWorld(pack_id="t", seed=1, width=4, height=4)
    g.world = World()
    g.level = surface
    g._active_site = SimpleNamespace(surface=surface)
    g._active_site_sub = None
    messages: list[str] = []
    g.renderer = SimpleNamespace(add_message=messages.append)
    if with_crier:
        g.world.create_entity({
            "Crier": Crier(),
            "Position": Position(x=0, y=0, level_id="town_surface"),
        })
    return g, messages


def test_crier_announces_on_segment_boundary() -> None:
    i18n_init("en")
    g, messages = _crier_game(with_crier=True)
    g.hex_world.hour, g.hex_world.minute = 11, 58  # MORNING, near noon
    g.hex_world._sync_time_from_hour()

    g._advance_site_clock()  # crosses into MIDDAY

    assert g.hex_world.time is TimeOfDay.MIDDAY
    assert t("town.crier_hour.midday") in messages


def test_no_announcement_without_crier() -> None:
    i18n_init("en")
    g, messages = _crier_game(with_crier=False)
    g.hex_world.hour, g.hex_world.minute = 11, 58
    g.hex_world._sync_time_from_hour()

    g._advance_site_clock()

    assert g.hex_world.time is TimeOfDay.MIDDAY
    assert messages == []


def test_no_announcement_without_boundary() -> None:
    i18n_init("en")
    g, messages = _crier_game(with_crier=True)
    g.hex_world.hour, g.hex_world.minute = 9, 0  # mid-MORNING
    g.hex_world._sync_time_from_hour()

    g._advance_site_clock()  # stays in MORNING

    assert g.hex_world.time is TimeOfDay.MORNING
    assert messages == []
