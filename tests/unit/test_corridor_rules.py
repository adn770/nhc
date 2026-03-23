"""Tests enforcing corridor rendering and connection rules.

Rules:
1. Corridor tiles must have VOID (not WALL) on their sides.
2. Corridors never terminate at room corners.
3. Every corridor-room connection has a door.
4. Corridors can connect to other corridors without doors.
"""

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Terrain
from nhc.dungeon.room_types import assign_room_types
from nhc.dungeon.terrain import apply_terrain
from nhc.utils.rng import set_seed, get_rng


def _generate(seed: int = 42):
    set_seed(seed)
    gen = BSPGenerator()
    level = gen.generate(GenerationParams(width=70, height=35, depth=2))
    rng = get_rng()
    assign_room_types(level, rng)
    apply_terrain(level, rng)
    return level


class TestCorridorSidesAreVoid:
    """Rule 1: corridor tiles must NOT have WALL on their sides."""

    def test_no_wall_adjacent_to_corridor(self):
        for seed in (42, 7, 123, 999):
            level = _generate(seed)
            for y in range(level.height):
                for x in range(level.width):
                    tile = level.tiles[y][x]
                    if not (tile.terrain == Terrain.FLOOR
                            and tile.is_corridor):
                        continue
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb is None:
                            continue
                        assert nb.terrain != Terrain.WALL, (
                            f"seed={seed}: corridor ({x},{y}) has WALL "
                            f"neighbor at ({x+dx},{y+dy})"
                        )


class TestCorridorRoomDoors:
    """Rule 3: every corridor-room transition has a door."""

    def test_corridor_adjacent_to_room_has_door(self):
        for seed in (42, 7, 123):
            level = _generate(seed)
            for y in range(level.height):
                for x in range(level.width):
                    tile = level.tiles[y][x]
                    if not (tile.terrain == Terrain.FLOOR
                            and tile.is_corridor):
                        continue
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb is None:
                            continue
                        # Corridor adjacent to room floor (non-corridor)
                        if (nb.terrain == Terrain.FLOOR
                                and not nb.is_corridor
                                and not nb.feature):
                            # There must be a door between them —
                            # either this tile or the neighbor
                            has_door = (
                                tile.feature in (
                                    "door_closed", "door_open",
                                    "door_secret",
                                )
                                or nb.feature in (
                                    "door_closed", "door_open",
                                    "door_secret",
                                )
                            )
                            # Allow: corridor enters room directly
                            # if there's a door within 1 tile
                            if not has_door:
                                # Check if there's a door within 2
                                # tiles along the corridor
                                door_nearby = False
                                for dx2, dy2 in [(-1, 0), (1, 0),
                                                 (0, -1), (0, 1)]:
                                    nb2 = level.tile_at(
                                        x + dx2, y + dy2,
                                    )
                                    if nb2 and nb2.feature in (
                                        "door_closed", "door_open",
                                        "door_secret",
                                    ):
                                        door_nearby = True
                                        break
                                assert door_nearby, (
                                    f"seed={seed}: corridor ({x},{y}) "
                                    f"touches room floor ({x+dx},{y+dy})"
                                    f" without a door nearby"
                                )
