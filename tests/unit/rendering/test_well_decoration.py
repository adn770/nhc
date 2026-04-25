"""Well-feature SVG decoration: stone ring + water disc.

Sub-hex wayside / well sites place ``feature = "well"`` on the
centerpiece tile. The renderer paints a Dyson-style ring of
keystone stones around the tile centre with a blue water disc
inside, so the well is visible on the surface SVG even though
the interactable is an ECS entity overlaid by the client.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import (
    Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
)
from nhc.hexcrawl.model import MinorFeatureType
from nhc.rendering._features_svg import (
    WELL_KEYSTONE_COUNT, WELL_SQUARE_STONE_COUNT, WELL_WATER_FILL,
    render_well_features,
)
from nhc.rendering.svg import render_floor_svg
from nhc.sites.wayside import assemble_wayside


def _level_with_well(at: tuple[int, int]) -> Level:
    """Tiny floor with a single well tile at ``at`` for direct
    fragment-emitter tests."""
    level = Level.create_empty(
        "well_demo", "Well demo", 1, 8, 8,
    )
    for y in range(8):
        for x in range(8):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r0", rect=Rect(0, 0, 8, 8))]
    fx, fy = at
    level.tiles[fy][fx].feature = "well"
    return level


def test_render_well_features_emits_one_group_per_well():
    level = _level_with_well((4, 4))
    frags = render_well_features(level)
    text = "".join(frags)
    assert text.count('id="well-') == 1
    assert WELL_WATER_FILL in text
    # Exactly one ring of keystones per well.
    assert text.count("<path") >= WELL_KEYSTONE_COUNT


def test_render_well_features_skips_levels_without_wells():
    level = _level_with_well((4, 4))
    level.tiles[4][4].feature = None
    assert render_well_features(level) == []


def test_render_well_features_handles_multiple_wells():
    level = _level_with_well((2, 2))
    level.tiles[5][5].feature = "well"
    text = "".join(render_well_features(level))
    assert text.count('id="well-') == 2


def test_floor_svg_contains_well_decoration():
    """End-to-end: render_floor_svg picks up the well feature."""
    level = _level_with_well((4, 4))
    svg = render_floor_svg(level, seed=1)
    assert WELL_WATER_FILL in svg
    assert 'id="well-4-4"' in svg


def test_wayside_well_site_renders_well():
    """Sub-hex wayside/WELL site: assembler tags the centerpiece
    tile with feature='well'; the floor renderer must surface a
    visible decoration on it."""
    site = assemble_wayside(
        "wayside_well_t", random.Random(7),
        feature=MinorFeatureType.WELL,
    )
    svg = render_floor_svg(site.surface, seed=7)
    assert WELL_WATER_FILL in svg
    # Ring fragments are stamped at the tagged tile coords.
    well_tiles = [
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, t in enumerate(row)
        if t.feature == "well"
    ]
    assert len(well_tiles) == 1
    fx, fy = well_tiles[0]
    assert f'id="well-{fx}-{fy}"' in svg


def test_render_level_svg_paints_well_on_site_surface():
    """The production dispatcher used by the web app
    (``render_level_svg``) routes site surfaces through
    ``render_site_surface_svg`` which composes the floor SVG +
    roofs + enclosure. The well decoration must survive that
    composition so the player actually sees the well in-game,
    not just in the standalone sample SVGs."""
    from nhc.rendering.level_svg import render_level_svg

    site = assemble_wayside(
        "wayside_well_prod", random.Random(11),
        feature=MinorFeatureType.WELL,
    )
    svg = render_level_svg(site.surface, site=site, seed=11)
    assert WELL_WATER_FILL in svg
    well_tiles = [
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, t in enumerate(row)
        if t.feature == "well"
    ]
    assert len(well_tiles) == 1
    fx, fy = well_tiles[0]
    assert f'id="well-{fx}-{fy}"' in svg


def test_keystone_count_matches_constant():
    """Geometric sanity: each well emits at least
    WELL_KEYSTONE_COUNT keystone paths (one per stone)."""
    level = _level_with_well((4, 4))
    text = "".join(render_well_features(level))
    # The ring contains exactly WELL_KEYSTONE_COUNT keystone
    # <path> elements plus a small number of structural shapes
    # (water disc + outer ring); count keystones via the unique
    # marker class.
    assert text.count('class="well-keystone"') == WELL_KEYSTONE_COUNT


# ── Square wells ──────────────────────────────────────────────


def _level_with_square_well(at: tuple[int, int]) -> Level:
    """Tiny floor with a single square-well tile at ``at``."""
    level = Level.create_empty(
        "square_well_demo", "Square well demo", 1, 8, 8,
    )
    for y in range(8):
        for x in range(8):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r0", rect=Rect(0, 0, 8, 8))]
    fx, fy = at
    level.tiles[fy][fx].feature = "well_square"
    return level


def test_render_square_well_emits_one_group_per_tile():
    level = _level_with_square_well((4, 4))
    text = "".join(render_well_features(level))
    assert text.count('id="well-') == 1
    assert WELL_WATER_FILL in text


def test_render_square_well_uses_rect_water_not_circle():
    """Square wells use a rounded ``<rect>`` for the water pool;
    circular wells use a ``<circle>``. The dispatcher must route
    to the right shape based on the feature tag."""
    level = _level_with_square_well((4, 4))
    text = "".join(render_well_features(level))
    assert 'class="well-water"' in text
    # The water pool fragment is a rect on square wells.
    water_idx = text.index('class="well-water"')
    head = text.rfind("<", 0, water_idx)
    assert text[head:water_idx].startswith("<rect")


def test_render_square_well_emits_perimeter_stones():
    level = _level_with_square_well((4, 4))
    text = "".join(render_well_features(level))
    assert text.count('class="well-stone"') == WELL_SQUARE_STONE_COUNT


def test_dispatcher_routes_circle_vs_square():
    """A level with both kinds of well must produce one of each
    shape -- circle keystones for "well", flat stones for
    "well_square". Neither tag steals the other's geometry."""
    level = _level_with_square_well((2, 2))
    level.tiles[5][5].feature = "well"
    text = "".join(render_well_features(level))
    assert text.count('id="well-2-2"') == 1
    assert text.count('id="well-5-5"') == 1
    assert text.count('class="well-keystone"') == WELL_KEYSTONE_COUNT
    assert text.count('class="well-stone"') == WELL_SQUARE_STONE_COUNT


def test_floor_svg_paints_square_well():
    """End-to-end: render_floor_svg picks up a square well."""
    level = _level_with_square_well((4, 4))
    svg = render_floor_svg(level, seed=1)
    assert 'id="well-4-4"' in svg
    assert WELL_WATER_FILL in svg
    assert 'class="well-stone"' in svg
