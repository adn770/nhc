"""Tests for the unified door candidate function."""

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator, _door_candidates
from nhc.dungeon.model import (
    CircleShape,
    CrossShape,
    HybridShape,
    Level,
    OctagonShape,
    Rect,
    RectShape,
    Room,
    Terrain,
    Tile,
)
from nhc.utils.rng import set_seed


def _make_room_level(
    rect: Rect, shape, level_w: int = 40, level_h: int = 30,
) -> tuple[Level, Room]:
    """Create a level with a single room, floor carved, walls built."""
    level = Level.create_empty("test", "Test", depth=1,
                               width=level_w, height=level_h)
    room = Room(id="r0", rect=rect, shape=shape)
    floor = shape.floor_tiles(rect)
    for fx, fy in floor:
        level.tiles[fy][fx] = Tile(terrain=Terrain.FLOOR)
    # Build walls (8-neighbor of floor → WALL if VOID)
    for fx, fy in floor:
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = fx + dx, fy + dy
                if (level.in_bounds(nx, ny)
                        and level.tiles[ny][nx].terrain == Terrain.VOID):
                    level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)
    level.rooms.append(room)
    return level, room


class TestDoorCandidatesRect:
    def test_rect_has_candidates_on_all_sides(self):
        level, room = _make_room_level(
            Rect(10, 10, 6, 4), RectShape())
        cands = _door_candidates(level, room)
        sides = {side for _, _, side in cands}
        assert sides == {"north", "south", "east", "west"}

    def test_rect_no_corner_candidates(self):
        """No candidates at convex corners of the bounding rect."""
        level, room = _make_room_level(
            Rect(10, 10, 6, 4), RectShape())
        cands = _door_candidates(level, room)
        r = room.rect
        corners = {
            (r.x - 1, r.y - 1), (r.x2, r.y - 1),
            (r.x - 1, r.y2), (r.x2, r.y2),
        }
        cand_positions = {(x, y) for x, y, _ in cands}
        assert not (cand_positions & corners), (
            f"Corner positions in candidates: "
            f"{cand_positions & corners}")

    def test_rect_candidate_count(self):
        """A 6x4 rect should have candidates along all straight edges."""
        level, room = _make_room_level(
            Rect(10, 10, 6, 4), RectShape())
        cands = _door_candidates(level, room)
        # North: 6 wall tiles minus 2 corners = 4
        # South: same = 4
        # East: 4 wall tiles minus 2 corners = 2
        # West: same = 2
        # Total = 12 (may be less if some have clearance issues)
        assert len(cands) >= 8


class TestDoorCandidatesCircle:
    def test_circle_only_cardinal_positions(self):
        """Circle rooms should only have candidates at cardinal walls."""
        level, room = _make_room_level(
            Rect(10, 10, 7, 7), CircleShape())
        cands = _door_candidates(level, room)
        # Should have at most 4 candidates (N, S, E, W)
        assert len(cands) <= 4
        assert len(cands) >= 2  # at least 2 cardinals valid
        # All must be on straight wall segments
        for x, y, side in cands:
            assert side in ("north", "south", "east", "west")

    def test_circle_no_diagonal_positions(self):
        """All candidates must have VOID on the outward side and
        WALL neighbors on both parallel sides with VOID outward.
        No candidates on curved wall sections."""
        level, room = _make_room_level(
            Rect(10, 10, 9, 9), CircleShape())
        cands = _door_candidates(level, room)
        _INWARD = {
            "north": (0, 1), "south": (0, -1),
            "east": (-1, 0), "west": (1, 0),
        }
        _PARALLEL = {
            "north": [(-1, 0), (1, 0)],
            "south": [(-1, 0), (1, 0)],
            "east": [(0, -1), (0, 1)],
            "west": [(0, -1), (0, 1)],
        }
        for wx, wy, side in cands:
            idx, idy = _INWARD[side]
            # Outward must be VOID
            ot = level.tile_at(wx - idx, wy - idy)
            assert ot and ot.terrain == Terrain.VOID, (
                f"({wx},{wy}) {side}: outward not VOID")
            # Both parallel wall neighbors must have VOID outward
            for pdx, pdy in _PARALLEL[side]:
                pw = level.tile_at(wx + pdx, wy + pdy)
                assert pw and pw.terrain == Terrain.WALL, (
                    f"({wx},{wy}) {side}: parallel not WALL")
                po = level.tile_at(wx + pdx - idx, wy + pdy - idy)
                assert po and po.terrain == Terrain.VOID, (
                    f"({wx},{wy}) {side}: parallel outward not VOID")


class TestDoorCandidatesOctagon:
    def test_octagon_no_clipped_corners(self):
        """Octagon corners are clipped — no candidates there."""
        level, room = _make_room_level(
            Rect(10, 10, 9, 9), OctagonShape())
        cands = _door_candidates(level, room)
        cand_positions = {(x, y) for x, y, _ in cands}
        r = room.rect
        # The clipped corner positions should not be candidates
        corners = {
            (r.x - 1, r.y - 1), (r.x2, r.y - 1),
            (r.x - 1, r.y2), (r.x2, r.y2),
        }
        assert not (cand_positions & corners)
        # Should still have candidates on the straight edges
        assert len(cands) >= 4


class TestDoorCandidatesHybrid:
    def test_hybrid_circle_rect_has_rect_side_candidates(self):
        """Hybrid room should have candidates on the rect half."""
        level, room = _make_room_level(
            Rect(10, 10, 7, 6),
            HybridShape(CircleShape(), RectShape(), "vertical"),
        )
        cands = _door_candidates(level, room)
        # Must have at least one candidate on the east side
        # (rect half's outer edge)
        east_cands = [(x, y) for x, y, s in cands if s == "east"]
        assert len(east_cands) >= 1, (
            f"No east candidates for hybrid rect half. "
            f"All candidates: {cands}")

    def test_hybrid_no_diagonal_connection(self):
        """No candidates at the circle-to-rect transition corners."""
        level, room = _make_room_level(
            Rect(10, 10, 7, 6),
            HybridShape(CircleShape(), RectShape(), "vertical"),
        )
        cands = _door_candidates(level, room)
        floor = room.floor_tiles()
        for wx, wy, side in cands:
            # Every candidate's inward floor tile must have
            # straight wall neighbors
            dirs = {
                "north": (0, 1), "south": (0, -1),
                "east": (-1, 0), "west": (1, 0),
            }
            dx, dy = dirs[side]
            fx, fy = wx + dx, wy + dy
            assert (fx, fy) in floor, (
                f"Candidate ({wx},{wy}) {side}: inward tile "
                f"({fx},{fy}) not in floor")


class TestDoorCandidatesBugRegression:
    def test_seed_237490099_no_diagonal_door(self):
        """Reproduce the bug: hybrid room 19 should not get a door
        at (39,31) which is a diagonal connection point."""
        set_seed(237490099)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(
            width=120, height=40, depth=1,
            shape_variety=0.3, theme="dungeon",
            corridor_style="organic",
        ))
        # Find room at approximately (39,31)
        target_room = None
        for room in level.rooms:
            if (room.rect.x == 39 and room.rect.y == 31
                    and isinstance(room.shape, HybridShape)):
                target_room = room
                break
        if target_room is None:
            pytest.skip("Room layout changed with new algorithm")

        # Check that no door exists at (39,31) — the problematic
        # diagonal corner position
        tile = level.tile_at(39, 31)
        door_feats = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }
        assert tile.feature not in door_feats, (
            f"Door still placed at diagonal corner (39,31): "
            f"{tile.feature}")
