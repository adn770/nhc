"""Stair picker prefers diagonally opposite leaves (M10).

On multi-floor buildings with ≥ 2 rooms per floor, adjacent stair
tiles (same floor's stairs_down and stairs_up, linking floor N
to N+1) should land in *different* rooms so traversal reads as a
spiral. The heuristic picks the room whose centroid is furthest
from the room containing the pending stair-down.
"""

from __future__ import annotations

import random

import pytest

from nhc.sites.mage_residence import assemble_mage_residence


def _stair_tiles_per_floor(
    building,
) -> list[dict[str, tuple[int, int]]]:
    """Return per-floor map of ``{feature: (x, y)}`` for stair
    features. ``stairs_up`` / ``stairs_down`` only."""
    out: list[dict[str, tuple[int, int]]] = []
    for floor in building.floors:
        features: dict[str, tuple[int, int]] = {}
        for y, row in enumerate(floor.tiles):
            for x, tile in enumerate(row):
                if tile.feature in ("stairs_up", "stairs_down"):
                    features[tile.feature] = (x, y)
        out.append(features)
    return out


def _room_containing(
    floor, xy: tuple[int, int],
):
    for room in floor.rooms:
        r = room.rect
        if (r.x <= xy[0] < r.x2) and (r.y <= xy[1] < r.y2):
            return room
    return None


class TestStairDiagonalLeaves:
    def test_stair_up_and_down_in_different_rooms(self) -> None:
        """On a middle floor with both stairs_up and stairs_down,
        the two tiles land in different rooms."""
        for seed in range(50):
            site = assemble_mage_residence(
                "m1", random.Random(seed),
            )
            b = site.buildings[0]
            if len(b.floors) < 3:
                continue
            per_floor = _stair_tiles_per_floor(b)
            # Middle floors have both features.
            middles = [
                per_floor[i] for i in range(1, len(b.floors) - 1)
                if "stairs_up" in per_floor[i]
                and "stairs_down" in per_floor[i]
            ]
            if not middles:
                continue
            for features in middles:
                up = features["stairs_up"]
                down = features["stairs_down"]
                # Find which room each sits in on that floor.
                floor_idx = per_floor.index(features)
                floor = b.floors[floor_idx]
                up_room = _room_containing(floor, up)
                down_room = _room_containing(floor, down)
                if up_room is None or down_room is None:
                    continue
                assert up_room.id != down_room.id, (
                    f"seed={seed} floor={floor_idx}: stairs_up "
                    f"and stairs_down both in room {up_room.id}"
                )
            return
        pytest.skip(
            "no mage-residence seed produced a 3-floor building "
            "with both stair features on a middle floor"
        )
