"""Shingle-roof fragment generator moved into nhc.rendering.

Used by M5's site-surface wrapper to paint visible rooftops on
the floor SVG. Historically this code lived inside the sample
generator; porting it into production lets the game's SVG
pipeline reach it without dev-time imports. The sample generator
keeps its debug-only label pill and info panel but delegates
the actual geometry to this module.
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.model import (
    CircleShape, LShape, OctagonShape, RectShape, Rect,
)
from nhc.dungeon.site import Site
from nhc.dungeon.sites.tower import assemble_tower
from nhc.dungeon.sites.town import assemble_town
from nhc.rendering._roofs import (
    building_roof_fragments,
    _roof_mode,
)


def _tower_with_shape(shape_cls, rect: Rect) -> Site:
    """Helper: build a town site (which uses varied shapes) and
    pluck out the first building of the requested shape. Falls
    back to constructing a minimal Site if none match."""
    for seed in range(30):
        site = assemble_town(f"t{seed}", random.Random(seed))
        for b in site.buildings:
            if isinstance(b.base_shape, shape_cls):
                return site, b
    raise AssertionError(f"no {shape_cls.__name__} in 30 seeds")


class TestRoofMode:
    def test_square_rect_is_pyramid(self) -> None:
        # A square rectangle picks the pyramid roof.
        b = Building(
            id="bsq",
            base_rect=Rect(0, 0, 4, 4),
            base_shape=RectShape(),
            floors=[],
        )
        assert _roof_mode(b) == "pyramid"

    def test_nonsquare_rect_is_gable(self) -> None:
        b = Building(
            id="bln",
            base_rect=Rect(0, 0, 6, 3),
            base_shape=RectShape(),
            floors=[],
        )
        assert _roof_mode(b) == "gable"

    def test_octagon_is_pyramid(self) -> None:
        b = Building(
            id="bo",
            base_rect=Rect(0, 0, 6, 6),
            base_shape=OctagonShape(),
            floors=[],
        )
        assert _roof_mode(b) == "pyramid"

    def test_l_shape_is_gable(self) -> None:
        b = Building(
            id="bl",
            base_rect=Rect(0, 0, 6, 6),
            base_shape=LShape(corner="nw"),
            floors=[],
        )
        assert _roof_mode(b) == "gable"

    def test_circle_is_skipped(self) -> None:
        b = Building(
            id="bc",
            base_rect=Rect(0, 0, 6, 6),
            base_shape=CircleShape(),
            floors=[],
        )
        assert _roof_mode(b) == "skip"


class TestBuildingRoofFragments:
    def test_site_with_only_circle_returns_empty(self) -> None:
        # Tower is a single circular building. Its roof should skip.
        site = assemble_tower("t_circle", random.Random(2))
        # Force the shape to Circle for the guard test.
        for b in site.buildings:
            b.base_shape = CircleShape()
        assert building_roof_fragments(site, seed=0) == []

    def test_rect_building_emits_clippath_and_shingles(self) -> None:
        site = assemble_town("town_roof", random.Random(5))
        frags = building_roof_fragments(site, seed=0)
        body = "".join(frags)
        assert "<defs>" in body
        # At least one clipPath roof footprint.
        assert 'id="roof_fp_' in body
        # At least one shingle rect (rect elements fill each half).
        assert "<rect" in body
        # Gable or pyramid ridge lines should emit <line>.
        assert "<line" in body

    def test_output_is_deterministic_under_fixed_seed(self) -> None:
        site = assemble_town("town_det", random.Random(11))
        a = building_roof_fragments(site, seed=9)
        b = building_roof_fragments(site, seed=9)
        assert a == b

    def test_output_varies_with_seed(self) -> None:
        site = assemble_town("town_var", random.Random(13))
        a = building_roof_fragments(site, seed=1)
        b = building_roof_fragments(site, seed=2)
        assert a != b
