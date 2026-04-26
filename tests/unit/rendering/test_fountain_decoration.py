"""Fountain SVG decoration: 2x2 tile footprint, circle + square.

Fountains share the well's water-feature aesthetic but scale up
to a 2x2 tile footprint with a central pedestal/spout. The
top-left tile of the 2x2 carries the ``feature`` tag (``fountain``
for the circle variant, ``fountain_square`` for the square one);
the renderer paints the decoration centred on the corner shared
by the four tiles.
"""

from __future__ import annotations

from nhc.dungeon.model import (
    Level, Rect, Room, Terrain, Tile,
)
from nhc.rendering._features_svg import (
    FOUNTAIN_KEYSTONE_COUNT, FOUNTAIN_OUTER_RADIUS,
    FOUNTAIN_SQUARE_STONE_COUNT, FOUNTAIN_WATER_FILL,
    render_fountain_features,
)
from nhc.rendering._svg_helpers import CELL
from nhc.rendering.svg import render_floor_svg


def _level_with_fountain(at: tuple[int, int], tag: str) -> Level:
    """Tiny floor with a fountain anchored at ``at`` (top-left
    tile of the 2x2 footprint)."""
    level = Level.create_empty(
        "fountain_demo", "Fountain demo", 1, 12, 12,
    )
    for y in range(12):
        for x in range(12):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r0", rect=Rect(0, 0, 12, 12))]
    fx, fy = at
    level.tiles[fy][fx].feature = tag
    return level


# ── Circle fountain ────────────────────────────────────────────


def test_circle_fountain_emits_one_group():
    level = _level_with_fountain((4, 4), "fountain")
    text = "".join(render_fountain_features(level))
    assert text.count('id="fountain-4-4"') == 1
    assert FOUNTAIN_WATER_FILL in text


def test_circle_fountain_emits_keystones():
    level = _level_with_fountain((4, 4), "fountain")
    text = "".join(render_fountain_features(level))
    assert (
        text.count('class="fountain-keystone"')
        == FOUNTAIN_KEYSTONE_COUNT
    )


def test_circle_fountain_centred_on_2x2_corner():
    """The fountain's centre sits on the corner shared by the
    four tiles (tx, ty), (tx+1, ty), (tx, ty+1), (tx+1, ty+1)
    -- not the top-left tile centre. Verify by checking the
    outer ring's cx/cy match (tx+1)*CELL / (ty+1)*CELL."""
    tx, ty = 4, 4
    level = _level_with_fountain((tx, ty), "fountain")
    text = "".join(render_fountain_features(level))
    expected_cx = f'cx="{(tx + 1) * CELL:.2f}"'
    expected_cy = f'cy="{(ty + 1) * CELL:.2f}"'
    assert expected_cx in text
    assert expected_cy in text


def test_circle_fountain_has_pedestal():
    """Central pedestal/spout sits on top of the water disc so
    the fountain reads as a fountain (not just a big well)."""
    level = _level_with_fountain((4, 4), "fountain")
    text = "".join(render_fountain_features(level))
    assert 'class="fountain-pedestal"' in text


# ── Square fountain ───────────────────────────────────────────


def test_square_fountain_emits_one_group():
    level = _level_with_fountain((4, 4), "fountain_square")
    text = "".join(render_fountain_features(level))
    assert text.count('id="fountain-4-4"') == 1
    assert FOUNTAIN_WATER_FILL in text


def test_square_fountain_emits_perimeter_stones():
    level = _level_with_fountain((4, 4), "fountain_square")
    text = "".join(render_fountain_features(level))
    assert (
        text.count('class="fountain-stone"')
        == FOUNTAIN_SQUARE_STONE_COUNT
    )


def test_square_fountain_uses_rect_water():
    level = _level_with_fountain((4, 4), "fountain_square")
    text = "".join(render_fountain_features(level))
    water_idx = text.index('class="fountain-water"')
    head = text.rfind("<", 0, water_idx)
    assert text[head:water_idx].startswith("<rect")


def test_square_fountain_has_pedestal():
    level = _level_with_fountain((4, 4), "fountain_square")
    text = "".join(render_fountain_features(level))
    assert 'class="fountain-pedestal"' in text


# ── Dispatcher + integration ──────────────────────────────────


def test_dispatcher_routes_circle_vs_square():
    level = _level_with_fountain((2, 2), "fountain")
    level.tiles[7][7].feature = "fountain_square"
    text = "".join(render_fountain_features(level))
    assert text.count('id="fountain-2-2"') == 1
    assert text.count('id="fountain-7-7"') == 1
    assert (
        text.count('class="fountain-keystone"')
        == FOUNTAIN_KEYSTONE_COUNT
    )
    assert (
        text.count('class="fountain-stone"')
        == FOUNTAIN_SQUARE_STONE_COUNT
    )


def test_render_fountain_features_skips_unrelated_features():
    """Fountains do not steal the well dispatcher's tags and
    vice versa -- each feature stays on its own renderer."""
    level = _level_with_fountain((4, 4), "fountain")
    level.tiles[2][2].feature = "well"
    level.tiles[6][6].feature = "well_square"
    text = "".join(render_fountain_features(level))
    assert 'id="fountain-4-4"' in text
    assert 'id="well-2-2"' not in text
    assert 'id="well-6-6"' not in text


def test_floor_svg_paints_fountain():
    """End-to-end: render_floor_svg emits the fountain pass."""
    level = _level_with_fountain((4, 4), "fountain")
    svg = render_floor_svg(level, seed=1)
    assert 'id="fountain-4-4"' in svg
    assert FOUNTAIN_WATER_FILL in svg


def test_floor_svg_paints_square_fountain():
    level = _level_with_fountain((4, 4), "fountain_square")
    svg = render_floor_svg(level, seed=1)
    assert 'id="fountain-4-4"' in svg
    assert 'class="fountain-stone"' in svg


def test_fountain_outer_radius_spans_almost_two_tiles():
    """Sanity: the 2x2 footprint is wide enough to read as a
    fountain (not a slightly-bigger well). Outer radius must
    sit between 0.85 and 1.0 of CELL so the rim covers most of
    the 2x2 area without bleeding past it."""
    assert 0.85 * CELL <= FOUNTAIN_OUTER_RADIUS <= 1.0 * CELL


# ── Water movement: irregular ripple strokes ─────────────────


import re as _re_water

from nhc.rendering._features_svg import (
    WATER_MOVEMENT_MARK_COUNT,
)


def _all_attrs(svg: str, cls: str, attr: str) -> list[str]:
    pattern = (
        rf'class="{_re_water.escape(cls)}"[^/]*{attr}="([^"]+)"'
    )
    return _re_water.findall(pattern, svg)


class TestFountainCircleWaterMovement:
    def test_movement_mark_count(self):
        text = "".join(
            render_fountain_features(
                _level_with_fountain((4, 4), "fountain"),
            ),
        )
        count = text.count('class="fountain-water-movement"')
        assert count == WATER_MOVEMENT_MARK_COUNT

    def test_marks_are_fill_none(self):
        text = "".join(
            render_fountain_features(
                _level_with_fountain((4, 4), "fountain"),
            ),
        )
        fills = _all_attrs(text, "fountain-water-movement", "fill")
        assert fills
        for fill in fills:
            assert fill == "none"

    def test_marks_use_dasharray(self):
        text = "".join(
            render_fountain_features(
                _level_with_fountain((4, 4), "fountain"),
            ),
        )
        dashes = _all_attrs(
            text, "fountain-water-movement", "stroke-dasharray",
        )
        assert len(dashes) == WATER_MOVEMENT_MARK_COUNT


class TestFountainSquareWaterMovement:
    def test_movement_mark_count(self):
        text = "".join(
            render_fountain_features(
                _level_with_fountain((4, 4), "fountain_square"),
            ),
        )
        count = text.count('class="fountain-water-movement"')
        assert count == WATER_MOVEMENT_MARK_COUNT

    def test_marks_are_fill_none(self):
        text = "".join(
            render_fountain_features(
                _level_with_fountain((4, 4), "fountain_square"),
            ),
        )
        fills = _all_attrs(text, "fountain-water-movement", "fill")
        assert fills
        for fill in fills:
            assert fill == "none"
