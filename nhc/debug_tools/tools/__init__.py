"""Tool registry for nhc debug MCP server."""

from nhc.debug_tools.tools.autosave import GetAutosaveInfoTool
from nhc.debug_tools.tools.exports import ListExportsTool, ReadExportTool
from nhc.debug_tools.tools.game_state import (
    GetEntityComponentsTool,
    GetEntityListTool,
    GetGameSnapshotTool,
    GetHenchmanSheetsTool,
    GetTileInfoTool,
)
from nhc.debug_tools.tools.dungeon import (
    GetDoorAnalysisTool,
    GetRoomInfoTool,
    GetRoomTilesTool,
    GetTileMapTool,
    SearchTilesTool,
)
from nhc.debug_tools.tools.rendering import (
    GetFOVAnalysisTool,
    GetHatchPolygonTool,
    GetLayerStateTool,
)
from nhc.debug_tools.tools.hex_tools import (
    AdvanceDayClockTool,
    ClearDungeonAtTool,
    ForceEncounterTool,
    RevealAllHexesTool,
    SeedDungeonAtTool,
    SetRumorTruthTool,
    ShowWorldStateTool,
    TeleportHexTool,
)
from nhc.debug_tools.tools.svg_query import (
    GetSVGRoomWallsTool,
    GetSVGTileElementsTool,
)
from nhc.debug_tools.tools.ir_query import (
    GetIRBufferTool,
    GetIRDiffTool,
    GetIROpsTool,
    GetIRRegionTool,
    GetWallCoverageTool,
)

ALL_TOOL_CLASSES = [
    GetAutosaveInfoTool,
    ListExportsTool,
    ReadExportTool,
    GetGameSnapshotTool,
    GetEntityListTool,
    GetEntityComponentsTool,
    GetTileInfoTool,
    GetHenchmanSheetsTool,
    GetRoomInfoTool,
    GetRoomTilesTool,
    GetDoorAnalysisTool,
    GetTileMapTool,
    SearchTilesTool,
    GetFOVAnalysisTool,
    GetLayerStateTool,
    GetHatchPolygonTool,
    GetSVGTileElementsTool,
    GetSVGRoomWallsTool,
    # IR query tools (Phase 2.4 of plans/nhc_ir_migration_plan.md).
    GetIRBufferTool,
    GetIRRegionTool,
    GetIROpsTool,
    GetIRDiffTool,
    GetWallCoverageTool,
    # Hex-mode debug tools (M-4.1).
    ShowWorldStateTool,
    RevealAllHexesTool,
    TeleportHexTool,
    ForceEncounterTool,
    AdvanceDayClockTool,
    SetRumorTruthTool,
    ClearDungeonAtTool,
    SeedDungeonAtTool,
]
