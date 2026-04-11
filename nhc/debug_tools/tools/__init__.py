"""Tool registry for nhc debug MCP server."""

from nhc.debug_tools.tools.autosave import GetAutosaveInfoTool
from nhc.debug_tools.tools.exports import ListExportsTool, ReadExportTool
from nhc.debug_tools.tools.game_state import (
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
from nhc.debug_tools.tools.svg_query import (
    GetSVGRoomWallsTool,
    GetSVGTileElementsTool,
)

ALL_TOOL_CLASSES = [
    GetAutosaveInfoTool,
    ListExportsTool,
    ReadExportTool,
    GetGameSnapshotTool,
    GetEntityListTool,
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
]
