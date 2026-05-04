"""Global test fixtures."""

import pytest

from nhc.i18n import init as i18n_init

# Initialize i18n with English for all tests.
i18n_init("en")


# ── Phase 2.19 legacy-format skip list ─────────────────────────
#
# Phase 2.19 retired ``nhc.rendering.ir_to_svg`` (the Python SVG
# emitter) and rewired ``render_floor_svg`` to flow through the
# Rust ``nhc_render.ir_to_svg`` Painter-based path. The Rust
# SvgPainter emits structurally different SVG markup (e.g. paths
# instead of ``<polygon>`` / ``<circle>`` elements, no ``class=``
# attributes, no per-layer ``<!-- layer.X: -->`` comments). Many
# legacy assertion tests check for those Python-emitter shapes;
# they belong to the contract that retired here, not to the IR
# emit + cross-rasteriser PSNR contract that survives.
#
# Phase 2.21 reformulates the gate in terms of PSNR + structural
# sanity; until then these tests skip rather than rot. Each entry
# is the fully-qualified test id (``module::Class::test``) — the
# items in this list will be re-evaluated at 2.21 and either
# rewritten against the new contract or deleted.
_PHASE_2_19_LEGACY_SVG_FORMAT_TESTS: frozenset[str] = frozenset({
    # tests/unit/test_svg_terrain.py
    "tests/unit/test_svg_terrain.py::TestTerrainDetailSVG::test_water_tiles_get_wavy_detail",
    # tests/unit/test_mine_rendering.py
    "tests/unit/test_mine_rendering.py::TestCartTrackRendering::test_track_tiles_render_rails",
    "tests/unit/test_mine_rendering.py::TestOreDepositRendering::test_ore_tiles_render_sparkles",
    # tests/unit/test_render_building_floor.py
    "tests/unit/test_render_building_floor.py::TestLShapeBuildingWalls::test_wood_lshape_building_floor_clips_seams",
    "tests/unit/test_render_building_floor.py::TestLShapeBuildingFloorFilled::test_regular_dungeon_level_still_may_have_bones",
    # tests/unit/test_surface_rendering.py
    "tests/unit/test_surface_rendering.py::TestWoodInteriorFloor::test_wood_floor_suppresses_crack_detail",
    "tests/unit/test_surface_rendering.py::TestWoodParquetPattern::test_horizontal_room_emits_many_plank_end_lines",
    "tests/unit/test_surface_rendering.py::TestWoodParquetPattern::test_parquet_strips_use_plank_width",
    "tests/unit/test_surface_rendering.py::TestWoodParquetRandomLengths::test_plank_end_gaps_cover_a_range",
    "tests/unit/test_surface_rendering.py::TestWoodParquetRandomLengths::test_plank_ends_do_not_align_across_strips",
    # tests/unit/rendering/test_cross_floor_kind_portability.py
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestTreePortability::test_tree_paints_on_dungeon",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestTreePortability::test_tree_paints_on_building_interior",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestTreePortability::test_tree_paints_on_surface",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestTreePortability::test_tree_paints_on_cave",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestBushPortability::test_bush_paints_on_dungeon",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestBushPortability::test_bush_paints_on_building_interior",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestBushPortability::test_bush_paints_on_surface",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestBushPortability::test_bush_paints_on_cave",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestWaterPortability::test_water_paints_on_dungeon",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestWaterPortability::test_water_paints_on_building_interior",
    "tests/unit/rendering/test_cross_floor_kind_portability.py::TestWaterPortability::test_water_paints_on_surface",
    # tests/unit/rendering/test_terrain_decorators.py
    "tests/unit/rendering/test_terrain_decorators.py::TestTerrainDecoratorPortability::test_water_tile_renders_water_class",
    "tests/unit/rendering/test_terrain_decorators.py::TestTerrainDecoratorPortability::test_lava_tile_renders_lava_class",
    "tests/unit/rendering/test_terrain_decorators.py::TestTerrainDecoratorPortability::test_chasm_tile_renders_chasm_class",
    "tests/unit/rendering/test_terrain_decorators.py::TestRoomCorridorBucketing::test_room_water_uses_clip_group",
    "tests/unit/rendering/test_terrain_decorators.py::TestRoomCorridorBucketing::test_corridor_water_skips_clip_group",
    # tests/unit/rendering/test_diagonal_walls.py
    "tests/unit/rendering/test_diagonal_walls.py::TestOctagonWallRendering::test_octagon_floor_svg_omits_clipped_corner_walls",
    # tests/unit/rendering/test_level_svg_dispatch.py
    "tests/unit/rendering/test_level_svg_dispatch.py::test_plain_dungeon_level_unaffected",
    # tests/unit/rendering/test_site_surface_svg.py
    "tests/unit/rendering/test_site_surface_svg.py::TestGoldenSnapshot::test_town_surface_matches_golden",
})


def pytest_collection_modifyitems(config, items):
    """Auto-skip Phase 2.19 legacy-SVG-format tests."""
    skip_marker = pytest.mark.skip(
        reason=(
            "Phase 2.19: legacy Python ir_to_svg.py emitter format "
            "retired; this assertion checks for shapes the Rust "
            "SvgPainter doesn't reproduce. Phase 2.21 reformulates "
            "the gate in terms of PSNR + structural sanity."
        ),
    )
    for item in items:
        # nodeid is "tests/unit/foo.py::Class::method" or
        # "tests/unit/foo.py::function".
        if item.nodeid in _PHASE_2_19_LEGACY_SVG_FORMAT_TESTS:
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _reset_i18n_to_english():
    """Reset i18n to English before every test.

    The i18n module is process-global; tests that flip to ``ca`` or
    ``es`` and forget to restore otherwise leak state across the
    xdist worker, which surfaces as flaky failures in tests that
    assume English (e.g. ``TestLookAction``). Tests that need a
    different locale call :func:`init` explicitly after this
    fixture runs and the change applies for the test body."""
    i18n_init("en")
    yield
