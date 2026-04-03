"""Tools for inspecting autosave files."""

from __future__ import annotations

import pickle
import zlib
from pathlib import Path
from typing import Any

from nhc.debug_tools.base import BaseTool


def _load_autosave(path: Path) -> dict[str, Any] | None:
    """Decompress and unpickle an autosave file."""
    if not path.exists():
        return None
    data = path.read_bytes()
    return pickle.loads(zlib.decompress(data))


class GetAutosaveInfoTool(BaseTool):
    name = "get_autosave_info"
    description = (
        "Inspect an autosave file and return a diagnostic "
        "overview: seed, turn, depth, player position, room "
        "count, entity count, floor cache, messages, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path to autosave file (default: "
                    "debug/autosave.nhc)"
                ),
            },
        },
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        save_path = Path(
            kwargs.get("path") or "debug/autosave.nhc",
        )
        payload = _load_autosave(save_path)
        if payload is None:
            return {"error": f"No autosave at {save_path}"}

        level = payload.get("level")
        # Player position from ECS components
        player_id = payload.get("player_id")
        player_pos = None
        components = payload.get("world_components", {})
        for comp_type, store in components.items():
            type_name = (
                comp_type.__name__
                if hasattr(comp_type, "__name__")
                else str(comp_type)
            )
            if type_name == "Position" and player_id in store:
                pos = store[player_id]
                player_pos = [pos.x, pos.y]
                break

        # Room info from level
        rooms = []
        depth = None
        dimensions = None
        seed = payload.get("seed")
        if level:
            depth = getattr(level, "depth", None)
            dimensions = {
                "width": level.width,
                "height": level.height,
            }
            for i, room in enumerate(level.rooms):
                r = room.rect
                rooms.append({
                    "index": i,
                    "x": r.x, "y": r.y,
                    "w": r.width, "h": r.height,
                    "shape": getattr(room.shape, "type_name", "?"),
                })

        # Entity summary from ECS
        entity_ids = payload.get("world_entities", set())

        # Floor cache depths
        floor_cache = payload.get("floor_cache", {})

        # Character info
        character = payload.get("character")
        char_info = None
        if character:
            char_info = {
                k: v for k, v in (
                    character if isinstance(character, dict)
                    else vars(character)
                ).items()
                if isinstance(v, (str, int, float, bool, list))
            }

        # Recent messages
        messages = payload.get("messages", [])

        return {
            "version": payload.get("version"),
            "turn": payload.get("turn"),
            "depth": depth,
            "seed": seed,
            "god_mode": payload.get("god_mode"),
            "mode": payload.get("mode"),
            "player_id": player_id,
            "player_pos": player_pos,
            "dimensions": dimensions,
            "entity_count": len(entity_ids),
            "room_count": len(rooms),
            "rooms": rooms,
            "floor_cache_depths": sorted(floor_cache.keys()),
            "identified_items": sorted(
                payload.get("knowledge_identified", set()),
            ),
            "seen_creatures": sorted(
                payload.get("seen_creatures", set()),
            ),
            "message_count": len(messages),
            "recent_messages": messages[-10:],
            "character": char_info,
            "file": str(save_path),
            "file_size": save_path.stat().st_size,
        }
