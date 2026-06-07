"""Town life M1: the slow-drift site clock.

While the player is on a site surface or inside a structure on
it, each turn advances the world clock a sliver so a long visit
can cross a time-of-day segment, while a short errand stays put
(see ``design/town_life.md``). Overland travel and dungeon
descents are unaffected.

These tests drive ``Game._advance_site_clock`` directly on a
hand-built ``Game`` shell, mirroring ``test_current_view`` --
the helper is a pure function of ``hex_world``, ``world``,
``level`` and ``_active_site``.
"""

from __future__ import annotations

from types import SimpleNamespace

from nhc.core.game import Game, SITE_TURNS_PER_SEGMENT
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import WorldType
from nhc.hexcrawl.model import HexWorld, TimeOfDay


class _StubSite:
    def __init__(self, surface):
        self.surface = surface


def _floor_level(*, building_id: str | None = None,
                 level_id: str = "lvl", depth: int = 0) -> Level:
    level = Level.create_empty(level_id, level_id, depth, 3, 3)
    for y in range(3):
        for x in range(3):
            level.set_tile(x, y, Tile(terrain=Terrain.FLOOR))
    level.building_id = building_id
    return level


def _site_game(*, level: Level, surface: Level) -> Game:
    """A ``Game`` shell parked on a site, with a real ``HexWorld``
    clock and a stub ECS world exposing ``time_of_day``."""
    g = Game.__new__(Game)
    g.world_type = WorldType.HEXCRAWL
    g.hex_world = HexWorld(pack_id="test", seed=1, width=4, height=4)
    g.world = SimpleNamespace(time_of_day=None, query=lambda *a: [])
    g.level = level
    g._active_site = _StubSite(surface=surface)
    g._active_site_sub = None
    return g


# --- advances while in a site ------------------------------------


def test_one_turn_advances_a_sliver() -> None:
    surface = _floor_level(level_id="town_surface")
    g = _site_game(level=surface, surface=surface)
    g._advance_site_clock()
    # One segment is six hours; SITE_TURNS_PER_SEGMENT turns span it.
    expected_minutes = round(6 * 60 / SITE_TURNS_PER_SEGMENT)
    assert g.hex_world.hour * 60 + g.hex_world.minute == 6 * 60 + expected_minutes


def test_short_visit_stays_in_segment() -> None:
    surface = _floor_level(level_id="town_surface")
    g = _site_game(level=surface, surface=surface)
    for _ in range(SITE_TURNS_PER_SEGMENT - 1):
        g._advance_site_clock()
    assert g.hex_world.time is TimeOfDay.MORNING


def test_long_visit_crosses_segment() -> None:
    surface = _floor_level(level_id="town_surface")
    g = _site_game(level=surface, surface=surface)
    for _ in range(SITE_TURNS_PER_SEGMENT):
        g._advance_site_clock()
    assert g.hex_world.time is TimeOfDay.MIDDAY


def test_syncs_segment_onto_world() -> None:
    surface = _floor_level(level_id="town_surface")
    g = _site_game(level=surface, surface=surface)
    g._advance_site_clock()
    assert g.world.time_of_day is g.hex_world.time
    # Carry it past a boundary too.
    for _ in range(SITE_TURNS_PER_SEGMENT):
        g._advance_site_clock()
    assert g.world.time_of_day is TimeOfDay.MIDDAY


def test_drifts_inside_a_structure() -> None:
    surface = _floor_level(level_id="town_surface")
    building = _floor_level(
        level_id="town_b0_f0", building_id="town_b0", depth=1,
    )
    g = _site_game(level=building, surface=surface)
    g._advance_site_clock()
    assert g.hex_world.minute != 0  # clock moved


# --- no drift outside site / structure ---------------------------


def test_no_drift_on_dungeon_descent() -> None:
    """A descent under a town is the ``dungeon`` view -- no drift."""
    surface = _floor_level(level_id="town_surface")
    descent = _floor_level(level_id="town_descent_d2", depth=2)
    g = _site_game(level=descent, surface=surface)  # level != surface, no building_id
    g._advance_site_clock()
    assert g.hex_world.hour == 6 and g.hex_world.minute == 0
    assert g.world.time_of_day is None


def test_no_drift_without_active_site() -> None:
    surface = _floor_level(level_id="town_surface")
    g = _site_game(level=surface, surface=surface)
    g._active_site = None
    g._advance_site_clock()
    assert g.hex_world.hour == 6 and g.hex_world.minute == 0


def test_no_drift_in_overland_hex() -> None:
    g = Game.__new__(Game)
    g.world_type = WorldType.HEXCRAWL
    g.hex_world = HexWorld(pack_id="test", seed=1, width=4, height=4)
    g.hex_world.exploring_sub_hex = None
    g.world = SimpleNamespace(time_of_day=None, query=lambda *a: [])
    g.level = None
    g._active_site = None
    g._advance_site_clock()
    assert g.hex_world.hour == 6 and g.hex_world.minute == 0
