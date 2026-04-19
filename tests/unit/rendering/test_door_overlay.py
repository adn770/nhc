"""Sample-only door overlay helper.

The production game's doors are rendered by the web / console
clients from ``Tile.door_side`` metadata -- the SVG pipeline never
draws them. But the sample generator (tests/samples/) produces
standalone SVGs for offline design review, and those want visible
doors so building walls read correctly. This module supplies a
helper the sample generator imports; the game's SVG path keeps
ignoring it.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.rendering._doors_svg import door_overlay_fragments
from nhc.rendering._svg_helpers import CELL, PADDING


def _make_level_with_door(
    dx: int, dy: int, *,
    door_side: str,
    feature: str = "door_closed",
) -> Level:
    """A 5x5 FLOOR level with one door tile at (dx, dy)."""
    level = Level.create_empty("test", "test", 0, 5, 5)
    for y in range(5):
        for x in range(5):
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.STREET,
            )
    level.tiles[dy][dx] = Tile(
        terrain=Terrain.FLOOR,
        feature=feature,
        surface_type=SurfaceType.STREET,
        door_side=door_side,
    )
    return level


class TestDoorOverlayFragments:
    def test_empty_level_returns_empty_list(self) -> None:
        level = Level.create_empty("empty", "empty", 0, 3, 3)
        assert door_overlay_fragments(level, seed=0) == []

    def test_level_with_no_doors_returns_empty(self) -> None:
        level = _make_level_with_door(1, 1, door_side="north")
        # Strip the door we added -- should return [].
        level.tiles[1][1] = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.STREET,
        )
        assert door_overlay_fragments(level, seed=0) == []

    def test_closed_door_produces_one_rect(self) -> None:
        level = _make_level_with_door(2, 2, door_side="east")
        frags = door_overlay_fragments(level, seed=0)
        assert len(frags) == 1
        assert frags[0].startswith("<rect")

    def test_east_door_on_right_half_of_tile(self) -> None:
        level = _make_level_with_door(2, 2, door_side="east")
        frags = door_overlay_fragments(level, seed=0)
        # Tile (2, 2) spans x = PADDING + 2*CELL .. + 3*CELL.
        tile_left = PADDING + 2 * CELL
        # East door should start in the right half: x > midpoint.
        # Extract the x attribute.
        import re
        m = re.search(r'x="([0-9.]+)"', frags[0])
        assert m is not None
        x_val = float(m.group(1))
        assert x_val >= tile_left + CELL / 2, (
            f"east door x={x_val} should be in right half "
            f"(>= {tile_left + CELL / 2})"
        )

    def test_west_door_on_left_half_of_tile(self) -> None:
        level = _make_level_with_door(2, 2, door_side="west")
        frags = door_overlay_fragments(level, seed=0)
        import re
        m = re.search(r'x="([0-9.]+)"', frags[0])
        assert m is not None
        tile_left = PADDING + 2 * CELL
        x_val = float(m.group(1))
        assert x_val < tile_left + CELL / 2

    def test_north_door_on_top_half_of_tile(self) -> None:
        level = _make_level_with_door(2, 2, door_side="north")
        frags = door_overlay_fragments(level, seed=0)
        import re
        m = re.search(r'y="([0-9.]+)"', frags[0])
        assert m is not None
        tile_top = PADDING + 2 * CELL
        y_val = float(m.group(1))
        assert y_val < tile_top + CELL / 2

    def test_south_door_on_bottom_half_of_tile(self) -> None:
        level = _make_level_with_door(2, 2, door_side="south")
        frags = door_overlay_fragments(level, seed=0)
        import re
        m = re.search(r'y="([0-9.]+)"', frags[0])
        assert m is not None
        tile_top = PADDING + 2 * CELL
        y_val = float(m.group(1))
        assert y_val >= tile_top + CELL / 2

    def test_door_without_side_falls_back_to_centre(self) -> None:
        """Interior dungeons sometimes leave door_side empty. The
        overlay should still emit a small marker so the sample
        shows the door, just without edge snap."""
        level = _make_level_with_door(2, 2, door_side="")
        frags = door_overlay_fragments(level, seed=0)
        assert len(frags) == 1

    def test_closed_vs_open_door_have_different_fills(self) -> None:
        closed = _make_level_with_door(
            2, 2, door_side="east", feature="door_closed",
        )
        opened = _make_level_with_door(
            2, 2, door_side="east", feature="door_open",
        )
        closed_frags = door_overlay_fragments(closed, seed=0)
        opened_frags = door_overlay_fragments(opened, seed=0)
        # Different fills so a closed door reads as solid and an
        # open one as gapped.
        assert closed_frags[0] != opened_frags[0]

    def test_deterministic_for_fixed_seed(self) -> None:
        level = _make_level_with_door(2, 2, door_side="east")
        a = door_overlay_fragments(level, seed=7)
        b = door_overlay_fragments(level, seed=7)
        assert a == b
