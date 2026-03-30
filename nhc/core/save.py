"""Save and load game state to/from JSON files."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nhc.dungeon.model import (
    Corridor,
    Level,
    LevelMetadata,
    Rect,
    Room,
    Terrain,
    Tile,
    shape_from_type,
)
from nhc.entities import components as comp_module

if TYPE_CHECKING:
    from nhc.core.ecs import World

# Map component type names to their dataclass constructors
_COMPONENT_CLASSES: dict[str, type] = {}
for _name in dir(comp_module):
    _cls = getattr(comp_module, _name)
    if isinstance(_cls, type) and hasattr(_cls, "__dataclass_fields__"):
        _COMPONENT_CLASSES[_name] = _cls

DEFAULT_SAVE_DIR = Path.home() / ".nhc" / "saves"


def save_game(
    world: "World",
    level: Level,
    player_id: int,
    turn: int,
    messages: list[str],
    save_path: Path | None = None,
) -> Path:
    """Serialize game state to a JSON file."""
    if save_path is None:
        DEFAULT_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        save_path = DEFAULT_SAVE_DIR / "save.json"

    data: dict[str, Any] = {
        "version": 1,
        "turn": turn,
        "player_id": player_id,
        "next_id": world._next_id,
        "entities": _serialize_entities(world),
        "level": _serialize_level(level),
        "messages": messages[-50:],
    }

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(data, indent=2))
    return save_path


def load_game(
    save_path: Path | None = None,
) -> tuple["World", Level, int, int, list[str]]:
    """Deserialize game state from a JSON file.

    Returns (world, level, player_id, turn, messages).
    """
    if save_path is None:
        save_path = DEFAULT_SAVE_DIR / "save.json"

    from nhc.core.ecs import World

    data = json.loads(save_path.read_text())

    world = World()
    world._next_id = data["next_id"]

    for eid_str, comps in data["entities"].items():
        eid = int(eid_str)
        world._entities.add(eid)
        for comp_type, comp_data in comps.items():
            comp = _deserialize_component(comp_type, comp_data)
            world.add_component(eid, comp_type, comp)

    level = _deserialize_level(data["level"])
    player_id = data["player_id"]
    turn = data["turn"]
    messages = data.get("messages", [])

    return world, level, player_id, turn, messages


def has_save(save_path: Path | None = None) -> bool:
    """Check if a save file exists."""
    if save_path is None:
        save_path = DEFAULT_SAVE_DIR / "save.json"
    return save_path.exists()


def delete_save(save_path: Path | None = None) -> None:
    """Delete a save file."""
    if save_path is None:
        save_path = DEFAULT_SAVE_DIR / "save.json"
    if save_path.exists():
        save_path.unlink()


def _serialize_entities(world: "World") -> dict[str, dict[str, Any]]:
    """Serialize all entities and their components."""
    result: dict[str, dict[str, Any]] = {}

    for eid in world._entities:
        comps: dict[str, Any] = {}
        for comp_type, store in world._components.items():
            if eid in store:
                comp = store[eid]
                comps[comp_type] = _serialize_component(comp_type, comp)
        result[str(eid)] = comps

    return result


def _serialize_component(comp_type: str, comp: Any) -> Any:
    """Serialize a single component to a JSON-safe dict."""
    if comp is None:
        return None
    if isinstance(comp, bool):
        return comp
    if comp_type in _COMPONENT_CLASSES:
        return asdict(comp)
    if hasattr(comp, "__dict__"):
        return comp.__dict__
    return comp


def _deserialize_component(comp_type: str, data: Any) -> Any:
    """Deserialize a component from JSON data."""
    if data is None:
        return None
    if isinstance(data, bool):
        return data
    if comp_type in _COMPONENT_CLASSES:
        cls = _COMPONENT_CLASSES[comp_type]
        if comp_type == "LootTable" and "entries" in data:
            data["entries"] = [tuple(e) for e in data["entries"]]
        return cls(**data)
    return data


def _serialize_level(level: Level) -> dict[str, Any]:
    """Serialize a Level to a JSON-safe dict."""
    tiles_data = []
    for row in level.tiles:
        row_data = []
        for tile in row:
            td: dict[str, Any] = {"terrain": tile.terrain.name}
            if tile.feature:
                td["feature"] = tile.feature
            if tile.explored:
                td["explored"] = True
            row_data.append(td)
        tiles_data.append(row_data)

    rooms_data = []
    for room in level.rooms:
        rd: dict[str, Any] = {
            "id": room.id,
            "rect": asdict(room.rect),
            "tags": room.tags,
            "description": room.description,
            "connections": room.connections,
        }
        if room.shape.type_name != "rect":
            rd["shape"] = room.shape.type_name
        rooms_data.append(rd)

    corridors_data = []
    for corridor in level.corridors:
        corridors_data.append({
            "id": corridor.id,
            "points": corridor.points,
            "connects": corridor.connects,
        })

    return {
        "id": level.id,
        "name": level.name,
        "depth": level.depth,
        "width": level.width,
        "height": level.height,
        "tiles": tiles_data,
        "rooms": rooms_data,
        "corridors": corridors_data,
        "metadata": asdict(level.metadata),
    }


def _deserialize_level(data: dict[str, Any]) -> Level:
    """Deserialize a Level from JSON data."""
    tiles = []
    for row_data in data["tiles"]:
        row = []
        for td in row_data:
            tile = Tile(
                terrain=Terrain[td["terrain"]],
                feature=td.get("feature"),
                explored=td.get("explored", False),
            )
            row.append(tile)
        tiles.append(row)

    rooms = []
    for rd in data.get("rooms", []):
        rooms.append(Room(
            id=rd["id"],
            rect=Rect(**rd["rect"]),
            shape=shape_from_type(rd.get("shape")),
            tags=rd.get("tags", []),
            description=rd.get("description", ""),
            connections=rd.get("connections", []),
        ))

    corridors = []
    for cd in data.get("corridors", []):
        corridors.append(Corridor(
            id=cd["id"],
            points=[tuple(p) for p in cd.get("points", [])],
            connects=cd.get("connects", []),
        ))

    meta_data = data.get("metadata", {})
    metadata = LevelMetadata(
        theme=meta_data.get("theme", "dungeon"),
        difficulty=meta_data.get("difficulty", 1),
        narrative_hooks=meta_data.get("narrative_hooks", []),
        faction=meta_data.get("faction"),
        ambient=meta_data.get("ambient", ""),
    )

    return Level(
        id=data["id"],
        name=data["name"],
        depth=data["depth"],
        width=data["width"],
        height=data["height"],
        tiles=tiles,
        rooms=rooms,
        corridors=corridors,
        metadata=metadata,
    )
