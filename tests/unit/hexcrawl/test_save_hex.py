"""Save/load round-trip for hex mode, plus the schema version bump.

JSON save schema now sits at version 2. Version 1 dungeon-only saves
are rejected on load with a clear error (pre-1.0 churn is
documented in design/overland_hexcrawl.md and the implementation
plan).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhc.core.ecs import World
from nhc.core.save import (
    SCHEMA_VERSION,
    SaveSchemaError,
    load_game,
    load_hex_world_from_save,
    save_game,
)
from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, Room, Terrain, Tile,
)
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome, EdgeSegment, HexCell, HexFeatureType, HexWorld, TimeOfDay,
)


# ---------------------------------------------------------------------------
# Minimal Level fixture the save path accepts
# ---------------------------------------------------------------------------


def _tiny_level() -> Level:
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(3)]
        for _ in range(3)
    ]
    return Level(
        id="test-level", name="Test", depth=1,
        width=3, height=3, tiles=tiles, rooms=[], corridors=[],
        metadata=LevelMetadata(),
    )


def _tiny_hex_world() -> HexWorld:
    w = HexWorld(pack_id="testland", seed=42, width=4, height=4)
    for q in range(4):
        for r in range(4):
            w.set_cell(
                HexCell(coord=HexCoord(q, r), biome=Biome.GREENLANDS),
            )
    w.cells[HexCoord(2, 2)].feature = HexFeatureType.CITY
    w.cells[HexCoord(2, 2)].biome = Biome.DRYLANDS
    w.reveal(HexCoord(2, 2))
    w.visit(HexCoord(2, 2))
    w.last_hub = HexCoord(2, 2)
    w.day = 3
    w.time = TimeOfDay.EVENING
    w.biome_costs = {Biome.MOUNTAIN: 6}
    w.cleared.add(HexCoord(0, 0))
    return w


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_schema_version_is_four() -> None:
    assert SCHEMA_VERSION == 4


def test_save_writes_schema_version_four(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    path = tmp_path / "s.json"
    save_game(w, _tiny_level(), pid, turn=1, messages=[], save_path=path)
    data = json.loads(path.read_text())
    assert data["version"] == 4


# ---------------------------------------------------------------------------
# Dungeon-only round-trip (behaviour preserved)
# ---------------------------------------------------------------------------


def test_dungeon_only_save_round_trip_still_works(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    path = tmp_path / "s.json"
    save_game(w, _tiny_level(), pid, turn=7, messages=["hi"], save_path=path)
    w2, l2, pid2, turn2, msgs2 = load_game(path)
    assert pid2 == pid
    assert turn2 == 7
    assert msgs2 == ["hi"]
    assert l2.width == 3


def test_load_hex_world_returns_none_when_absent(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    path = tmp_path / "s.json"
    save_game(w, _tiny_level(), pid, turn=0, messages=[], save_path=path)
    assert load_hex_world_from_save(path) is None


# ---------------------------------------------------------------------------
# Hex-mode round-trip
# ---------------------------------------------------------------------------


def test_save_serializes_hex_world(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    hex_world = _tiny_hex_world()
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    data = json.loads(path.read_text())
    assert "hex_world" in data
    assert data["hex_world"]["pack_id"] == "testland"
    assert data["hex_world"]["day"] == 3
    assert data["hex_world"]["time"] == "evening"


def test_load_restores_hex_world_round_trip(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    hex_world = _tiny_hex_world()
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    restored = load_hex_world_from_save(path)
    assert restored is not None
    assert restored.pack_id == hex_world.pack_id
    assert restored.seed == hex_world.seed
    assert restored.width == hex_world.width
    assert restored.height == hex_world.height
    assert restored.day == 3
    assert restored.time is TimeOfDay.EVENING
    assert restored.last_hub == HexCoord(2, 2)
    # Sets come back as sets.
    assert HexCoord(2, 2) in restored.revealed
    assert HexCoord(2, 2) in restored.visited
    assert HexCoord(0, 0) in restored.cleared
    # biome_costs survive.
    assert restored.biome_costs[Biome.MOUNTAIN] == 6
    # Cells survive with feature + biome.
    city_cell = restored.cells[HexCoord(2, 2)]
    assert city_cell.biome is Biome.DRYLANDS
    assert city_cell.feature is HexFeatureType.CITY


# ---------------------------------------------------------------------------
# Old saves rejected
# ---------------------------------------------------------------------------


def test_load_rejects_version_one_save(tmp_path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "version": 1,
        "turn": 0,
        "player_id": 0,
        "next_id": 1,
        "entities": {},
        "level": {
            "width": 1, "height": 1,
            "tiles": [[{"x": 0, "y": 0, "terrain": "floor"}]],
            "rooms": [], "corridors": [],
            "metadata": {"seed": 0, "depth": 1},
        },
        "messages": [],
    }))
    with pytest.raises(SaveSchemaError):
        load_game(path)


def test_load_rejects_missing_version(tmp_path) -> None:
    path = tmp_path / "noversion.json"
    path.write_text(json.dumps({"turn": 0}))
    with pytest.raises(SaveSchemaError):
        load_game(path)


# ---------------------------------------------------------------------------
# Elevation, edges, rivers, paths round-trip
# ---------------------------------------------------------------------------


def _hex_world_with_edges() -> HexWorld:
    """Build a HexWorld with elevation, edge segments, rivers, and paths."""
    w = HexWorld(pack_id="testland", seed=42, width=4, height=4)
    for q in range(4):
        for r in range(4):
            elev = 0.8 - 0.1 * r  # decreasing elevation southward
            w.set_cell(
                HexCell(
                    coord=HexCoord(q, r),
                    biome=Biome.GREENLANDS,
                    elevation=elev,
                ),
            )
    # Add river edge segments to a few cells.
    river_coords = [HexCoord(1, 0), HexCoord(1, 1), HexCoord(1, 2)]
    w.cells[river_coords[0]].edges.append(
        EdgeSegment(type="river", entry_edge=None, exit_edge=3),
    )
    w.cells[river_coords[1]].edges.append(
        EdgeSegment(type="river", entry_edge=0, exit_edge=3),
    )
    w.cells[river_coords[2]].edges.append(
        EdgeSegment(type="river", entry_edge=0, exit_edge=None),
    )
    w.rivers.append(river_coords)

    # Add a path between two cells.
    path_coords = [HexCoord(0, 1), HexCoord(1, 1), HexCoord(2, 1)]
    w.cells[path_coords[0]].edges.append(
        EdgeSegment(type="path", entry_edge=None, exit_edge=2),
    )
    w.cells[path_coords[1]].edges.append(
        EdgeSegment(type="path", entry_edge=5, exit_edge=2),
    )
    w.cells[path_coords[2]].edges.append(
        EdgeSegment(type="path", entry_edge=5, exit_edge=None),
    )
    w.paths.append(path_coords)
    return w


def test_save_round_trip_preserves_elevation(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    hex_world = _hex_world_with_edges()
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    restored = load_hex_world_from_save(path)
    assert restored is not None
    for coord, cell in hex_world.cells.items():
        assert restored.cells[coord].elevation == pytest.approx(
            cell.elevation,
        )


def test_save_round_trip_preserves_edge_segments(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    hex_world = _hex_world_with_edges()
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    restored = load_hex_world_from_save(path)
    assert restored is not None
    # Check the river source cell.
    src = restored.cells[HexCoord(1, 0)]
    assert len(src.edges) == 1
    assert src.edges[0].type == "river"
    assert src.edges[0].entry_edge is None
    assert src.edges[0].exit_edge == 3
    # Check a mid-river cell with both river and path.
    mid = restored.cells[HexCoord(1, 1)]
    assert len(mid.edges) == 2
    types = {seg.type for seg in mid.edges}
    assert types == {"river", "path"}


def test_save_round_trip_preserves_rivers(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    hex_world = _hex_world_with_edges()
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    restored = load_hex_world_from_save(path)
    assert restored is not None
    assert len(restored.rivers) == 1
    assert restored.rivers[0] == hex_world.rivers[0]


def test_save_round_trip_preserves_paths(tmp_path) -> None:
    w = World()
    pid = w.create_entity({})
    hex_world = _hex_world_with_edges()
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    restored = load_hex_world_from_save(path)
    assert restored is not None
    assert len(restored.paths) == 1
    assert restored.paths[0] == hex_world.paths[0]


def test_old_saves_without_edges_load_with_defaults(tmp_path) -> None:
    """v2 saves written before rivers/paths load with empty defaults."""
    w = World()
    pid = w.create_entity({})
    hex_world = _tiny_hex_world()  # no edges, no elevation set
    path = tmp_path / "s.json"
    save_game(
        w, _tiny_level(), pid, turn=0, messages=[],
        save_path=path, hex_world=hex_world,
    )
    restored = load_hex_world_from_save(path)
    assert restored is not None
    for cell in restored.cells.values():
        assert cell.elevation == 0.0
        assert cell.edges == []
    assert restored.rivers == []
    assert restored.paths == []
