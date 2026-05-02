"""Tests for GetWallCoverageTool (Phase 2.4 of nhc_ir_migration_plan.md).

Exercises legacy field extraction, new-op summary, and the fixture
shortcut that all IR tools share.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "floor_ir"
)
_FIXTURE_RECT = _FIXTURE_ROOT / "seed42_rect_dungeon_dungeon" / "floor.nir"
_FIXTURE_OCTAGON = _FIXTURE_ROOT / "seed7_octagon_crypt_dungeon" / "floor.nir"
_FIXTURE_CAVE = _FIXTURE_ROOT / "seed99_cave_cave_cave" / "floor.nir"


@pytest.mark.asyncio
async def test_get_wall_coverage_seed42_summary() -> None:
    """seed42 emits 18 DungeonInk ExteriorWallOps + a 165-tile
    CorridorWallOp; legacy ``wall_segments`` is empty after Phase 1.19.
    """
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(path=str(_FIXTURE_RECT))
    assert "error" not in result

    legacy = result["legacy"]
    # Phase 1.19: every legacy wall counter on the WallsAndFloorsOp
    # is empty for fresh IR; only `cave_region_present` may stay true
    # for fixtures with cave content (none here).
    assert legacy["wall_segments_count"] == 0
    assert legacy["smooth_walls_count"] == 0
    assert legacy["wall_extensions_d_chars"] == 0
    assert legacy["cave_region_present"] is False

    new = result["new"]
    ext_walls = new["exterior_walls"]
    assert len(ext_walls) == 18
    assert all(w["style"] == "DungeonInk" for w in ext_walls)
    assert all(w["outline_kind"] == "Polygon" for w in ext_walls)

    corridor = new["corridor_wall_op"]
    assert corridor["tiles_count"] == 165
    assert corridor["style"] == "DungeonInk"

    assert new["interior_walls"] == []

    by_style = result["by_style"]
    assert by_style["DungeonInk"] == 18


@pytest.mark.asyncio
async def test_get_wall_coverage_seed7_octagon_smooth() -> None:
    """seed7_octagon emits 18 ExteriorWallOps (10 rect + 8 smooth);
    legacy ``smooth_walls`` / ``wall_segments`` are empty after 1.19.
    """
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(
        path=str(_FIXTURE_OCTAGON),
    )
    assert "error" not in result

    legacy = result["legacy"]
    assert legacy["smooth_walls_count"] == 0
    assert legacy["wall_segments_count"] == 0

    new = result["new"]
    assert len(new["exterior_walls"]) == 18


@pytest.mark.asyncio
async def test_get_wall_coverage_seed99_cave() -> None:
    """seed99_cave has 1 cave-merged ExteriorWallOp with CaveInk."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(path=str(_FIXTURE_CAVE))
    assert "error" not in result

    legacy = result["legacy"]
    assert legacy["wall_segments_count"] == 0
    # Phase 1.19 cleared `caveRegion` along with the other legacy
    # fields; cave geometry now lives on FloorOp.outline.vertices.
    assert legacy["cave_region_present"] is False

    new = result["new"]
    ext_walls = new["exterior_walls"]
    assert len(ext_walls) == 1
    assert ext_walls[0]["style"] == "CaveInk"
    assert ext_walls[0]["outline_kind"] == "Polygon"

    # No corridor in a pure cave
    assert new["corridor_wall_op"] is None

    by_style = result["by_style"]
    assert by_style.get("CaveInk", 0) == 1
    assert by_style.get("DungeonInk", 0) == 0


@pytest.mark.asyncio
async def test_get_wall_coverage_with_fixture_shortcut() -> None:
    """The tool accepts fixture=<name>; legacy counters all zero
    after Phase 1.19."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(
        fixture="seed42_rect_dungeon_dungeon",
    )
    assert "error" not in result
    assert result["legacy"]["wall_segments_count"] == 0
    # New ops are still populated: the shortcut path resolves to the
    # same .nir as the path-based call above.
    assert len(result["new"]["exterior_walls"]) == 18


@pytest.mark.asyncio
async def test_get_wall_coverage_outline_kind_string_form() -> None:
    """outline_kind is reported as 'Polygon' / 'Circle' / 'Pill',
    not the int enum value."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(path=str(_FIXTURE_RECT))
    assert "error" not in result
    ext_walls = result["new"]["exterior_walls"]
    for w in ext_walls:
        assert isinstance(w["outline_kind"], str)
        assert w["outline_kind"] in ("Polygon", "Circle", "Pill")
