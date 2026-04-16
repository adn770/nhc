"""Terminal hex renderer (M-3.1).

``build_hex_frame`` produces the ASCII-art overland view: an
odd-q staggered grid of biome + feature glyphs with the player
marker overlayed. Fog of war honours ``HexWorld.revealed`` and
the frame ends with a status line showing day / time / current
hex. Pure string output so the tests are snapshot-friendly and
the terminal client can drop it into a single ``Terminal`` print.
"""

from __future__ import annotations

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import Biome, HexCell, HexFeatureType, HexWorld, TimeOfDay
from nhc.rendering.terminal.hex_renderer import (
    BIOME_GLYPH,
    FEATURE_GLYPH,
    PLAYER_GLYPH,
    UNREVEALED_GLYPH,
    build_hex_frame,
    build_hex_status_line,
)


def _world(cells: list[tuple[int, int, Biome, HexFeatureType]]) -> HexWorld:
    w = HexWorld(pack_id="test", seed=0, width=25, height=16)
    for q, r, biome, feature in cells:
        c = HexCoord(q=q, r=r)
        w.cells[c] = HexCell(coord=c, biome=biome, feature=feature)
        w.reveal(c)
    return w


# ---------------------------------------------------------------------------
# Grid geometry
# ---------------------------------------------------------------------------


def test_frame_has_odd_q_staggered_rows() -> None:
    """Odd columns sit on odd rows, even columns on even rows."""
    w = _world([
        (0, 0, Biome.GREENLANDS, HexFeatureType.NONE),
        (1, 0, Biome.GREENLANDS, HexFeatureType.NONE),
        (2, 0, Biome.GREENLANDS, HexFeatureType.NONE),
    ])
    frame = build_hex_frame(w, player=HexCoord(q=0, r=0))
    rows = frame.splitlines()
    # q=0 (even) and q=2 (even) both land on row 0; q=1 (odd)
    # lands on row 1 (half-hex offset).
    glyph = BIOME_GLYPH[Biome.GREENLANDS]
    assert rows[0][0] == PLAYER_GLYPH  # player at q=0 overrides
    assert rows[0][4] == glyph
    assert rows[1][2] == glyph


def test_frame_grid_dimensions_for_known_world() -> None:
    """A 3x2 cluster yields a frame whose grid rows fit the
    expected staggered footprint."""
    w = _world([
        (0, 0, Biome.GREENLANDS, HexFeatureType.NONE),
        (1, 0, Biome.FOREST, HexFeatureType.NONE),
        (2, 0, Biome.GREENLANDS, HexFeatureType.NONE),
        (0, 1, Biome.GREENLANDS, HexFeatureType.NONE),
        (1, 1, Biome.FOREST, HexFeatureType.NONE),
        (2, 1, Biome.GREENLANDS, HexFeatureType.NONE),
    ])
    frame = build_hex_frame(w, player=HexCoord(q=0, r=0))
    rows = frame.splitlines()
    # Rows 0..3 cover q=0..2, r=0..1 (even rows carry q even,
    # odd rows carry q odd). Plus a trailing status line.
    assert len(rows) >= 4
    # All grid rows share the same printable width.
    grid_rows = rows[:-1]
    widths = {len(r) for r in grid_rows}
    assert len(widths) == 1, (
        f"grid rows must have uniform width, got {widths}"
    )


# ---------------------------------------------------------------------------
# Glyph choice
# ---------------------------------------------------------------------------


def test_player_glyph_overrides_biome() -> None:
    w = _world([(0, 0, Biome.MOUNTAIN, HexFeatureType.NONE)])
    frame = build_hex_frame(w, player=HexCoord(q=0, r=0))
    assert PLAYER_GLYPH in frame


def test_feature_glyph_overrides_biome() -> None:
    w = _world([(1, 0, Biome.GREENLANDS, HexFeatureType.CAVE)])
    frame = build_hex_frame(w, player=HexCoord(q=0, r=0))
    cave = FEATURE_GLYPH[HexFeatureType.CAVE]
    # Cave glyph sits at screen col 2, row 1 (odd column).
    assert frame.splitlines()[1][2] == cave


def test_unrevealed_cells_render_as_void() -> None:
    """An in-world cell not yet in ``revealed`` shows as the
    unrevealed glyph, not its biome."""
    w = HexWorld(pack_id="test", seed=0, width=25, height=16)
    c1 = HexCoord(q=0, r=0)
    c2 = HexCoord(q=2, r=0)
    w.cells[c1] = HexCell(coord=c1, biome=Biome.GREENLANDS,
                          feature=HexFeatureType.NONE)
    w.cells[c2] = HexCell(coord=c2, biome=Biome.FOREST,
                          feature=HexFeatureType.NONE)
    w.reveal(c1)   # only the first is revealed

    frame = build_hex_frame(w, player=c1)
    row0 = frame.splitlines()[0]
    assert row0[0] == PLAYER_GLYPH
    assert row0[4] == UNREVEALED_GLYPH, (
        f"unrevealed cell should render as {UNREVEALED_GLYPH!r}, "
        f"got {row0[4]!r}"
    )


# ---------------------------------------------------------------------------
# Status line
# ---------------------------------------------------------------------------


def test_status_line_shows_day_time_and_coord() -> None:
    w = _world([(3, 2, Biome.FOREST, HexFeatureType.NONE)])
    w.day = 7
    w.time = TimeOfDay.EVENING
    line = build_hex_status_line(w, player=HexCoord(q=3, r=2))
    assert "Day 7" in line
    assert "evening" in line.lower()
    assert "(3, 2)" in line
    assert "forest" in line.lower()


def test_build_hex_frame_ends_with_status_line() -> None:
    w = _world([(0, 0, Biome.GREENLANDS, HexFeatureType.NONE)])
    w.day = 2
    w.time = TimeOfDay.MORNING
    frame = build_hex_frame(w, player=HexCoord(q=0, r=0))
    last = frame.splitlines()[-1]
    assert "Day 2" in last and "morning" in last.lower()
