"""Load static dungeon levels from YAML files on disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from nhc.dungeon.model import (
    Corridor,
    EntityPlacement,
    Level,
    LevelMetadata,
    Rect,
    Room,
    Terrain,
    Tile,
)

# Default legend mapping ASCII chars to terrain/features
DEFAULT_LEGEND: dict[str, str] = {
    "#": "corridor",
    ".": "floor",
    "+": "door_closed",
    "<": "stairs_up",
    ">": "stairs_down",
    "~": "water",
    "^": "trap",
    " ": "void",
    # Box-drawing wall characters
    "─": "wall", "│": "wall",
    "┌": "wall", "┐": "wall", "└": "wall", "┘": "wall",
    "├": "wall", "┤": "wall", "┬": "wall", "┴": "wall", "┼": "wall",
}

# Map legend values to Terrain enum
TERRAIN_MAP: dict[str, Terrain] = {
    "wall": Terrain.WALL,
    "floor": Terrain.FLOOR,
    "water": Terrain.WATER,
    "lava": Terrain.LAVA,
    "chasm": Terrain.CHASM,
    "void": Terrain.VOID,
}

# Legend values that are features on a floor tile (not terrain themselves)
FEATURE_TYPES: set[str] = {
    "door_closed", "door_open", "door_locked",
    "stairs_up", "stairs_down",
    "trap",
}


def _parse_tile(char: str, legend: dict[str, str]) -> Tile:
    """Convert a single ASCII character to a Tile using the legend."""
    meaning = legend.get(char, "void")

    if meaning == "corridor":
        return Tile(terrain=Terrain.FLOOR, is_corridor=True)

    if meaning in FEATURE_TYPES:
        return Tile(terrain=Terrain.FLOOR, feature=meaning)

    terrain = TERRAIN_MAP.get(meaning, Terrain.VOID)
    return Tile(terrain=terrain)


def _parse_map(map_str: str, width: int, height: int,
               legend: dict[str, str]) -> list[list[Tile]]:
    """Parse an ASCII map string into a 2D tile grid."""
    lines = map_str.rstrip("\n").split("\n")
    tiles: list[list[Tile]] = []

    for y in range(height):
        row: list[Tile] = []
        line = lines[y] if y < len(lines) else ""
        for x in range(width):
            char = line[x] if x < len(line) else " "
            row.append(_parse_tile(char, legend))
        tiles.append(row)

    return tiles


def _parse_rooms(raw_rooms: list[dict[str, Any]]) -> list[Room]:
    """Parse room definitions from YAML data."""
    rooms: list[Room] = []
    for r in raw_rooms:
        room = Room(
            id=r["id"],
            rect=Rect(x=r["x"], y=r["y"],
                       width=r["width"], height=r["height"]),
            tags=r.get("tags", []),
            description=r.get("description", "").strip(),
            connections=r.get("connections", []),
        )
        rooms.append(room)
    return rooms


def _parse_corridors(raw_corridors: list[dict[str, Any]]) -> list[Corridor]:
    """Parse corridor definitions from YAML data."""
    corridors: list[Corridor] = []
    for c in raw_corridors:
        corridor = Corridor(
            id=c["id"],
            points=[tuple(p) for p in c.get("points", [])],
            connects=c.get("connects", []),
        )
        corridors.append(corridor)
    return corridors


def _parse_entities(
    raw_entities: list[dict[str, Any]],
) -> list[EntityPlacement]:
    """Parse entity placement definitions from YAML data."""
    entities: list[EntityPlacement] = []
    for e in raw_entities:
        pos = e.get("position", {})
        placement = EntityPlacement(
            entity_type=e["type"],
            entity_id=e["id"],
            x=pos.get("x", 0),
            y=pos.get("y", 0),
            extra=e.get("extra", {}),
        )
        entities.append(placement)
    return entities


def load_level(path: str | Path) -> Level:
    """Load a dungeon level from a YAML file.

    Returns a fully constructed Level with tiles, rooms, corridors,
    entity placements, and metadata.
    """
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)

    width = data["width"]
    height = data["height"]

    # Build legend (merge defaults with file-specific overrides)
    legend = dict(DEFAULT_LEGEND)
    if "legend" in data:
        for char, meaning in data["legend"].items():
            legend[char] = meaning

    # Parse tile grid from ASCII map
    tiles: list[list[Tile]] = []
    if "map" in data:
        tiles = _parse_map(data["map"], width, height, legend)
    else:
        tiles = [
            [Tile(terrain=Terrain.WALL) for _ in range(width)]
            for _ in range(height)
        ]

    # Apply tile overrides (sparse format for tweaking generated maps)
    for override in data.get("tile_overrides", []):
        x, y = override["x"], override["y"]
        if 0 <= x < width and 0 <= y < height:
            if "feature" in override:
                tiles[y][x].feature = override["feature"]
                tiles[y][x].terrain = Terrain.FLOOR
            if "terrain" in override:
                tiles[y][x].terrain = TERRAIN_MAP.get(
                    override["terrain"], Terrain.FLOOR
                )

    # Parse structured data
    rooms = _parse_rooms(data.get("rooms", []))
    corridors = _parse_corridors(data.get("corridors", []))
    entities = _parse_entities(data.get("entities", []))

    metadata = LevelMetadata(
        theme=data.get("theme", "dungeon"),
        difficulty=data.get("difficulty", 1),
        narrative_hooks=data.get("narrative_hooks", []),
        faction=data.get("faction"),
        ambient=data.get("ambient", ""),
    )

    level = Level(
        id=data["id"],
        name=data["name"],
        depth=data["depth"],
        width=width,
        height=height,
        tiles=tiles,
        rooms=rooms,
        corridors=corridors,
        entities=entities,
        metadata=metadata,
    )

    return level


def get_player_start(path: str | Path) -> tuple[int, int]:
    """Read just the player_start position from a level file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    ps = data.get("player_start", {})
    return ps.get("x", 1), ps.get("y", 1)
