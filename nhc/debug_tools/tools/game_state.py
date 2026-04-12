"""Tools for querying game state from exports."""

from __future__ import annotations

from typing import Any

from nhc.debug_tools.base import BaseTool


# ── Item type detection ──────────────────────────────────────────
# Order matters: the first matching component wins, so more
# specific types (Wand, Ring) come before generic ones (Weapon).
_ITEM_TYPE_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("Wand", "wand"),
    ("Ring", "ring"),
    ("Weapon", "weapon"),
    ("Armor", "armor"),
    ("Consumable", "consumable"),
    ("DiggingTool", "tool"),
    ("Gem", "gem"),
)


def _item_summary(
    item_id: int, comps: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a compact summary of an item entity from its components."""
    if comps is None:
        return None

    desc = comps.get("Description") or {}
    summary: dict[str, Any] = {
        "id": item_id,
        "name": desc.get("name", ""),
    }

    reg = comps.get("RegistryId")
    if reg and reg.get("item_id"):
        summary["item_id"] = reg["item_id"]

    item_type = "item"
    for comp_name, type_label in _ITEM_TYPE_COMPONENTS:
        if comp_name in comps:
            item_type = type_label
            data = comps[comp_name] or {}
            # Copy non-zero / non-default fields onto the summary.
            for key, value in data.items():
                if value not in (0, "", None, False):
                    summary[key] = value
            break
    summary["type"] = item_type

    if "Enchanted" in comps:
        summary["enchanted"] = True

    return summary


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


def _enrich_entity(
    entity: dict[str, Any],
    ecs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge key ECS component data into a rendering entity dict."""
    eid = entity.get("id")
    if eid is None:
        return entity
    comps = ecs.get(str(eid))
    if not comps:
        return entity
    enriched = dict(entity)
    # List component names present on this entity
    enriched["components"] = sorted(comps.keys())
    # Include commonly useful component details
    for comp_name in (
        "Trap", "Henchman", "AI", "Health", "Detected",
        "BuriedMarker", "StatusEffect", "Hunger",
    ):
        if comp_name in comps:
            enriched[comp_name] = comps[comp_name]
    return enriched


class GetEntityListTool(BaseTool):
    name = "get_entity_list"
    description = (
        "List entities from the most recent game_state export. "
        "Optionally filter by glyph or room index. Includes "
        "ECS component names and key component details."
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
        ecs = data.get("ecs", {}) or {}
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

        enriched = [_enrich_entity(e, ecs) for e in entities]
        return {"entities": enriched, "count": len(enriched)}


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
            if tile.get("buried"):
                result["buried"] = tile["buried"]
            if tile.get("dug_floor"):
                result["dug_floor"] = True
            if tile.get("dug_wall"):
                result["dug_wall"] = True

        # Check FOV
        fov = layer.get("fov", [])
        result["visible"] = [x, y] in fov

        # Check explored
        explored = layer.get("explored", [])
        result["explored_layer"] = [x, y] in explored

        # Entities at position (enriched with ECS components)
        entities = game.get("entities", [])
        ecs = game.get("ecs", {}) or {}
        at_pos = [e for e in entities
                  if e.get("x") == x and e.get("y") == y]
        result["entities"] = [
            _enrich_entity(e, ecs) for e in at_pos
        ]

        # Also check ECS for entities at this position that may
        # not appear in the rendering list (e.g. hidden traps)
        rendered_ids = {e.get("id") for e in at_pos}
        for eid_str, comps in ecs.items():
            pos = comps.get("Position")
            if not pos or pos.get("x") != x or pos.get("y") != y:
                continue
            eid = int(eid_str)
            if eid in rendered_ids:
                continue
            desc = comps.get("Description", {})
            hidden_entry: dict[str, Any] = {
                "id": eid,
                "x": x, "y": y,
                "name": desc.get("name", ""),
                "hidden_from_render": True,
                "components": sorted(comps.keys()),
            }
            for comp_name in ("Trap", "BuriedMarker", "Detected"):
                if comp_name in comps:
                    hidden_entry[comp_name] = comps[comp_name]
            result["entities"].append(hidden_entry)

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


class GetEntityComponentsTool(BaseTool):
    name = "get_entity_components"
    description = (
        "Get all ECS components for a specific entity by ID. "
        "Returns the full component data from the most recent "
        "game_state export."
    )
    parameters = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "integer",
                "description": "Entity ID to inspect",
            },
        },
        "required": ["entity_id"],
    }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        data = self._read_json_export("game_state")
        if "error" in data:
            return data
        ecs = data.get("ecs", {}) or {}
        eid = kwargs["entity_id"]
        comps = ecs.get(str(eid))
        if comps is None:
            return {"error": f"Entity {eid} not found in ECS"}
        return {"entity_id": eid, "components": comps}


class GetHenchmanSheetsTool(BaseTool):
    name = "get_henchman_sheets"
    description = (
        "Return character sheets for all henchmen in the most "
        "recent game_state export: name, level, XP, HP, ability "
        "stats, equipped weapon/armor/shield/helmet/rings, and "
        "carried inventory items. Optionally filter by entity id."
    )
    parameters = {
        "type": "object",
        "properties": {
            "henchman_id": {
                "type": "integer",
                "description": (
                    "Only return the sheet for this entity id."
                ),
            },
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
        ecs: dict[str, dict[str, Any]] = data.get("ecs", {}) or {}
        return build_henchman_sheets(
            ecs, henchman_id=kwargs.get("henchman_id"),
        )


def _lookup(
    ecs: dict[str, dict[str, Any]], item_id: int | None,
) -> dict[str, Any] | None:
    if item_id is None:
        return None
    return ecs.get(str(item_id))


def _build_equipment(
    equipment: dict[str, Any] | None,
    ecs: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not equipment:
        return None
    slots = (
        "weapon", "armor", "shield", "helmet",
        "ring_left", "ring_right",
    )
    return {
        slot: _item_summary(
            equipment.get(slot),
            _lookup(ecs, equipment.get(slot)),
        )
        for slot in slots
    }


def _build_inventory(
    slot_ids: list[int],
    ecs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item_id in slot_ids:
        summary = _item_summary(item_id, _lookup(ecs, item_id))
        if summary is not None:
            items.append(summary)
    return items


def _build_sheet(
    eid: int,
    comps: dict[str, Any],
    ecs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    henchman = comps.get("Henchman") or {}
    desc = comps.get("Description") or {}
    stats = comps.get("Stats")
    health = comps.get("Health")
    equipment = comps.get("Equipment")
    inventory = comps.get("Inventory") or {}

    return {
        "id": eid,
        "name": desc.get("name", ""),
        "short": desc.get("short", ""),
        "level": henchman.get("level", 1),
        "xp": henchman.get("xp", 0),
        "xp_to_next": henchman.get("xp_to_next", 0),
        "hired": henchman.get("hired", False),
        "owner": henchman.get("owner"),
        "hp": health.get("current") if health else None,
        "max_hp": health.get("maximum") if health else None,
        "stats": dict(stats) if stats else None,
        "equipment": _build_equipment(equipment, ecs),
        "inventory": _build_inventory(
            inventory.get("slots", []), ecs,
        ),
        "inventory_max_slots": inventory.get("max_slots"),
    }


def build_henchman_sheets(
    ecs: dict[str, dict[str, Any]],
    *,
    henchman_id: int | None = None,
    hired_only: bool = False,
    owner_id: int | None = None,
) -> dict[str, Any]:
    """Build henchman character sheets from a serialized ECS dict.

    Shared by the MCP debug tool (reads from JSON exports) and the
    live web endpoint (serializes the running ``World``).

    Args:
        ecs: Serialized ECS dict (entity_id_str → component dict).
        henchman_id: If set, only return the sheet for this entity id.
        hired_only: If True, exclude unhired adventurers.
        owner_id: If set, only return henchmen owned by this player.
    """
    sheets: list[dict[str, Any]] = []
    for eid_str, comps in ecs.items():
        hench = comps.get("Henchman")
        if not hench:
            continue
        try:
            eid = int(eid_str)
        except (TypeError, ValueError):
            continue
        if henchman_id is not None and eid != henchman_id:
            continue
        if hired_only and not hench.get("hired"):
            continue
        if owner_id is not None and hench.get("owner") != owner_id:
            continue
        sheets.append(_build_sheet(eid, comps, ecs))

    sheets.sort(key=lambda s: s["id"])
    return {"henchmen": sheets, "count": len(sheets)}
