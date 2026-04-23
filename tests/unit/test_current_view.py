"""Classifier: ``Game.current_view`` returns one of five view names.

See ``design/views.md`` for the authoritative definition. This
test pins every branch of the classifier so downstream callers
(server-side view signalling, client toolbar dispatch, input
gating) can trust the return value without re-deriving it.

The test uses a minimal hand-built ``Game`` instance rather than
``initialize()`` so each view shape is set up explicitly and in
isolation. ``Game.current_view`` is a pure function of
``world_type``, ``hex_world``, ``level``, ``_active_site`` -- no
other dependencies required.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile
from nhc.hexcrawl.coords import HexCoord


class _StubHexWorld:
    """Minimal stand-in for :class:`HexWorld` -- only
    ``exploring_sub_hex`` is read by the classifier."""

    def __init__(self, exploring_sub_hex=None):
        self.exploring_sub_hex = exploring_sub_hex


class _StubSite:
    """Minimal stand-in for a :class:`Site`. The classifier only
    reads :attr:`surface`."""

    def __init__(self, surface):
        self.surface = surface


def _floor_level(
    *, building_id: str | None = None, level_id: str = "lvl",
    depth: int = 0,
) -> Level:
    """Build a tiny 3x3 floor level with the given metadata.
    Sidesteps ``create_empty`` defaults we don't care about."""
    level = Level.create_empty(level_id, level_id, depth, 3, 3)
    for y in range(3):
        for x in range(3):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.building_id = building_id
    return level


def _game_shell() -> Game:
    """Return a ``Game`` with its attributes zeroed out -- no
    ``__init__`` call, so we don't drag in ECS / renderer /
    registry machinery just to read ``current_view``."""
    g = Game.__new__(Game)
    g.world_type = None
    g.hex_world = None
    g.level = None
    g._active_site = None
    return g


# --- hex / flower -------------------------------------------------


def test_hexcrawl_overland_returns_hex() -> None:
    from nhc.hexcrawl.mode import WorldType

    g = _game_shell()
    g.world_type = WorldType.HEXCRAWL
    g.hex_world = _StubHexWorld(exploring_sub_hex=None)
    g.level = None
    assert g.current_view() == "hex"


def test_hexcrawl_flower_mode_returns_flower() -> None:
    from nhc.hexcrawl.mode import WorldType

    g = _game_shell()
    g.world_type = WorldType.HEXCRAWL
    g.hex_world = _StubHexWorld(
        exploring_sub_hex=HexCoord(0, 0),
    )
    g.level = None
    assert g.current_view() == "flower"


def test_dungeon_mode_with_no_level_falls_back_to_hex() -> None:
    """Defensive default -- dungeon-only games shouldn't normally
    hit a ``level is None`` state, but the classifier must not
    explode if they do."""
    from nhc.hexcrawl.mode import WorldType

    g = _game_shell()
    g.world_type = WorldType.DUNGEON
    g.level = None
    assert g.current_view() == "hex"


# --- tile-layer views: site / structure / dungeon ----------------


def test_site_surface_returns_site() -> None:
    from nhc.hexcrawl.mode import WorldType

    surface = _floor_level(level_id="keep_surface")
    g = _game_shell()
    g.world_type = WorldType.HEXCRAWL
    g.level = surface
    g._active_site = _StubSite(surface=surface)
    assert g.current_view() == "site"


def test_building_floor_returns_structure() -> None:
    from nhc.hexcrawl.mode import WorldType

    surface = _floor_level(level_id="keep_surface")
    building_floor = _floor_level(
        level_id="keep_b0_f0",
        building_id="keep_b0",
        depth=1,
    )
    g = _game_shell()
    g.world_type = WorldType.HEXCRAWL
    g.level = building_floor
    g._active_site = _StubSite(surface=surface)
    assert g.current_view() == "structure"


def test_standalone_dungeon_returns_dungeon() -> None:
    """Pure dungeon-mode game (no hex world, no site)."""
    from nhc.hexcrawl.mode import WorldType

    dungeon = _floor_level(level_id="d1", depth=1)
    g = _game_shell()
    g.world_type = WorldType.DUNGEON
    g.level = dungeon
    assert g.current_view() == "dungeon"


def test_site_descent_returns_dungeon() -> None:
    """Descending from a site (via a building's stairs down)
    leaves ``_active_site`` set and ``level.building_id`` unset
    -- the classifier treats this as a dungeon."""
    from nhc.hexcrawl.mode import WorldType

    surface = _floor_level(level_id="town_surface")
    descent = _floor_level(level_id="town_descent_d2", depth=2)
    g = _game_shell()
    g.world_type = WorldType.HEXCRAWL
    g.level = descent
    g._active_site = _StubSite(surface=surface)
    assert g.current_view() == "dungeon"


def test_returns_valid_view_name_always() -> None:
    """Whatever shape the game is in, the classifier must return
    one of the five canonical names -- no ``None``, no
    ``"unknown"``."""
    valid = {"hex", "flower", "site", "structure", "dungeon"}
    g = _game_shell()
    # Totally zeroed-out shell still classifies.
    assert g.current_view() in valid
