"""Tools for analyzing rendering state from exports."""

from __future__ import annotations

from typing import Any

from nhc.debug_tools.base import BaseTool


class GetFOVAnalysisTool(BaseTool):
    name = "get_fov_analysis"
    description = (
        "Analyze FOV state: visible/explored tile counts, "
        "perimeter tiles, and coverage percentages."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        layer = self._read_json_export("layer_state")
        if "error" in layer:
            return layer
        debug = layer.get("debug", {})
        fov = layer.get("fov", [])
        explored = layer.get("explored", [])
        w = debug.get("map_width", 0)
        h = debug.get("map_height", 0)
        total = w * h

        # Find perimeter tiles (visible with non-visible neighbor)
        fov_set = {(t[0], t[1]) for t in fov}
        perimeter = []
        for x, y in fov_set:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                if (x + dx, y + dy) not in fov_set:
                    perimeter.append([x, y])
                    break

        return {
            "visible_tiles": len(fov),
            "explored_tiles": len(explored),
            "total_tiles": total,
            "visible_pct": round(
                len(fov) / total * 100, 1) if total else 0,
            "explored_pct": round(
                len(explored) / total * 100, 1) if total else 0,
            "perimeter_tiles": len(perimeter),
            "fov_radius": debug.get("fov_radius", 8),
            "map_dimensions": {"width": w, "height": h},
        }


class GetLayerStateTool(BaseTool):
    name = "get_layer_state"
    description = (
        "Get the full rendering layer state including FOV, "
        "explored tiles, doors, and debug overlay data."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        layer = self._read_json_export("layer_state")
        if "error" in layer:
            return layer
        return {
            "turn": layer.get("turn"),
            "timestamp": layer.get("timestamp"),
            "visible_count": len(layer.get("fov", [])),
            "explored_count": len(layer.get("explored", [])),
            "door_count": len(layer.get("doors", [])),
            "rooms": len(
                layer.get("debug", {}).get("rooms", [])),
            "corridors": len(
                layer.get("debug", {}).get("corridors", [])),
            "debug_doors": len(
                layer.get("debug", {}).get("doors", [])),
        }


class GetHatchPolygonTool(BaseTool):
    name = "get_hatch_polygon"
    description = (
        "Query the clearHatch debug snapshot: walkable tile "
        "set with wall masks, raw tile-perimeter loops, the "
        "2px-expanded offset loops, and per-tile detail for "
        "every door tile and its orthogonal neighbours."
    )
    parameters = {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["summary", "loops", "doors", "full"],
                "description": (
                    "summary (default) returns counts only; "
                    "loops adds the raw + expanded loop "
                    "geometry; doors adds the door "
                    "neighbourhood detail; full returns "
                    "everything including the walls list."
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        hatch = self._read_json_export("hatch_debug")
        if "error" in hatch:
            return hatch
        detail = kwargs.get("detail", "summary")

        raw_loops = hatch.get("loops_raw", [])
        expanded = hatch.get("loops_expanded", [])
        result: dict[str, Any] = {
            "turn": hatch.get("turn"),
            "timestamp": hatch.get("timestamp"),
            "cell_size": hatch.get("cell_size"),
            "padding": hatch.get("padding"),
            "offset_px": hatch.get("offset_px"),
            "tile_count": hatch.get("tile_count"),
            "loop_count": hatch.get("loop_count"),
            "loop_edges": [len(loop) for loop in raw_loops],
            "expanded_vertices": [len(loop) for loop in expanded],
            "door_tile_count": sum(
                1 for e in hatch.get("door_neighbourhood", [])
                if e.get("is_door")
            ),
            "door_neighbourhood_count": len(
                hatch.get("door_neighbourhood", [])
            ),
        }
        if detail in ("loops", "full"):
            result["loops_raw"] = raw_loops
            result["loops_expanded"] = expanded
        if detail in ("doors", "full"):
            result["door_neighbourhood"] = hatch.get(
                "door_neighbourhood", [])
        if detail == "full":
            result["walls"] = hatch.get("walls", [])
        return result
