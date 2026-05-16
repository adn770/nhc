"""Tests for the frozen RenderContext / build_render_context factory.

Phase 1 of the rendering refactor — see ``rendering_refactor_plan.md``.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import Level, Rect, Room
from nhc.rendering._render_context import (
    RenderContext,
    build_render_context,
)
from nhc.rendering.terrain_palette import THEME_PALETTES, get_palette


def _bare_level(
    *, building_id: str | None = None, theme: str = "dungeon",
    prerevealed: bool = False, interior_floor: str = "stone",
    cave: bool = False,
) -> Level:
    level = Level.create_empty("t", "t", 0, 4, 4)
    level.metadata.theme = theme
    level.metadata.prerevealed = prerevealed
    level.building_id = building_id
    level.interior_floor = interior_floor
    if cave:
        level.rooms.append(Room(
            id="r1",
            rect=Rect(0, 0, 2, 2),
            shape=CaveShape(tiles={(0, 0), (1, 0), (0, 1)}),
        ))
    return level


class TestVegetationGateRemoved:
    """The vegetation suppression gate was an SVG-size perf hack
    made obsolete by the browser WASM render path. Vegetation is
    now always emitted; the parameter and ctx flag are gone."""

    def test_build_render_context_has_no_vegetation_param(self) -> None:
        import inspect

        params = inspect.signature(build_render_context).parameters
        assert "vegetation" not in params

    def test_render_context_has_no_vegetation_enabled_field(self) -> None:
        import dataclasses

        fields = {f.name for f in dataclasses.fields(RenderContext)}
        assert "vegetation_enabled" not in fields


class TestFloorKindResolution:
    def test_dungeon_default(self) -> None:
        ctx = build_render_context(_bare_level(), seed=1)
        assert ctx.floor_kind == "dungeon"

    def test_building_wins_over_other_signals(self) -> None:
        # building_id beats prerevealed and cave shape.
        level = _bare_level(
            building_id="b1", prerevealed=True, cave=True,
        )
        ctx = build_render_context(level, seed=1)
        assert ctx.floor_kind == "building"

    def test_cave_when_any_room_has_caveshape(self) -> None:
        level = _bare_level(cave=True)
        ctx = build_render_context(level, seed=1)
        assert ctx.floor_kind == "cave"

    def test_surface_when_prerevealed_and_no_cave(self) -> None:
        level = _bare_level(prerevealed=True)
        ctx = build_render_context(level, seed=1)
        assert ctx.floor_kind == "surface"

    def test_cave_beats_prerevealed(self) -> None:
        # A cave room outranks the prerevealed flag.
        level = _bare_level(prerevealed=True, cave=True)
        ctx = build_render_context(level, seed=1)
        assert ctx.floor_kind == "cave"


class TestResolvedFlags:
    def test_dungeon_flags(self) -> None:
        ctx = build_render_context(_bare_level(), seed=0)
        assert ctx.shadows_enabled is True
        assert ctx.hatching_enabled is True
        assert ctx.atmospherics_enabled is True
        assert ctx.macabre_detail is True

    def test_building_disables_shadows_hatching_macabre(self) -> None:
        ctx = build_render_context(
            _bare_level(building_id="b1"), seed=0,
        )
        assert ctx.shadows_enabled is False
        assert ctx.hatching_enabled is False
        assert ctx.macabre_detail is False
        # Atmospherics (webs) stay on by default — buildings can be
        # dusty.
        assert ctx.atmospherics_enabled is True

    def test_surface_disables_hatching_keeps_shadows(self) -> None:
        # Site surfaces ship without hatching but still cast soft
        # shadows and accept atmospherics.
        ctx = build_render_context(
            _bare_level(prerevealed=True), seed=0,
        )
        assert ctx.shadows_enabled is True
        assert ctx.hatching_enabled is False
        assert ctx.macabre_detail is True

    def test_cave_keeps_all_flags(self) -> None:
        ctx = build_render_context(_bare_level(cave=True), seed=0)
        assert ctx.shadows_enabled is True
        assert ctx.hatching_enabled is True
        assert ctx.macabre_detail is True

    def test_interior_finish_default_stone(self) -> None:
        ctx = build_render_context(_bare_level(), seed=0)
        assert ctx.interior_finish == "stone"

    def test_interior_finish_wood(self) -> None:
        level = _bare_level(
            building_id="b1", interior_floor="wood",
        )
        ctx = build_render_context(level, seed=0)
        assert ctx.interior_finish == "wood"


class TestThemeAndPalette:
    def test_default_theme_dungeon(self) -> None:
        ctx = build_render_context(_bare_level(), seed=0)
        assert ctx.theme == "dungeon"
        assert ctx.palette is get_palette("dungeon")

    def test_known_theme_resolves_to_its_palette(self) -> None:
        level = _bare_level(theme="cave")
        ctx = build_render_context(level, seed=0)
        assert ctx.theme == "cave"
        assert ctx.palette is THEME_PALETTES["cave"]

    def test_unknown_theme_falls_back_to_dungeon(self) -> None:
        level = _bare_level(theme="not_a_theme")
        ctx = build_render_context(level, seed=0)
        assert ctx.theme == "not_a_theme"
        assert ctx.palette is THEME_PALETTES["dungeon"]


class TestBuildingGeometryPassthrough:
    def test_building_polygon_and_footprint_round_trip(self) -> None:
        footprint = {(1, 1), (1, 2), (2, 1)}
        polygon = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        ctx = build_render_context(
            _bare_level(building_id="b1"),
            seed=0,
            building_footprint=footprint,
            building_polygon=polygon,
        )
        assert ctx.building_footprint == frozenset(footprint)
        assert ctx.building_polygon == tuple(polygon)

    def test_no_building_geometry_when_none(self) -> None:
        ctx = build_render_context(_bare_level(), seed=0)
        assert ctx.building_footprint is None
        assert ctx.building_polygon is None


class TestImmutability:
    def test_context_is_frozen(self) -> None:
        ctx = build_render_context(_bare_level(), seed=0)
        with pytest.raises(FrozenInstanceError):
            ctx.theme = "other"  # type: ignore[misc]


class TestGeometryBuilderInjection:
    def test_cave_geometry_builder_called_with_level_and_rng(self) -> None:
        captured: dict = {}

        def builder(level, rng):
            captured["level"] = level
            captured["rng"] = rng
            return ("PATH", "POLY", {(1, 1)})

        level = _bare_level()
        ctx = build_render_context(
            level, seed=0, cave_geometry_builder=builder,
        )
        assert captured["level"] is level
        assert ctx.cave_wall_path == "PATH"
        assert ctx.cave_wall_poly == "POLY"
        assert ctx.cave_tiles == frozenset({(1, 1)})

    def test_dungeon_polygon_builder_receives_cave_inputs(self) -> None:
        captured: dict = {}

        def cave_builder(level, rng):
            return ("p", "POLY_OBJ", {(2, 2)})

        def poly_builder(level, *, cave_wall_poly, cave_tiles):
            captured["poly"] = cave_wall_poly
            captured["tiles"] = cave_tiles
            return "DUNGEON_POLY"

        ctx = build_render_context(
            _bare_level(),
            seed=0,
            cave_geometry_builder=cave_builder,
            dungeon_polygon_builder=poly_builder,
        )
        assert captured["poly"] == "POLY_OBJ"
        assert captured["tiles"] == {(2, 2)}
        assert ctx.dungeon_poly == "DUNGEON_POLY"

    def test_no_builders_yields_empty_geometry(self) -> None:
        ctx = build_render_context(_bare_level(), seed=0)
        assert ctx.cave_wall_path is None
        assert ctx.cave_wall_poly is None
        assert ctx.cave_tiles == frozenset()
        assert ctx.dungeon_poly is None
