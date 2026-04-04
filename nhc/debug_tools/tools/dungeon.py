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


class GetTileMapTool(BaseTool):
    name = "get_tile_map"
    description = (
        "Draw an ASCII tile map around a room or coordinate. "
        "Shows terrain, doors, entities, and room bounding rect."
    )
    parameters = {
        "type": "object",
        "properties": {
            "room_index": {
                "type": "integer",
                "description": "Room index to center on (optional)",
            },
            "x": {
                "type": "integer",
                "description": "Center X (used if no room_index)",
            },
            "y": {
                "type": "integer",
                "description": "Center Y (used if no room_index)",
            },
            "padding": {
                "type": "integer",
                "description": "Tiles around the area (default 3)",
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        game = self._read_json_export("game_state")
        if "error" in game:
            return game
        layer = self._read_json_export("layer_state")

        tiles = game.get("level", {}).get("tiles", [])
        if not tiles:
            return {"error": "No tile data"}
        max_y = len(tiles)
        max_x = len(tiles[0]) if tiles else 0
        pad = kwargs.get("padding", 3)

        room_idx = kwargs.get("room_index")
        rooms = layer.get("debug", {}).get("rooms", [])

        # Determine viewport
        if room_idx is not None and 0 <= room_idx < len(rooms):
            room = rooms[room_idx]
            rx, ry = room["x"], room["y"]
            rw, rh = room["w"], room["h"]
            x0 = max(0, rx - pad)
            y0 = max(0, ry - pad)
            x1 = min(max_x, rx + rw + pad)
            y1 = min(max_y, ry + rh + pad)
        else:
            cx = kwargs.get("x", max_x // 2)
            cy = kwargs.get("y", max_y // 2)
            x0 = max(0, cx - 10)
            y0 = max(0, cy - 10)
            x1 = min(max_x, cx + 11)
            y1 = min(max_y, cy + 11)
            rx, ry, rw, rh = -1, -1, 0, 0

        # Build entity lookup
        entity_map: dict[tuple[int, int], str] = {}
        for e in game.get("entities", []):
            ex, ey = e.get("x", -1), e.get("y", -1)
            if x0 <= ex < x1 and y0 <= ey < y1:
                entity_map[(ex, ey)] = e.get("glyph", "?")

        # Build door lookup
        door_map: dict[tuple[int, int], str] = {}
        for d in layer.get("debug", {}).get("doors", []):
            door_map[(d["x"], d["y"])] = d.get("kind", "D")

        _DOOR_CHARS = {
            "C": "+", "O": "'", "S": "S", "L": "L",
        }
        _TERRAIN_CHARS = {
            "VOID": " ", "WALL": "#", "FLOOR": ".",
            "WATER": "~",
        }

        # Draw the map
        lines = []
        # Column header
        hdr = "     "
        tens = "     "
        for x in range(x0, x1):
            hdr += str(x % 10)
            tens += str((x // 10) % 10) if x % 10 == 0 else " "
        lines.append(tens)
        lines.append(hdr)

        for y in range(y0, y1):
            row = f"{y:4d} "
            for x in range(x0, x1):
                pos = (x, y)
                # Room bounding rect corners
                on_rect = (
                    room_idx is not None
                    and (x == rx - 1 or x == rx + rw)
                    and (y == ry - 1 or y == ry + rh)
                )
                if pos in entity_map:
                    row += entity_map[pos]
                elif pos in door_map:
                    row += _DOOR_CHARS.get(
                        door_map[pos], "D")
                elif y < max_y and x < max_x:
                    tile = tiles[y][x]
                    terrain = tile.get("terrain", "VOID")
                    feat = tile.get("feature")
                    if feat and "stair" in feat:
                        row += "<" if "up" in feat else ">"
                    elif feat and "door" in feat:
                        row += "+"
                    else:
                        ch = _TERRAIN_CHARS.get(terrain, "?")
                        if on_rect:
                            ch = "*"
                        row += ch
                else:
                    row += " "
            lines.append(row)

        legend = (
            "Legend: . floor  # wall  + door  S secret  "
            "L locked  ' open  @ player  < > stairs"
        )
        result: dict[str, Any] = {
            "map": "\n".join(lines),
            "legend": legend,
            "viewport": {
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            },
        }
        if room_idx is not None and 0 <= room_idx < len(rooms):
            result["room"] = rooms[room_idx]
        return result


class GetRoomTilesTool(BaseTool):
    """Return the exact floor tile set for a room.

    For cave-shape rooms, reads the explicit tile set from the
    export.  For rectangular rooms, derives the tile set from the
    rect bounds.  Useful for diagnosing wall rendering against
    the authoritative tile list.
    """

    name = "get_room_tiles"
    description = (
        "Return the exact set of floor tiles belonging to a "
        "room (including irregular cave shapes)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "room_index": {
                "type": "integer",
                "description": "Room index from the rooms list",
            },
        },
        "required": ["room_index"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        idx = kwargs["room_index"]
        game = self._read_json_export("game_state")
        if "error" in game:
            return game
        rooms = game.get("level", {}).get("rooms", [])
        if idx < 0 or idx >= len(rooms):
            return {
                "error": f"Room index {idx} out of range "
                         f"(0-{len(rooms) - 1})",
            }
        room = rooms[idx]
        shape = room.get("shape", "rect")
        rect = room.get("rect", {})

        if shape == "cave" and "tiles" in room:
            tiles = [list(t) for t in room["tiles"]]
        else:
            rx, ry = rect.get("x", 0), rect.get("y", 0)
            rw, rh = rect.get("width", 0), rect.get("height", 0)
            tiles = [
                [x, y]
                for y in range(ry, ry + rh)
                for x in range(rx, rx + rw)
            ]

        return {
            "room_index": idx,
            "shape": shape,
            "rect": rect,
            "tile_count": len(tiles),
            "tiles": tiles,
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
