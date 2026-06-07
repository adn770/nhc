"""Tests for GetWallCoverageTool against the v5 IR.

The tool reports wall coverage from the v5 ``StrokeOp`` stream:
per-treatment and per-substance-family counts plus a per-stroke
detail list (region_ref, treatment, family, style, outline_kind,
vertices/cuts counts). These tests pin the structural shape and the
counts the committed NIR5 fixtures produce.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhc.debug_tools.tools.ir_query import (
    _MATERIAL_FAMILY,
    _WALL_TREATMENT,
)

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
    """seed42 emits one StrokeOp per walled region (19 total), all
    Stone-family PlainStroke walls with polygon outlines."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(path=str(_FIXTURE_RECT))
    assert "error" not in result

    assert result["stroke_count"] == 19
    assert result["by_treatment"] == {"PlainStroke": 19}
    assert result["by_family"] == {"Stone": 19}

    strokes = result["strokes"]
    assert len(strokes) == 19
    assert all(s["outline_kind"] == "Polygon" for s in strokes)
    # Every stroke references a region present in the floor.
    assert all(s["region_ref"] for s in strokes)


@pytest.mark.asyncio
async def test_get_wall_coverage_seed7_octagon() -> None:
    """seed7_octagon (10 rect + 8 smooth rooms + corridor) emits 19
    StrokeOps."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(
        path=str(_FIXTURE_OCTAGON),
    )
    assert "error" not in result
    assert result["stroke_count"] == 19
    assert sum(result["by_treatment"].values()) == 19


@pytest.mark.asyncio
async def test_get_wall_coverage_seed99_cave() -> None:
    """seed99_cave has a single cave-merged StrokeOp."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(path=str(_FIXTURE_CAVE))
    assert "error" not in result

    assert result["stroke_count"] == 1
    stroke = result["strokes"][0]
    assert stroke["region_ref"] == "cave.0"
    assert stroke["outline_kind"] == "Polygon"


@pytest.mark.asyncio
async def test_get_wall_coverage_with_fixture_shortcut() -> None:
    """The tool accepts fixture=<name>, resolving to the same .nir as
    the path-based call."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(
        fixture="seed42_rect_dungeon_dungeon",
    )
    assert "error" not in result
    assert result["stroke_count"] == 19


@pytest.mark.asyncio
async def test_get_wall_coverage_enum_string_forms() -> None:
    """treatment / family / outline_kind are reported as enum name
    strings, not raw int values."""
    from nhc.debug_tools.tools.ir_query import GetWallCoverageTool
    result = await GetWallCoverageTool().execute(path=str(_FIXTURE_RECT))
    assert "error" not in result
    treatments = set(_WALL_TREATMENT.values())
    families = set(_MATERIAL_FAMILY.values())
    for s in result["strokes"]:
        assert s["outline_kind"] in ("Polygon", "Circle", "Pill")
        assert s["treatment"] in treatments
        assert s["family"] in families
