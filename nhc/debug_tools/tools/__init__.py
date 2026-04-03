"""Tool registry for nhc debug MCP server."""

from nhc.debug_tools.tools.exports import ListExportsTool, ReadExportTool
from nhc.debug_tools.tools.game_state import (
    GetEntityListTool,
    GetGameSnapshotTool,
    GetTileInfoTool,
)
from nhc.debug_tools.tools.dungeon import (
    GetDoorAnalysisTool,
    GetRoomInfoTool,
    GetTileMapTool,
    SearchTilesTool,
)
from nhc.debug_tools.tools.rendering import (
    GetFOVAnalysisTool,
    GetLayerStateTool,
)
from nhc.debug_tools.tools.svg_query import (
    GetSVGTileElementsTool,
)

ALL_TOOL_CLASSES = [
    ListExportsTool,
    ReadExportTool,
    GetGameSnapshotTool,
    GetEntityListTool,
    GetTileInfoTool,
    GetRoomInfoTool,
    GetDoorAnalysisTool,
    GetTileMapTool,
    SearchTilesTool,
    GetFOVAnalysisTool,
    GetLayerStateTool,
    GetSVGTileElementsTool,
]
