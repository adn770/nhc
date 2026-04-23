"""FOV radius scales up on outdoor site surfaces.

Site surfaces (town, keep, ruin, cottage, temple courtyards) feel
claustrophobic at the dungeon FOV radius — villagers wandering a
city visibly pop in and out at the FOV boundary. These levels are
flagged with ``LevelMetadata.prerevealed=True`` by the assemblers
and should use a substantially larger sight radius so NPCs stay on
screen at realistic open-air distances.
"""

from __future__ import annotations

from nhc.core.game import (
    FOV_RADIUS, FOV_RADIUS_SURFACE, _fov_radius_for_level,
)
from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile


def _blank_level(prerevealed: bool) -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(5)]
             for _ in range(5)]
    return Level(
        id="t", name="T", depth=0, width=5, height=5, tiles=tiles,
        metadata=LevelMetadata(prerevealed=prerevealed),
    )


def test_surface_radius_is_significantly_larger_than_dungeon():
    assert FOV_RADIUS_SURFACE > FOV_RADIUS * 2


def test_fov_radius_picks_surface_for_prerevealed_level():
    level = _blank_level(prerevealed=True)
    assert _fov_radius_for_level(level) == FOV_RADIUS_SURFACE


def test_fov_radius_picks_default_for_dungeon_level():
    level = _blank_level(prerevealed=False)
    assert _fov_radius_for_level(level) == FOV_RADIUS


def test_fov_radius_picks_default_for_level_without_metadata():
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(5)]
             for _ in range(5)]
    level = Level(id="t", name="T", depth=0, width=5, height=5,
                  tiles=tiles)
    level.metadata = None  # type: ignore[assignment]
    assert _fov_radius_for_level(level) == FOV_RADIUS
