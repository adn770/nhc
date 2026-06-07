"""Phase 2.4 of plans/nhc_ir_migration_plan.md — IR-aware MCP tools.

Each tool reads a FloorIR FlatBuffer (defaulting to the latest
``floor_ir_*.nir`` under ``debug/exports/``) and answers structural
queries via the canonical dump produced by ``nhc.rendering.ir.dump``.
The tests pass an explicit ``path=`` to the committed fixture so
they don't depend on the export directory being populated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "floor_ir"
)
_FIXTURE_RECT = _FIXTURE_ROOT / "seed42_rect_dungeon_dungeon" / "floor.nir"
_FIXTURE_CAVE = _FIXTURE_ROOT / "seed99_cave_cave_cave" / "floor.nir"


@pytest.mark.asyncio
async def test_get_ir_buffer_returns_metadata() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRBufferTool
    result = await GetIRBufferTool().execute(path=str(_FIXTURE_RECT))
    assert "error" not in result
    assert result["major"] == 5
    assert result["minor"] >= 0
    # v5 regions for the seed42 fixture: 1 dungeon + 1 corridor +
    # 17 rooms + 1 vault + 5 water = 25.
    assert result["region_count"] == 25
    # v5 op stream for the seed42 fixture: ShadowOp 19, PaintOp 24,
    # StrokeOp 19, StampOp 9, FixtureOp 5, HatchOp 2 = 78.
    assert result["op_count"] == 78
    assert result["size_bytes"] > 0
    assert result["file_identifier"] == "NIR5"
    assert "dump" not in result  # off by default


@pytest.mark.asyncio
async def test_get_ir_buffer_includes_dump_when_requested() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRBufferTool
    result = await GetIRBufferTool().execute(
        path=str(_FIXTURE_RECT), include_dump=True,
    )
    assert "dump" in result
    parsed = json.loads(result["dump"])
    assert "regions" in parsed
    assert "ops" in parsed


@pytest.mark.asyncio
async def test_get_ir_buffer_missing_file_errors(tmp_path) -> None:
    from nhc.debug_tools.tools.ir_query import GetIRBufferTool
    result = await GetIRBufferTool().execute(
        path=str(tmp_path / "nope.nir"),
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_get_ir_region_lists_all_when_no_id() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRRegionTool
    result = await GetIRRegionTool().execute(path=str(_FIXTURE_RECT))
    assert "regions" in result
    # 1 dungeon + 1 corridor + 17 rooms + 1 vault + 5 water = 25.
    assert len(result["regions"]) == 25
    sample = result["regions"][0]
    # v5 regions carry no `kind`; the listing exposes id +
    # shape_tag + parent_id (tooling infers role from the id).
    assert "id" in sample and "shape_tag" in sample
    # Outline geometry is suppressed in the listing to keep the
    # response under MCP's payload budget; callers ask by id for
    # the full geometry.
    assert "outline" not in sample


@pytest.mark.asyncio
async def test_get_ir_region_returns_specific() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRRegionTool
    result = await GetIRRegionTool().execute(
        path=str(_FIXTURE_RECT), region_id="dungeon",
    )
    assert result["region"]["id"] == "dungeon"
    # v5 regions have no `kind`; fetching by id returns the full
    # record including its outline geometry.
    assert "outline" in result["region"]
    assert "shapeTag" in result["region"]


@pytest.mark.asyncio
async def test_get_ir_region_unknown_id_errors() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRRegionTool
    result = await GetIRRegionTool().execute(
        path=str(_FIXTURE_RECT), region_id="no-such-region",
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_get_ir_ops_summary() -> None:
    from nhc.debug_tools.tools.ir_query import GetIROpsTool
    result = await GetIROpsTool().execute(path=str(_FIXTURE_RECT))
    assert "summary" in result
    assert result["total"] == 78
    assert sum(result["summary"].values()) == 78
    assert "ShadowOp" in result["summary"]
    # v5 paints surfaces with PaintOp (24 in the seed42 fixture)
    # rather than the retired v4 FloorOp.
    assert result["summary"].get("PaintOp") == 24
    # v5 walls are StrokeOps (19 here) rather than the retired v4
    # ExteriorWallOp / CorridorWallOp.
    assert result["summary"].get("StrokeOp") == 19


@pytest.mark.asyncio
async def test_get_ir_ops_filtered_by_kind() -> None:
    from nhc.debug_tools.tools.ir_query import GetIROpsTool
    result = await GetIROpsTool().execute(
        path=str(_FIXTURE_RECT), kind="ShadowOp",
    )
    assert result["kind"] == "ShadowOp"
    assert result["count"] >= 1
    assert all(o["opType"] == "ShadowOp" for o in result["ops"])


@pytest.mark.asyncio
async def test_get_ir_ops_unknown_kind_returns_empty() -> None:
    from nhc.debug_tools.tools.ir_query import GetIROpsTool
    result = await GetIROpsTool().execute(
        path=str(_FIXTURE_RECT), kind="NotAnOp",
    )
    assert result["kind"] == "NotAnOp"
    assert result["count"] == 0
    assert result["ops"] == []


@pytest.mark.asyncio
async def test_get_ir_diff_no_changes_when_same_file() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRDiffTool
    result = await GetIRDiffTool().execute(
        before=str(_FIXTURE_RECT), after=str(_FIXTURE_RECT),
    )
    assert result["regions_added"] == []
    assert result["regions_removed"] == []
    assert result["ops_added"] == 0
    assert result["ops_removed"] == 0


@pytest.mark.asyncio
async def test_get_ir_diff_detects_changes() -> None:
    from nhc.debug_tools.tools.ir_query import GetIRDiffTool
    result = await GetIRDiffTool().execute(
        before=str(_FIXTURE_RECT), after=str(_FIXTURE_CAVE),
    )
    # Rect dungeon has 25 regions (room_*/vault_*/water.*); cave has
    # 9 (cave_*). Diff must surface region churn on both sides and a
    # non-zero net op delta, otherwise the tool isn't comparing.
    assert len(result["regions_removed"]) > 0
    assert len(result["regions_added"]) > 0
    assert result["ops_removed"] > 0
    # ShadowOp drops 19 → 7 between dungeon and cave; surface this
    # specifically so a future regression in the per-kind breakdown
    # is caught.
    assert result["ops_net_per_kind"].get("ShadowOp", 0) < 0


# ---------------------------------------------------------------------------
# Fixture shortcut tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_shortcut_resolves_to_correct_path() -> None:
    """get_ir_buffer(fixture='seed42_rect_dungeon_dungeon') reads
    the seed42 fixture's .nir, not debug/exports."""
    from nhc.debug_tools.tools.ir_query import GetIRBufferTool
    result = await GetIRBufferTool().execute(
        fixture="seed42_rect_dungeon_dungeon",
    )
    assert "error" not in result
    assert result["major"] == 5
    assert result["op_count"] == 78
    assert "seed42_rect_dungeon_dungeon" in result["path"]


@pytest.mark.asyncio
async def test_fixture_shortcut_unknown_fixture_lists_available() -> None:
    """An unknown fixture name returns an error listing the
    available fixture directory names."""
    from nhc.debug_tools.tools.ir_query import GetIRBufferTool
    result = await GetIRBufferTool().execute(fixture="no_such_fixture")
    assert "error" in result
    assert "no_such_fixture" in result["error"]
    assert "available" in result
    assert "seed42_rect_dungeon_dungeon" in result["available"]


@pytest.mark.asyncio
async def test_get_ir_diff_accepts_fixture_before_after() -> None:
    """fixture_before='X' + fixture_after='Y' resolves both."""
    from nhc.debug_tools.tools.ir_query import GetIRDiffTool
    result = await GetIRDiffTool().execute(
        fixture_before="seed42_rect_dungeon_dungeon",
        fixture_after="seed99_cave_cave_cave",
    )
    assert "error" not in result
    assert len(result["regions_removed"]) > 0
    assert len(result["regions_added"]) > 0
