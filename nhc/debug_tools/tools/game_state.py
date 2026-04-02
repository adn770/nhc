"""Tools for querying game state from exports."""

from __future__ import annotations

from typing import Any

from nhc.debug_tools.base import BaseTool


class GetGameSnapshotTool(BaseTool):
    name = "get_game_snapshot"
    description = (
        "Get a high-level overview of the game state from the "
        "most recent (or specified) game_state export."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Specific export file (optional)",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        data = self._read_json_export(
            "game_state", kwargs.get("filename"))
        if "error" in data:
            return data
        level = data.get("level", {})
        rooms = level.get("rooms", [])
        entities = data.get("entities", [])
        stats = data.get("stats", {})
        # Find player position
        player_pos = None
        for e in entities:
            if e.get("glyph") == "@":
                player_pos = [e["x"], e["y"]]
                break
        return {
            "turn": data.get("turn"),
            "seed": data.get("seed"),
            "player_id": data.get("player_id"),
            "player_pos": player_pos,
            "entity_count": len(entities),
            "room_count": len(rooms),
            "level_name": stats.get("level_name"),
            "depth": stats.get("depth"),
            "dimensions": {
                "width": level.get("width"),
                "height": level.get("height"),
            },
            "hp": f"{stats.get('hp')}/{stats.get('hp_max')}",
            "timestamp": data.get("timestamp"),
        }


class GetEntityListTool(BaseTool):
    name = "get_entity_list"
    description = (
        "List entities from the most recent game_state export. "
        "Optionally filter by glyph or room index."
    )
    parameters = {
        "type": "object",
        "properties": {
            "glyph": {
                "type": "string",
                "description": "Filter by glyph character",
            },
            "room_index": {
                "type": "integer",
                "description": "Filter by room (entities "
                               "within room bounds)",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        data = self._read_json_export("game_state")
        if "error" in data:
            return data
        entities = data.get("entities", [])
        glyph = kwargs.get("glyph")
        room_idx = kwargs.get("room_index")

        if glyph:
            entities = [e for e in entities
                        if e.get("glyph") == glyph]

        if room_idx is not None:
            rooms = data.get("level", {}).get("rooms", [])
            if room_idx < len(rooms):
                r = rooms[room_idx].get("rect", {})
                rx, ry = r.get("x", 0), r.get("y", 0)
                rw, rh = r.get("w", 0), r.get("h", 0)
                entities = [
                    e for e in entities
                    if (rx <= e.get("x", -1) < rx + rw
                        and ry <= e.get("y", -1) < ry + rh)
                ]

        return {"entities": entities, "count": len(entities)}


class GetTileInfoTool(BaseTool):
    name = "get_tile_info"
    description = (
        "Get detailed information about a specific tile from "
        "the most recent game_state and layer_state exports."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Tile X"},
            "y": {"type": "integer", "description": "Tile Y"},
        },
        "required": ["x", "y"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        x, y = kwargs["x"], kwargs["y"]
        game = self._read_json_export("game_state")
        layer = self._read_json_export("layer_state")

        result: dict[str, Any] = {"x": x, "y": y}

        # Tile terrain from level data
        tiles = game.get("level", {}).get("tiles", [])
        if y < len(tiles) and x < len(tiles[0]) if tiles else False:
            tile = tiles[y][x]
            result["terrain"] = tile.get("terrain")
            result["feature"] = tile.get("feature")
            result["explored"] = tile.get("explored", False)

        # Check FOV
        fov = layer.get("fov", [])
        result["visible"] = [x, y] in fov

        # Check explored
        explored = layer.get("explored", [])
        result["explored_layer"] = [x, y] in explored

        # Entities at position
        entities = game.get("entities", [])
        at_pos = [e for e in entities
                  if e.get("x") == x and e.get("y") == y]
        result["entities"] = at_pos

        # Which room (if any)
        rooms = game.get("level", {}).get("rooms", [])
        for i, room in enumerate(rooms):
            r = room.get("rect", {})
            rx, ry = r.get("x", 0), r.get("y", 0)
            rw, rh = r.get("w", 0), r.get("h", 0)
            if rx <= x < rx + rw and ry <= y < ry + rh:
                result["room_index"] = i
                break

        # Door info
        doors = layer.get("doors", [])
        for d in doors:
            if d.get("x") == x and d.get("y") == y:
                result["door"] = d
                break

        return result
