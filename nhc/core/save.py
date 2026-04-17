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
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    EdgeSegment,
    HexCell,
    HexFeatureType,
    HexFlower,
    HexWorld,
    MinorFeatureType,
    Rumor,
    SubHexCell,
    SubHexEdgeSegment,
    TimeOfDay,
    FLOWER_COORDS,
)

if TYPE_CHECKING:
    from nhc.core.ecs import World

# Map component type names to their dataclass constructors
_COMPONENT_CLASSES: dict[str, type] = {}
for _name in dir(comp_module):
    _cls = getattr(comp_module, _name)
    if isinstance(_cls, type) and hasattr(_cls, "__dataclass_fields__"):
        _COMPONENT_CLASSES[_name] = _cls

DEFAULT_SAVE_DIR = Path.home() / ".nhc" / "saves"

# JSON save schema version. Bumped from 2 -> 3 when the sub-hex
# flower layer landed (flower data on each HexCell, hour/minute
# clock fields on HexWorld). Old saves are rejected on load.
SCHEMA_VERSION = 3


class SaveSchemaError(ValueError):
    """Raised when a save file's schema version is unsupported."""


def save_game(
    world: "World",
    level: Level,
    player_id: int,
    turn: int,
    messages: list[str],
    save_path: Path | None = None,
    hex_world: HexWorld | None = None,
) -> Path:
    """Serialize game state to a JSON file.

    ``hex_world`` is included as a top-level ``"hex_world"`` section
    when provided (hex-easy / hex-survival modes); pure dungeon
    saves omit the section entirely.
    """
    if save_path is None:
        DEFAULT_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        save_path = DEFAULT_SAVE_DIR / "save.json"

    data: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "turn": turn,
        "player_id": player_id,
        "next_id": world._next_id,
        "entities": _serialize_entities(world),
        "level": _serialize_level(level),
        "messages": messages[-50:],
    }
    if hex_world is not None:
        data["hex_world"] = _serialize_hex_world(hex_world)

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(data, indent=2))
    return save_path


def load_game(
    save_path: Path | None = None,
) -> tuple["World", Level, int, int, list[str]]:
    """Deserialize game state from a JSON file.

    Returns (world, level, player_id, turn, messages). Raises
    :class:`SaveSchemaError` when the file's ``"version"`` does not
    match :data:`SCHEMA_VERSION`. To retrieve the optional
    ``hex_world`` section, use :func:`load_hex_world_from_save` on
    the same path.
    """
    if save_path is None:
        save_path = DEFAULT_SAVE_DIR / "save.json"

    from nhc.core.ecs import World

    data = json.loads(save_path.read_text())
    _check_schema(data)

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


def load_hex_world_from_save(
    save_path: Path | None = None,
) -> HexWorld | None:
    """Return the saved :class:`HexWorld` or ``None`` if the file has
    no ``"hex_world"`` section (pure dungeon-mode save)."""
    if save_path is None:
        save_path = DEFAULT_SAVE_DIR / "save.json"
    data = json.loads(save_path.read_text())
    _check_schema(data)
    section = data.get("hex_world")
    if section is None:
        return None
    return _deserialize_hex_world(section)


def _check_schema(data: dict[str, Any]) -> None:
    version = data.get("version")
    if version != SCHEMA_VERSION:
        raise SaveSchemaError(
            f"save schema version {version!r} is not supported; "
            f"this build expects version {SCHEMA_VERSION}. Saves "
            f"from older versions cannot be upgraded."
        )


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
            if tile.visible:
                td["visible"] = True
            if tile.is_corridor:
                td["is_corridor"] = True
            if tile.door_side:
                td["door_side"] = tile.door_side
            if tile.opened_at_turn is not None:
                td["opened_at_turn"] = tile.opened_at_turn
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
        # For cave shapes, export the exact tile set so
        # diagnostics can know which tiles belong to the room.
        if room.shape.type_name == "cave":
            tiles_set = room.shape.floor_tiles(room.rect)
            rd["tiles"] = sorted([list(t) for t in tiles_set])
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
                visible=td.get("visible", False),
                is_corridor=td.get("is_corridor", False),
                door_side=td.get("door_side", ""),
                opened_at_turn=td.get("opened_at_turn"),
            )
            row.append(tile)
        tiles.append(row)

    rooms = []
    for rd in data.get("rooms", []):
        # Handle cave shapes with explicit tile sets
        shape_type = rd.get("shape")
        if shape_type == "cave" and "tiles" in rd:
            from nhc.dungeon.generators.cellular import CaveShape
            cave_tiles = {tuple(t) for t in rd["tiles"]}
            shape = CaveShape(cave_tiles)
        else:
            shape = shape_from_type(shape_type)
        rooms.append(Room(
            id=rd["id"],
            rect=Rect(**rd["rect"]),
            shape=shape,
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


# ---------------------------------------------------------------------------
# HexWorld serialisation (JSON)
# ---------------------------------------------------------------------------


def _coord_to_list(c: HexCoord) -> list[int]:
    return [c.q, c.r]


def _list_to_coord(lst: list[int]) -> HexCoord:
    return HexCoord(int(lst[0]), int(lst[1]))


# ---------------------------------------------------------------------------
# Flower serialization
# ---------------------------------------------------------------------------


def _serialize_flower(flower: HexFlower) -> dict[str, Any]:
    sub_cells = []
    for coord in sorted(
        flower.cells.keys(), key=lambda c: (c.q, c.r),
    ):
        sc = flower.cells[coord]
        sub_cells.append({
            "c": _coord_to_list(coord),
            "b": sc.biome.value,
            "e": sc.elevation,
            "mf": sc.minor_feature.value,
            "MF": sc.major_feature.value,
            "rd": sc.has_road,
            "rv": sc.has_river,
            "mc": sc.move_cost_hours,
            "em": sc.encounter_modifier,
        })
    edges = [
        {
            "type": seg.type,
            "path": [_coord_to_list(c) for c in seg.path],
            "entry": seg.entry_macro_edge,
            "exit": seg.exit_macro_edge,
        }
        for seg in flower.edges
    ]
    ft = {
        f"{k[0]},{k[1]}": v
        for k, v in flower.fast_travel_costs.items()
    }
    result: dict[str, Any] = {
        "cells": sub_cells,
        "edges": edges,
        "ft": ft,
    }
    if flower.feature_cell is not None:
        result["fc"] = _coord_to_list(flower.feature_cell)
    return result


def _deserialize_flower(
    data: dict[str, Any],
    parent_coord: HexCoord,
) -> HexFlower:
    cells: dict[HexCoord, SubHexCell] = {}
    for sc_data in data.get("cells", []):
        coord = _list_to_coord(sc_data["c"])
        cells[coord] = SubHexCell(
            coord=coord,
            biome=Biome(sc_data["b"]),
            elevation=float(sc_data.get("e", 0.0)),
            minor_feature=MinorFeatureType(sc_data.get("mf", "none")),
            major_feature=HexFeatureType(sc_data.get("MF", "none")),
            has_road=bool(sc_data.get("rd", False)),
            has_river=bool(sc_data.get("rv", False)),
            move_cost_hours=float(sc_data.get("mc", 1.0)),
            encounter_modifier=float(sc_data.get("em", 1.0)),
        )
    edges = [
        SubHexEdgeSegment(
            type=e["type"],
            path=[_list_to_coord(c) for c in e["path"]],
            entry_macro_edge=e.get("entry"),
            exit_macro_edge=e.get("exit"),
        )
        for e in data.get("edges", [])
    ]
    ft_raw = data.get("ft", {})
    ft_costs: dict[tuple[int, int], float] = {}
    for k, v in ft_raw.items():
        parts = k.split(",")
        ft_costs[(int(parts[0]), int(parts[1]))] = float(v)
    fc_data = data.get("fc")
    feature_cell = _list_to_coord(fc_data) if fc_data is not None else None
    return HexFlower(
        parent_coord=parent_coord,
        cells=cells,
        edges=edges,
        feature_cell=feature_cell,
        fast_travel_costs=ft_costs,
    )


def _serialize_hex_world(hw: HexWorld) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for coord, cell in sorted(
        hw.cells.items(), key=lambda kv: (kv[0].q, kv[0].r),
    ):
        cell_data: dict[str, Any] = {
            "coord": _coord_to_list(coord),
            "biome": cell.biome.value,
            "feature": cell.feature.value,
            "name_key": cell.name_key,
            "desc_key": cell.desc_key,
            "elevation": cell.elevation,
        }
        if cell.dungeon is not None:
            cell_data["dungeon"] = {
                "template": cell.dungeon.template,
                "depth": cell.dungeon.depth,
            }
        if cell.edges:
            cell_data["edges"] = [
                {
                    "type": seg.type,
                    "entry": seg.entry_edge,
                    "exit": seg.exit_edge,
                }
                for seg in cell.edges
            ]
        if cell.flower is not None:
            cell_data["flower"] = _serialize_flower(cell.flower)
        cells.append(cell_data)
    rumors = [
        {
            "id": r.id, "text_key": r.text_key,
            "truth": r.truth,
            "reveals": (
                _coord_to_list(r.reveals) if r.reveals is not None
                else None
            ),
        }
        for r in hw.active_rumors
    ]
    return {
        "pack_id": hw.pack_id,
        "seed": hw.seed,
        "width": hw.width,
        "height": hw.height,
        "cells": cells,
        "revealed": [_coord_to_list(c) for c in sorted(
            hw.revealed, key=lambda c: (c.q, c.r))],
        "visited": [_coord_to_list(c) for c in sorted(
            hw.visited, key=lambda c: (c.q, c.r))],
        "cleared": [_coord_to_list(c) for c in sorted(
            hw.cleared, key=lambda c: (c.q, c.r))],
        "looted": [_coord_to_list(c) for c in sorted(
            hw.looted, key=lambda c: (c.q, c.r))],
        "day": hw.day,
        "time": hw.time.name.lower(),
        "hour": hw.hour,
        "minute": hw.minute,
        "last_hub": (
            _coord_to_list(hw.last_hub)
            if hw.last_hub is not None else None
        ),
        "active_rumors": rumors,
        "expedition_party": list(hw.expedition_party),
        "biome_costs": {b.value: v for b, v in hw.biome_costs.items()},
        "rivers": [
            [_coord_to_list(c) for c in river]
            for river in hw.rivers
        ],
        "paths": [
            [_coord_to_list(c) for c in path]
            for path in hw.paths
        ],
        "exploring_hex": (
            _coord_to_list(hw.exploring_hex)
            if hw.exploring_hex is not None else None
        ),
        "exploring_sub_hex": (
            _coord_to_list(hw.exploring_sub_hex)
            if hw.exploring_sub_hex is not None else None
        ),
        "sub_hex_revealed": {
            f"{k.q},{k.r}": [_coord_to_list(c) for c in v]
            for k, v in hw.sub_hex_revealed.items()
        },
        "sub_hex_visited": {
            f"{k.q},{k.r}": [_coord_to_list(c) for c in v]
            for k, v in hw.sub_hex_visited.items()
        },
    }


def _deserialize_hex_world(data: dict[str, Any]) -> HexWorld:
    hw = HexWorld(
        pack_id=data["pack_id"],
        seed=int(data["seed"]),
        width=int(data["width"]),
        height=int(data["height"]),
    )
    for cd in data.get("cells", []):
        coord = _list_to_coord(cd["coord"])
        dungeon = None
        if cd.get("dungeon") is not None:
            dungeon = DungeonRef(
                template=cd["dungeon"]["template"],
                depth=int(cd["dungeon"].get("depth", 1)),
            )
        edges = [
            EdgeSegment(
                type=e["type"],
                entry_edge=e.get("entry"),
                exit_edge=e.get("exit"),
            )
            for e in cd.get("edges", [])
        ]
        flower = None
        if cd.get("flower") is not None:
            flower = _deserialize_flower(cd["flower"], coord)
        hw.set_cell(HexCell(
            coord=coord,
            biome=Biome(cd["biome"]),
            feature=HexFeatureType(cd.get("feature", "none")),
            name_key=cd.get("name_key"),
            desc_key=cd.get("desc_key"),
            dungeon=dungeon,
            elevation=float(cd.get("elevation", 0.0)),
            edges=edges,
            flower=flower,
        ))
    hw.revealed = {_list_to_coord(c) for c in data.get("revealed", [])}
    hw.visited = {_list_to_coord(c) for c in data.get("visited", [])}
    hw.cleared = {_list_to_coord(c) for c in data.get("cleared", [])}
    hw.looted = {_list_to_coord(c) for c in data.get("looted", [])}
    hw.day = int(data.get("day", 1))
    hw.time = TimeOfDay[data.get("time", "morning").upper()]
    hw.hour = int(data.get("hour", 6))
    hw.minute = int(data.get("minute", 0))
    lh = data.get("last_hub")
    hw.last_hub = _list_to_coord(lh) if lh is not None else None
    hw.active_rumors = [
        Rumor(
            id=r["id"], text_key=r["text_key"],
            truth=bool(r.get("truth", True)),
            reveals=(
                _list_to_coord(r["reveals"])
                if r.get("reveals") is not None else None
            ),
        )
        for r in data.get("active_rumors", [])
    ]
    hw.expedition_party = list(data.get("expedition_party", []))
    hw.biome_costs = {
        Biome(k): int(v)
        for k, v in data.get("biome_costs", {}).items()
    }
    hw.rivers = [
        [_list_to_coord(c) for c in river]
        for river in data.get("rivers", [])
    ]
    hw.paths = [
        [_list_to_coord(c) for c in path]
        for path in data.get("paths", [])
    ]
    eh = data.get("exploring_hex")
    hw.exploring_hex = _list_to_coord(eh) if eh is not None else None
    es = data.get("exploring_sub_hex")
    hw.exploring_sub_hex = _list_to_coord(es) if es is not None else None
    for k, v in data.get("sub_hex_revealed", {}).items():
        parts = k.split(",")
        macro = HexCoord(int(parts[0]), int(parts[1]))
        hw.sub_hex_revealed[macro] = {_list_to_coord(c) for c in v}
    for k, v in data.get("sub_hex_visited", {}).items():
        parts = k.split(",")
        macro = HexCoord(int(parts[0]), int(parts[1]))
        hw.sub_hex_visited[macro] = {_list_to_coord(c) for c in v}
    return hw
