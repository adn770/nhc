"""Tools for querying dungeon structure from exports."""

from __future__ import annotations

from typing import Any

from nhc.debug_tools.base import BaseTool


class GetRoomInfoTool(BaseTool):
    name = "get_room_info"
    description = (
        "Get detailed information about a specific room from "
        "the most recent layer_state export."
    )
    parameters = {
        "type": "object",
        "properties": {
            "room_index": {
                "type": "integer",
                "description": "Room index (from debug overlay)",
            },
        },
        "required": ["room_index"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        idx = kwargs["room_index"]
        layer = self._read_json_export("layer_state")
        if "error" in layer:
            return layer
        debug = layer.get("debug", {})
        rooms = debug.get("rooms", [])
        if idx < 0 or idx >= len(rooms):
            return {"error": f"Room index {idx} out of range "
                    f"(0-{len(rooms) - 1})"}
        room = rooms[idx]
        # Find doors adjacent to this room
        doors = debug.get("doors", [])
        rx, ry = room["x"], room["y"]
        rw, rh = room["w"], room["h"]
        room_doors = [
            d for d in doors
            if (rx - 1 <= d["x"] <= rx + rw
                and ry - 1 <= d["y"] <= ry + rh)
        ]
        return {
            "room": room,
            "doors": room_doors,
            "door_count": len(room_doors),
        }


class GetDoorAnalysisTool(BaseTool):
    name = "get_door_analysis"
    description = (
        "Analyze all doors in the dungeon: positions, states, "
        "and counts by type."
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
        doors = debug.get("doors", [])
        counts: dict[str, int] = {}
        for d in doors:
            kind = d.get("kind", "?")
            counts[kind] = counts.get(kind, 0) + 1
        return {
            "doors": doors,
            "total": len(doors),
            "by_type": counts,
            "legend": {
                "C": "closed", "O": "open",
                "S": "secret", "L": "locked",
            },
        }


class SearchTilesTool(BaseTool):
    name = "search_tiles"
    description = (
        "Search for tiles matching criteria (terrain, feature, "
        "visibility) from the most recent game_state export."
    )
    parameters = {
        "type": "object",
        "properties": {
            "terrain": {
                "type": "string",
                "description": "Terrain type (FLOOR, WALL, VOID, "
                               "WATER)",
            },
            "feature": {
                "type": "string",
                "description": "Feature (door_secret, door_closed, "
                               "stairs_up, etc.)",
            },
            "explored": {
                "type": "boolean",
                "description": "Filter by explored state",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 50)",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        game = self._read_json_export("game_state")
        if "error" in game:
            return game
        tiles = game.get("level", {}).get("tiles", [])
        terrain_filter = kwargs.get("terrain")
        feature_filter = kwargs.get("feature")
        explored_filter = kwargs.get("explored")
        limit = kwargs.get("limit", 50)

        results = []
        for y, row in enumerate(tiles):
            for x, tile in enumerate(row):
                if terrain_filter and tile.get(
                        "terrain") != terrain_filter:
                    continue
                if feature_filter and tile.get(
                        "feature") != feature_filter:
                    continue
                if (explored_filter is not None
                        and tile.get("explored") != explored_filter):
                    continue
                results.append({
                    "x": x, "y": y,
                    "terrain": tile.get("terrain"),
                    "feature": tile.get("feature"),
                    "explored": tile.get("explored", False),
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        return {"tiles": results, "count": len(results),
                "truncated": len(results) >= limit}
