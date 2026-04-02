"""Tests for FOV behavior around secret doors.

Layout (10x9):

     0123456789
  0  ##########
  1  ####.#####    North corridor: (4,1)
  2  ####S#####    Secret door N: (4,2)
  3  ##......##
  4  .S......S.    Main room floor: (2,3)-(7,5)
  5  ##......##    W door: (1,4), E door: (8,4)
  6  ####S#####    W corridor: (0,4), E corridor: (9,4)
  7  ####.#####    Secret door S: (4,6)
  8  ##########    South corridor: (4,7)

Secret doors block sight from both sides. After discovery
(feature becomes door_closed) they still block sight. After
opening (feature becomes door_open) FOV passes through.
"""

from __future__ import annotations

import pytest

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.utils.fov import compute_fov

WIDTH, HEIGHT = 10, 9
FOV_RADIUS = 8

# Door positions
DOOR_N = (4, 2)
DOOR_S = (4, 6)
DOOR_W = (1, 4)
DOOR_E = (8, 4)

# Corridor tiles behind each door
CORRIDOR_N = (4, 1)
CORRIDOR_S = (4, 7)
CORRIDOR_W = (0, 4)
CORRIDOR_E = (9, 4)

# Main room center and adjacent-to-door positions
CENTER = (5, 4)
NEAR_N = (4, 3)  # one tile south of north door
NEAR_S = (4, 5)  # one tile north of south door
NEAR_W = (2, 4)  # one tile east of west door
NEAR_E = (7, 4)  # one tile west of east door

ALL_DOORS = [DOOR_N, DOOR_S, DOOR_W, DOOR_E]


def _build_level(door_feature: str = "door_secret") -> Level:
    """Build the test level with configurable door feature."""
    level = Level.create_empty("test", "Test", depth=1,
                               width=WIDTH, height=HEIGHT)

    # Main room floor: cols 2-7, rows 3-5
    for y in range(3, 6):
        for x in range(2, 8):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    # Walls around main room (already VOID from create_empty,
    # set explicit WALLs on the border)
    #  Row 0: all wall
    #  Row 2: wall except (4,2) = door
    #  Row 6: wall except (4,6) = door
    #  Row 8: all wall
    #  Col 0: wall, Col 1: wall except (1,4) = door
    #  Col 8: wall except (8,4) = door, Col 9: wall
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if level.tiles[y][x].terrain == Terrain.VOID:
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)

    # Secret doors
    for dx, dy in ALL_DOORS:
        level.tiles[dy][dx] = Tile(
            terrain=Terrain.FLOOR, feature=door_feature,
        )

    # Corridor tiles behind each door
    for cx, cy in [CORRIDOR_N, CORRIDOR_S, CORRIDOR_W, CORRIDOR_E]:
        level.tiles[cy][cx] = Tile(terrain=Terrain.FLOOR,
                                   is_corridor=True)

    return level


def _fov_from(level: Level, x: int, y: int) -> set[tuple[int, int]]:
    """Compute FOV using the level's blocks_sight."""
    def is_blocking(bx: int, by: int) -> bool:
        tile = level.tile_at(bx, by)
        if not tile:
            return True
        return tile.blocks_sight

    return compute_fov(x, y, FOV_RADIUS, is_blocking)


# ── Helpers for parametrized tests ──────────────────────────────


_DOOR_IDS = ["north", "south", "west", "east"]

_DOORS = [DOOR_N, DOOR_S, DOOR_W, DOOR_E]
_CORRIDORS = [CORRIDOR_N, CORRIDOR_S, CORRIDOR_W, CORRIDOR_E]
_NEAR_INSIDE = [NEAR_N, NEAR_S, NEAR_W, NEAR_E]


# ── 1. Player at center — corridors not visible ────────────────


class TestSecretDoorFromCenter:
    """Player at main room center: no corridor behind any door."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_level("door_secret")
        return _fov_from(level, *CENTER)

    @pytest.mark.parametrize("door_id,corridor", zip(_DOOR_IDS, _CORRIDORS),
                             ids=_DOOR_IDS)
    def test_corridor_not_visible(self, fov, door_id, corridor):
        assert corridor not in fov, (
            f"{door_id} corridor {corridor} visible from center"
        )

    @pytest.mark.parametrize("door_id,door", zip(_DOOR_IDS, _DOORS),
                             ids=_DOOR_IDS)
    def test_door_tile_visible(self, fov, door_id, door):
        assert door in fov, (
            f"{door_id} door {door} not visible from center"
        )


# ── 2. Player adjacent to door from inside ─────────────────────


class TestSecretDoorFromAdjacent:
    """Player one tile inside, adjacent to each door."""

    @pytest.mark.parametrize(
        "door_id,near,door,corridor",
        zip(_DOOR_IDS, _NEAR_INSIDE, _DOORS, _CORRIDORS),
        ids=_DOOR_IDS,
    )
    def test_door_visible_corridor_not(self, door_id, near, door,
                                       corridor):
        level = _build_level("door_secret")
        fov = _fov_from(level, *near)
        assert door in fov, (
            f"{door_id} door not visible from {near}"
        )
        assert corridor not in fov, (
            f"{door_id} corridor visible from {near}"
        )


# ── 3. Player in corridor — main room not visible ──────────────


class TestSecretDoorFromCorridor:
    """Player in corridor: main room tiles not visible."""

    @pytest.mark.parametrize(
        "door_id,corridor,door,near",
        zip(_DOOR_IDS, _CORRIDORS, _DOORS, _NEAR_INSIDE),
        ids=_DOOR_IDS,
    )
    def test_door_visible_room_not(self, door_id, corridor, door,
                                   near):
        level = _build_level("door_secret")
        fov = _fov_from(level, *corridor)
        assert door in fov, (
            f"{door_id} door not visible from corridor {corridor}"
        )
        assert near not in fov, (
            f"room tile {near} visible from {door_id} corridor"
        )

    @pytest.mark.parametrize(
        "door_id,corridor",
        zip(_DOOR_IDS, _CORRIDORS),
        ids=_DOOR_IDS,
    )
    def test_center_not_visible(self, door_id, corridor):
        level = _build_level("door_secret")
        fov = _fov_from(level, *corridor)
        assert CENTER not in fov, (
            f"center visible from {door_id} corridor"
        )


# ── 4. Discovered (door_closed) — still blocks ─────────────────


class TestDiscoveredDoorBlocks:
    """After discovery door becomes door_closed, still blocks FOV."""

    @pytest.fixture()
    def level(self) -> Level:
        return _build_level("door_closed")

    @pytest.mark.parametrize(
        "door_id,near,corridor",
        zip(_DOOR_IDS, _NEAR_INSIDE, _CORRIDORS),
        ids=_DOOR_IDS,
    )
    def test_from_inside(self, level, door_id, near, corridor):
        fov = _fov_from(level, *near)
        assert corridor not in fov, (
            f"{door_id} corridor visible through closed door "
            f"from {near}"
        )

    @pytest.mark.parametrize(
        "door_id,corridor,near",
        zip(_DOOR_IDS, _CORRIDORS, _NEAR_INSIDE),
        ids=_DOOR_IDS,
    )
    def test_from_corridor(self, level, door_id, corridor, near):
        fov = _fov_from(level, *corridor)
        assert near not in fov, (
            f"room tile {near} visible through closed door "
            f"from {door_id} corridor"
        )


# ── 5. Opened (door_open) — FOV passes through ─────────────────


class TestOpenDoorAllowsFOV:
    """After opening, FOV passes through the doorway."""

    @pytest.fixture()
    def level(self) -> Level:
        return _build_level("door_open")

    @pytest.mark.parametrize(
        "door_id,near,corridor",
        zip(_DOOR_IDS, _NEAR_INSIDE, _CORRIDORS),
        ids=_DOOR_IDS,
    )
    def test_from_inside(self, level, door_id, near, corridor):
        fov = _fov_from(level, *near)
        assert corridor in fov, (
            f"{door_id} corridor not visible through open door "
            f"from {near}"
        )

    @pytest.mark.parametrize(
        "door_id,corridor,near",
        zip(_DOOR_IDS, _CORRIDORS, _NEAR_INSIDE),
        ids=_DOOR_IDS,
    )
    def test_from_corridor(self, level, door_id, corridor, near):
        fov = _fov_from(level, *corridor)
        assert near in fov, (
            f"room tile {near} not visible through open door "
            f"from {door_id} corridor"
        )
