"""Tests for field of view computation."""

from nhc.utils.fov import compute_fov


def _make_room(width: int, height: int) -> set[tuple[int, int]]:
    """Create a set of wall positions forming a room border."""
    walls = set()
    for x in range(width):
        walls.add((x, 0))
        walls.add((x, height - 1))
    for y in range(height):
        walls.add((0, y))
        walls.add((width - 1, y))
    return walls


class TestFOV:
    def test_origin_always_visible(self):
        visible = compute_fov(5, 5, 8, lambda x, y: False)
        assert (5, 5) in visible

    def test_open_field_symmetric(self):
        visible = compute_fov(10, 10, 3, lambda x, y: False)
        # Should be roughly circular, symmetric
        assert (10, 7) in visible   # North
        assert (10, 13) in visible  # South
        assert (7, 10) in visible   # West
        assert (13, 10) in visible  # East

    def test_wall_blocks_sight(self):
        # Wall at (5, 3), observer at (5, 5)
        def is_blocking(x, y):
            return x == 5 and y == 3

        visible = compute_fov(5, 5, 8, is_blocking)
        # Wall itself should be visible
        assert (5, 3) in visible
        # Tile behind wall should not be visible
        assert (5, 2) not in visible

    def test_room_visibility(self):
        # 10x10 room, observer in center
        walls = _make_room(10, 10)

        def is_blocking(x, y):
            return (x, y) in walls

        visible = compute_fov(5, 5, 8, is_blocking)

        # All interior tiles should be visible
        for x in range(1, 9):
            for y in range(1, 9):
                assert (x, y) in visible, f"({x}, {y}) should be visible"

        # Walls should be visible
        assert (0, 5) in visible
        assert (9, 5) in visible

    def test_radius_limits_visibility(self):
        visible = compute_fov(10, 10, 2, lambda x, y: False)
        # Tiles at distance 3 should not be visible
        assert (10, 7) not in visible
        assert (13, 10) not in visible

    def test_corridor_visibility(self):
        # Long narrow corridor: walls everywhere except y=5
        def is_blocking(x, y):
            return y != 5

        visible = compute_fov(5, 5, 8, is_blocking)
        # Should see along the corridor
        assert (10, 5) in visible
        # Should not see through walls
        assert (5, 3) not in visible
