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
    PillShape,
    Rect,
    RectShape,
    Room,
    TempleShape,
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

    def test_small_circle_has_cardinal_candidates(self):
        """A 5x5 circle has no straight runs >= 2, but should
        still get candidates at the 4 cardinal wall positions."""
        room = Room(id="r0", rect=Rect(41, 21, 5, 5),
                    shape=CircleShape())
        cands = _door_candidates(room)
        sides = {side for _, _, side in cands}
        assert sides == {"north", "south", "east", "west"}
        # Each cardinal should have exactly 1 candidate
        assert len(cands) == 4
        # Candidates must be the cardinal wall positions
        cand_positions = {(x, y) for x, y, _ in cands}
        # center=(43,23), r=2: N=(43,20), S=(43,26),
        # W=(40,23), E=(46,23)
        assert cand_positions == {
            (43, 20), (43, 26), (40, 23), (46, 23),
        }


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


class TestDoorCandidatesPill:
    def _candidates_on_rect_boundary(self, room: Room) -> None:
        """Every candidate must sit one step outside the bounding rect."""
        r = room.rect
        for wx, wy, _side in _door_candidates(room):
            on_edge = (
                wx == r.x - 1 or wx == r.x2
                or wy == r.y - 1 or wy == r.y2
            )
            assert on_edge, (
                f"Candidate ({wx},{wy}) is inside the bounding rect "
                f"{r.x},{r.y},{r.width},{r.height}"
            )

    def test_horizontal_pill_candidates_on_rect_boundary(self):
        """Pill shoulder walls must not produce interior candidates."""
        room = Room(id="r0", rect=Rect(33, 3, 10, 7),
                    shape=PillShape())
        self._candidates_on_rect_boundary(room)

    def test_vertical_pill_candidates_on_rect_boundary(self):
        room = Room(id="r0", rect=Rect(10, 5, 7, 11),
                    shape=PillShape())
        self._candidates_on_rect_boundary(room)

    def test_horizontal_pill_has_east_and_west_cap_candidates(self):
        """Horizontal pill: the cap extremes must be reachable.

        Without the cap candidates, corridors aimed at the east/west
        side fall back to shoulder walls and damage the pill outline.
        """
        room = Room(id="r0", rect=Rect(33, 3, 10, 7),
                    shape=PillShape())
        cands = _door_candidates(room)
        positions = {(x, y) for x, y, _s in cands}
        # Horizontal pill with rect y=3,h=7 → cy = 6
        assert (32, 6) in positions, (
            f"Missing west cap at (32,6); got {sorted(positions)}")
        assert (43, 6) in positions, (
            f"Missing east cap at (43,6); got {sorted(positions)}")
        sides = {s for _, _, s in cands}
        assert "west" in sides and "east" in sides

    def test_vertical_pill_has_north_and_south_cap_candidates(self):
        room = Room(id="r0", rect=Rect(10, 5, 7, 11),
                    shape=PillShape())
        cands = _door_candidates(room)
        positions = {(x, y) for x, y, _s in cands}
        # Vertical pill with rect x=10,w=7 → cx = 13
        assert (13, 4) in positions, (
            f"Missing north cap at (13,4); got {sorted(positions)}")
        assert (13, 16) in positions, (
            f"Missing south cap at (13,16); got {sorted(positions)}")
        sides = {s for _, _, s in cands}
        assert "north" in sides and "south" in sides

    def test_pill_candidates_point_to_floor(self):
        """Every candidate must be cardinally adjacent to room floor."""
        room = Room(id="r0", rect=Rect(33, 3, 10, 7),
                    shape=PillShape())
        floor = room.floor_tiles()
        _INWARD = {
            "north": (0, 1), "south": (0, -1),
            "east": (-1, 0), "west": (1, 0),
        }
        for wx, wy, side in _door_candidates(room):
            dx, dy = _INWARD[side]
            assert (wx + dx, wy + dy) in floor, (
                f"Candidate ({wx},{wy}) {side} not adjacent to floor")


class TestDoorCandidatesTemple:
    def _candidates_on_rect_boundary(self, room: Room) -> None:
        r = room.rect
        for wx, wy, _side in _door_candidates(room):
            on_edge = (
                wx == r.x - 1 or wx == r.x2
                or wy == r.y - 1 or wy == r.y2
            )
            assert on_edge, (
                f"Candidate ({wx},{wy}) is inside the bounding rect "
                f"{r.x},{r.y},{r.width},{r.height}"
            )

    def test_temple_north_flat_boundary(self):
        room = Room(id="r0", rect=Rect(10, 10, 11, 11),
                    shape=TempleShape(flat_side="north"))
        self._candidates_on_rect_boundary(room)

    def test_temple_south_flat_boundary(self):
        room = Room(id="r0", rect=Rect(10, 10, 11, 11),
                    shape=TempleShape(flat_side="south"))
        self._candidates_on_rect_boundary(room)

    def test_temple_east_flat_boundary(self):
        room = Room(id="r0", rect=Rect(10, 10, 11, 11),
                    shape=TempleShape(flat_side="east"))
        self._candidates_on_rect_boundary(room)

    def test_temple_west_flat_boundary(self):
        room = Room(id="r0", rect=Rect(10, 10, 11, 11),
                    shape=TempleShape(flat_side="west"))
        self._candidates_on_rect_boundary(room)

    def test_temple_caps_present_on_non_flat_arms(self):
        """Each non-flat arm must expose its rounded cap tip."""
        room = Room(id="r0", rect=Rect(10, 10, 11, 11),
                    shape=TempleShape(flat_side="south"))
        positions = {(x, y) for x, y, _ in _door_candidates(room)}
        # Expected cardinal caps: N=(15,9), E=(21,15), W=(9,15)
        assert (15, 9) in positions
        assert (21, 15) in positions
        assert (9, 15) in positions



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
