"""Town life M4: the working-folk roster.

Six tradespeople (blacksmith, market vendor, baker, water carrier,
washerwoman, porter) populate town streets, anchored to a workplace
during the day and routed home (despawning) at night via a
DailyRoutine. Counts scale across all four size classes. See
``design/town_life.md``.
"""

from __future__ import annotations

import random

import pytest

from nhc.ai.schedules import build_worker_routine
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.model import TimeOfDay
from nhc.i18n import init as i18n_init
from nhc.i18n import t
from nhc.sites.town import (
    TOWN_WORKER_COUNT,
    WORKER_IDS,
    assemble_town,
)

WORKING_FOLK = (
    "blacksmith", "market_vendor", "baker",
    "water_carrier", "washerwoman", "porter",
)


# --- registry ----------------------------------------------------


@pytest.mark.parametrize("cid", WORKING_FOLK)
def test_creature_registers_as_peaceful_human(cid: str) -> None:
    EntityRegistry.discover_all()
    comps = EntityRegistry.get_creature(cid)
    assert comps["AI"].behavior == "errand"
    assert comps["AI"].faction == "human"
    assert "Errand" in comps
    assert comps["Health"].maximum > 0


def test_worker_ids_match_roster() -> None:
    assert set(WORKER_IDS) == set(WORKING_FOLK)


# --- locale ------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "ca", "es"])
@pytest.mark.parametrize("cid", WORKING_FOLK)
def test_locale_names_resolve(lang: str, cid: str) -> None:
    i18n_init(lang)
    for field in ("name", "short", "long"):
        val = t(f"creature.{cid}.{field}")
        assert val and not val.startswith("creature."), (
            f"{lang}: creature.{cid}.{field} unresolved"
        )


@pytest.mark.parametrize("lang", ["ca", "es"])
@pytest.mark.parametrize("cid", WORKING_FOLK)
def test_gendered_locales_have_gender(lang: str, cid: str) -> None:
    i18n_init(lang)
    assert t(f"creature.{cid}.gender") in ("m", "f")


# --- routine builder ---------------------------------------------


def test_worker_routine_anchors_workday_and_goes_home() -> None:
    routine = build_worker_routine((10, 4), home=(2, 2))
    a = routine.anchors
    for seg in (TimeOfDay.MORNING, TimeOfDay.MIDDAY, TimeOfDay.EVENING):
        assert (a[seg].x, a[seg].y) == (10, 4)
        assert not a[seg].despawn
    night = a[TimeOfDay.NIGHT]
    assert (night.x, night.y) == (2, 2)
    assert night.despawn


def test_worker_routine_without_home_has_no_night_anchor() -> None:
    routine = build_worker_routine((10, 4))
    assert TimeOfDay.NIGHT not in routine.anchors


# --- town population ---------------------------------------------


@pytest.mark.parametrize("size", ["hamlet", "village", "town", "city"])
def test_worker_count_within_range(size: str) -> None:
    lo, hi = TOWN_WORKER_COUNT[size]
    for seed in range(12):
        site = assemble_town("t1", random.Random(seed), size_class=size)
        workers = [
            e for e in site.surface.entities
            if e.entity_id in WORKING_FOLK
        ]
        assert lo <= len(workers) <= hi, (
            f"{size} seed {seed}: {len(workers)} workers"
        )


def test_workers_carry_routine_spec() -> None:
    site = assemble_town("t1", random.Random(3), size_class="city")
    workers = [
        e for e in site.surface.entities
        if e.entity_id in WORKING_FOLK
    ]
    assert workers
    for w in workers:
        spec = w.extra.get("daily_routine")
        assert spec is not None
        assert "workplace" in spec and "home" in spec


def test_workers_land_on_walkable_street() -> None:
    from nhc.dungeon.model import SurfaceType

    site = assemble_town("t1", random.Random(5), size_class="town")
    surface = site.surface
    for w in (e for e in surface.entities if e.entity_id in WORKING_FOLK):
        tile = surface.tile_at(w.x, w.y)
        assert tile.walkable
        assert tile.surface_type == SurfaceType.STREET
