"""render_level_svg dispatches between floor and building renderers.

The web client used to call render_floor_svg for every floor,
dropping the brick / stone wall overlay that building sites
ship. The level_svg helper picks render_building_floor_svg when
the level is a Building floor, falling back to the plain path
for dungeon floors and Site surfaces.
"""

from __future__ import annotations

import random

from nhc.dungeon.site import assemble_site
from nhc.rendering._building_walls import (
    BRICK_FILL, STONE_FILL,
)
from nhc.rendering.level_svg import render_level_svg


def test_building_floor_produces_masonry_overlay():
    site = assemble_site("tower", "t0", random.Random(42))
    ground = site.buildings[0].ground
    svg = render_level_svg(ground, site, seed=42)
    # Tower default wall_material is brick.
    assert BRICK_FILL in svg or STONE_FILL in svg


def test_surface_level_has_no_masonry_overlay():
    site = assemble_site("keep", "k0", random.Random(42))
    svg = render_level_svg(site.surface, site, seed=42)
    # Keep's surface has no building_id, so no masonry overlay.
    assert site.surface.building_id is None
    assert BRICK_FILL not in svg
    assert STONE_FILL not in svg


def test_plain_dungeon_level_unaffected():
    from nhc.dungeon.generator import GenerationParams
    from nhc.dungeon.pipeline import generate_level

    params = GenerationParams(
        width=20, height=20, depth=1, seed=42,
    )
    level = generate_level(params)
    # No site passed; building_id unset. Plain floor render.
    svg = render_level_svg(level, site=None, seed=42)
    assert svg.startswith("<svg")
    assert BRICK_FILL not in svg
    assert STONE_FILL not in svg
