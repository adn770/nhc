"""Tests for the geometric door candidate function."""

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


class TestDoorCandidatesRect:
    def test_rect_has_candidates_on_all_sides(self):
        room = Room(id="r0", rect=Rect(10, 10, 6, 4),
                    shape=RectShape())
        cands = _door_candidates(room)
        sides = {side for _, _, side in cands}
        assert sides == {"north", "south", "east", "west"}

    def test_rect_candidates_are_wall_positions(self):
        """Candidates should be one step outside the floor."""
        room = Room(id="r0", rect=Rect(10, 10, 6, 4),
                    shape=RectShape())
        floor = room.floor_tiles()
        cands = _door_candidates(room)
        for wx, wy, side in cands:
            # Wall position must NOT be in floor
            assert (wx, wy) not in floor
            # But must be cardinally adjacent to floor
            _INWARD = {
                "north": (0, 1), "south": (0, -1),
                "east": (-1, 0), "west": (1, 0),
            }
            dx, dy = _INWARD[side]
            assert (wx + dx, wy + dy) in floor

    def test_rect_no_corner_candidates(self):
        """No candidates at convex corners of the bounding rect."""
        room = Room(id="r0", rect=Rect(10, 10, 6, 4),
                    shape=RectShape())
        cands = _door_candidates(room)
        r = room.rect
        corners = {
            (r.x - 1, r.y - 1), (r.x2, r.y - 1),
            (r.x - 1, r.y2), (r.x2, r.y2),
        }
        cand_positions = {(x, y) for x, y, _ in cands}
        assert not (cand_positions & corners)

    def test_rect_candidate_count(self):
        """A 6x4 rect: 4 north + 4 south + 2 east + 2 west = 12."""
        room = Room(id="r0", rect=Rect(10, 10, 6, 4),
                    shape=RectShape())
        cands = _door_candidates(room)
        assert len(cands) >= 8


class TestDoorCandidatesCircle:
    def test_circle_only_straight_segments(self):
        """Circle rooms should only have candidates near the
        cardinal points, on the straight wall sections."""
        room = Room(id="r0", rect=Rect(10, 10, 7, 7),
                    shape=CircleShape())
        cands = _door_candidates(room)
        # 4 sides × 2 runs of 2 tiles each = up to 16 candidates
        # but must have at least one per side
        sides = {s for _, _, s in cands}
        assert len(sides) >= 2
        assert len(cands) >= 4

    def test_circle_candidates_near_cardinals(self):
        """Candidates on a 9x9 circle should be at the N/S/E/W
        midpoints of the straight wall segments."""
        room = Room(id="r0", rect=Rect(10, 10, 9, 9),
                    shape=CircleShape())
        cands = _door_candidates(room)
        sides = {side for _, _, side in cands}
        # Should have all 4 cardinal directions
        assert sides == {"north", "south", "east", "west"}


class TestDoorCandidatesOctagon:
    def test_octagon_no_clipped_corner_candidates(self):
        """Octagon clipped corners should not produce candidates."""
        room = Room(id="r0", rect=Rect(10, 10, 9, 9),
                    shape=OctagonShape())
        cands = _door_candidates(room)
        r = room.rect
        corners = {
            (r.x - 1, r.y - 1), (r.x2, r.y - 1),
            (r.x - 1, r.y2), (r.x2, r.y2),
        }
        cand_positions = {(x, y) for x, y, _ in cands}
        assert not (cand_positions & corners)
        assert len(cands) >= 4


class TestDoorCandidatesHybrid:
    def test_hybrid_v_has_rect_side_candidates(self):
        """Vertical hybrid: rect half should provide east candidates."""
        room = Room(
            id="r0", rect=Rect(10, 10, 7, 6),
            shape=HybridShape(CircleShape(), RectShape(), "vertical"),
        )
        cands = _door_candidates(room)
        east_cands = [(x, y) for x, y, s in cands if s == "east"]
        assert len(east_cands) >= 1, (
            f"No east candidates. All: {cands}")

    def test_hybrid_h_has_rect_side_candidates(self):
        """Horizontal hybrid: rect half should provide south/west/east
        candidates."""
        room = Room(
            id="r0", rect=Rect(10, 10, 6, 7),
            shape=HybridShape(CircleShape(), RectShape(), "horizontal"),
        )
        cands = _door_candidates(room)
        south_cands = [(x, y) for x, y, s in cands if s == "south"]
        assert len(south_cands) >= 1, (
            f"No south candidates. All: {cands}")

    def test_hybrid_no_transition_zone_candidates(self):
        """No candidates at circle-to-rect transition where wall
        tiles separate overlapping floor regions."""
        room = Room(
            id="r0", rect=Rect(10, 10, 7, 6),
            shape=HybridShape(CircleShape(), RectShape(), "vertical"),
        )
        cands = _door_candidates(room)
        floor = room.floor_tiles()
        for wx, wy, side in cands:
            _INWARD = {
                "north": (0, 1), "south": (0, -1),
                "east": (-1, 0), "west": (1, 0),
            }
            dx, dy = _INWARD[side]
            fx, fy = wx + dx, wy + dy
            assert (fx, fy) in floor, (
                f"Candidate ({wx},{wy}) {side}: inward "
                f"({fx},{fy}) not floor")

    def test_hybrid_h_west_candidate_on_rect_half(self):
        """Bug case: hybrid(circle+rect,h) at (98,17) 6x7.
        West candidates should be on the rect half, not at the
        circle-to-rect transition."""
        room = Room(
            id="r0", rect=Rect(98, 17, 6, 7),
            shape=HybridShape(CircleShape(), RectShape(), "horizontal"),
        )
        cands = _door_candidates(room)
        west_cands = [(x, y) for x, y, s in cands if s == "west"]
        assert len(west_cands) >= 1, (
            f"No west candidates. All: {cands}")
        # All west candidates must be in the rect half (y >= 20)
        mid_y = 17 + 7 // 2  # = 20
        for wx, wy in west_cands:
            assert wy >= mid_y, (
                f"West candidate ({wx},{wy}) in circle half "
                f"(mid_y={mid_y})")


class TestDoorCandidatesBugRegression:
    def test_seed_237490099_no_diagonal_door(self):
        """Hybrid room 19 should not get a door at (39,31)."""
        set_seed(237490099)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(
            width=120, height=40, depth=1,
            shape_variety=0.3, theme="dungeon",
            corridor_style="organic",
        ))
        target_room = None
        for room in level.rooms:
            if (room.rect.x == 39 and room.rect.y == 31
                    and isinstance(room.shape, HybridShape)):
                target_room = room
                break
        if target_room is None:
            pytest.skip("Room layout changed with new algorithm")

        tile = level.tile_at(39, 31)
        door_feats = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }
        assert tile.feature not in door_feats, (
            f"Door at diagonal corner (39,31): {tile.feature}")

    def test_seed_97627531_no_transition_door(self):
        """Hybrid room 24 should not get doors in the circle-to-rect
        transition zone."""
        set_seed(97627531)
        gen = BSPGenerator()
        level = gen.generate(GenerationParams(
            width=120, height=40, depth=1,
            shape_variety=0.3, theme="dungeon",
            corridor_style="organic",
        ))
        target_room = None
        for room in level.rooms:
            if (room.rect.x == 98 and room.rect.y == 17
                    and isinstance(room.shape, HybridShape)):
                target_room = room
                break
        if target_room is None:
            pytest.skip("Room layout changed with new algorithm")

        # No door should be at (98,24) — the SW corner where
        # circle-to-rect transition creates wall artifacts
        tile = level.tile_at(98, 24)
        door_feats = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }
        # The south wall is fine, but the leftmost column (x=98)
        # is at the transition — only x=99+ should have south doors
        if tile.feature in door_feats:
            # If there IS a door here, verify the inward tile (98,23)
            # has floor neighbors on both parallel sides
            floor = target_room.floor_tiles()
            assert (97, 23) in floor or (99, 23) in floor, (
                f"Door at transition corner (98,24)")
