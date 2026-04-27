"""Frozen render-context dataclass for the SVG floor pipeline.

Centralises floor-kind detection (dungeon / building / surface / cave)
and resolved feature flags (shadows, hatching, atmospherics, macabre
detail, interior finish) so every layer and decorator reads the same
state. Computed once at the top of :func:`render_floor_svg` and passed
down — no more scattered ``getattr(level, "building_id", None)`` and
``level.metadata.prerevealed`` checks across the renderer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from shapely.geometry import MultiPolygon, Polygon

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import Level
from nhc.rendering.terrain_palette import ThemePalette, get_palette


FloorKind = Literal["dungeon", "building", "surface", "cave"]


@dataclass(frozen=True)
class RenderContext:
    """Resolved state for one ``render_floor_svg`` invocation.

    Attributes are all immutable: built once by
    :func:`build_render_context` and read by every layer and
    decorator. Adding a new flag means one new field here and one
    resolution rule in the factory.
    """

    level: Level
    seed: int

    floor_kind: FloorKind

    # Geometry, computed once.
    cave_wall_path: str | None
    cave_wall_poly: Polygon | MultiPolygon | None
    cave_tiles: frozenset[tuple[int, int]]
    dungeon_poly: Polygon | MultiPolygon | None

    # Building-only geometry (None elsewhere).
    building_footprint: frozenset[tuple[int, int]] | None
    building_polygon: tuple[tuple[float, float], ...] | None

    theme: str
    palette: ThemePalette

    # Resolved feature flags — replace inverse gates.
    shadows_enabled: bool       # was: not is_building
    hatching_enabled: bool      # was: not is_building and not prerevealed
    atmospherics_enabled: bool  # webs (any non-surface level)
    macabre_detail: bool        # bones + skulls + scattered floor stones
    vegetation_enabled: bool    # tree + bush surface decorators
    interior_finish: str        # "stone" | "wood" | future finishes

    # Hatch distance (in tiles) applied to the dungeon halo. Cave
    # levels clamp to a minimum of 2.0 so the wider grey ring stays
    # part of the cavern look.
    hatch_distance: float = 2.0


def _resolve_floor_kind(level: Level) -> FloorKind:
    """Pick the floor kind from level data.

    Priority: building_id → building (interior architecture);
    any CaveShape room → cave; prerevealed metadata → surface;
    otherwise → dungeon.
    """
    if getattr(level, "building_id", None) is not None:
        return "building"
    if any(isinstance(r.shape, CaveShape) for r in level.rooms):
        return "cave"
    if level.metadata is not None and level.metadata.prerevealed:
        return "surface"
    return "dungeon"


def build_render_context(
    level: Level,
    *,
    seed: int,
    cave_rng: random.Random | None = None,
    dungeon_polygon_builder=None,
    cave_geometry_builder=None,
    building_footprint: set[tuple[int, int]] | None = None,
    building_polygon: list[tuple[float, float]] | None = None,
    hatch_distance: float = 2.0,
    vegetation: bool = True,
) -> RenderContext:
    """Build a :class:`RenderContext` for a level.

    The ``*_builder`` callables let the orchestrator inject the
    existing geometry helpers without forcing a circular import on
    this module.

    ``cave_geometry_builder(level, rng) -> (svg_path, poly, tiles)``
    matches :func:`_build_cave_wall_geometry`.

    ``dungeon_polygon_builder(level, *, cave_wall_poly, cave_tiles)``
    matches :func:`_build_dungeon_polygon`.
    """
    floor_kind = _resolve_floor_kind(level)
    theme = (
        level.metadata.theme
        if level.metadata is not None
        else "dungeon"
    )
    palette = get_palette(theme)

    rng = cave_rng or random.Random(seed + 0x5A17E5)
    if cave_geometry_builder is not None:
        cave_wall_path, cave_wall_poly, cave_tiles = (
            cave_geometry_builder(level, rng)
        )
    else:
        cave_wall_path, cave_wall_poly, cave_tiles = None, None, set()

    if dungeon_polygon_builder is not None:
        dungeon_poly = dungeon_polygon_builder(
            level,
            cave_wall_poly=cave_wall_poly,
            cave_tiles=cave_tiles,
        )
    else:
        dungeon_poly = None

    is_building = floor_kind == "building"
    is_surface = floor_kind == "surface"

    # Inverse gates resolved once. Match the existing scattered
    # checks in svg.py / _floor_detail.py exactly so Phase 1 is a
    # pure rename of conditions.
    shadows_enabled = not is_building
    hatching_enabled = not is_building and not is_surface
    atmospherics_enabled = True
    macabre_detail = not is_building

    interior_finish = getattr(level, "interior_floor", "stone")

    if floor_kind == "cave":
        hatch_distance = max(hatch_distance, 2.0)

    return RenderContext(
        level=level,
        seed=seed,
        floor_kind=floor_kind,
        cave_wall_path=cave_wall_path,
        cave_wall_poly=cave_wall_poly,
        cave_tiles=frozenset(cave_tiles),
        dungeon_poly=dungeon_poly,
        building_footprint=(
            frozenset(building_footprint)
            if building_footprint is not None
            else None
        ),
        building_polygon=(
            tuple((float(x), float(y)) for x, y in building_polygon)
            if building_polygon is not None
            else None
        ),
        theme=theme,
        palette=palette,
        shadows_enabled=shadows_enabled,
        hatching_enabled=hatching_enabled,
        atmospherics_enabled=atmospherics_enabled,
        macabre_detail=macabre_detail,
        vegetation_enabled=vegetation,
        interior_finish=interior_finish,
        hatch_distance=hatch_distance,
    )
