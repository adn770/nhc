"""Town life M9: end-to-end integration and perception.

Spawn a full city's population from the real town generator and tick
every citizen's AI, confirming the schedule/patrol/event spawn wiring
holds together on generated geometry and that the web entity-gather
surfaces the whole crowd (no silent cap). See ``design/town_life.md``.
"""

from __future__ import annotations

import random

import pytest

from nhc.ai.behavior import decide_action
from nhc.core.actions import HoldAction, MoveAction
from nhc.core.ecs import World
from nhc.core.game import Game
from nhc.entities.components import (
    Description, Health, Player, Position, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.model import TimeOfDay
from nhc.i18n import init as i18n_init
from nhc.rendering.web_client import WebClient
from nhc.sites.town import assemble_town

# Full-city assembly + multi-turn AI ticking is heavy; this is an
# integration check, kept out of the fast dev loop.
pytestmark = pytest.mark.slow

CITIZEN_BEHAVIORS = {"errand", "patrol"}

_CITY_SITE = None


def _city_site():
    """Assemble the city once and reuse its (immutable) placement
    list across tests — assembly is the expensive part; each test
    spawns into a fresh world."""
    global _CITY_SITE
    if _CITY_SITE is None:
        i18n_init("en")
        EntityRegistry.discover_all()
        _CITY_SITE = assemble_town("c1", random.Random(4), size_class="city")
    return _CITY_SITE


def _spawned_city() -> tuple[Game, int]:
    """Spawn the city's full population into a fresh world via the
    real game spawn path. Returns (game, player_id)."""
    site = _city_site()

    g = Game.__new__(Game)
    g.world = World()
    g.level = site.surface
    g._knowledge = None
    g._spawn_level_entities(site.surface.entities)

    pid = g.world.create_entity({
        "Position": Position(x=2, y=2, level_id=site.surface.id),
        "Player": Player(),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=20, maximum=20),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })
    g.world.time_of_day = TimeOfDay.MIDDAY
    return g, pid


def test_city_spawns_scheduled_and_patrolling_citizens() -> None:
    g, _ = _spawned_city()
    routines = g.world.query("DailyRoutine")
    patrols = g.world.query("PatrolRoute")
    assert routines, "no scheduled citizens spawned"
    assert patrols, "no patrolling watch spawned"


def test_every_citizen_ai_ticks_without_error() -> None:
    g, pid = _spawned_city()
    level = g.level
    moves = 0
    for eid, ai in g.world.query("AI"):
        if ai.behavior not in CITIZEN_BEHAVIORS:
            continue
        action = decide_action(eid, g.world, level, pid)
        # Peaceful citizens only ever hold or step — never attack.
        assert action is None or isinstance(
            action, (MoveAction, HoldAction),
        )
        if isinstance(action, MoveAction):
            moves += 1
    assert moves > 0, "no citizen produced a movement at midday"


def test_night_thins_the_streets() -> None:
    """At night the scheduled crowd routes home and despawns, so
    fewer citizens remain than at midday."""
    g, pid = _spawned_city()
    level = g.level

    def _living_citizens() -> int:
        return sum(
            1 for _, ai in g.world.query("AI")
            if ai.behavior in CITIZEN_BEHAVIORS
        )

    midday_count = _living_citizens()
    g.world.time_of_day = TimeOfDay.NIGHT
    # Run enough ticks for despawn-anchored citizens to reach home.
    for _ in range(80):
        for eid, ai in list(g.world.query("AI")):
            if ai.behavior not in CITIZEN_BEHAVIORS:
                continue
            action = decide_action(eid, g.world, level, pid)
            if isinstance(action, MoveAction):
                pos = g.world.get_component(eid, "Position")
                pos.x += action.dx
                pos.y += action.dy
    assert _living_citizens() < midday_count


def test_gather_entities_surfaces_the_whole_crowd() -> None:
    g, pid = _spawned_city()
    level = g.level
    # Make the whole surface visible so nothing is gated by FOV.
    for tile in level.iter_tiles():
        tile.visible = True

    renderer = WebClient.__new__(WebClient)
    gathered = renderer._gather_entities(g.world, level, pid, turn=0)

    drawable = sum(
        1 for eid in g.world._entities
        if g.world.get_component(eid, "Position")
        and g.world.get_component(eid, "Renderable")
    )
    assert len(gathered) == drawable  # no silent cap
