"""Pin the v5 emit_roof shape→style mapping and the
material→pattern overlay mapping.

The Rust roof painter dispatches per RoofStyle. To keep
production roof rendering byte-identical to the legacy
shape-driven dispatch, ``emit_roofs`` picks the style that the
painter would have auto-picked from ``shape_tag`` + bbox: square
rect / octagon / circle → Pyramid; wide-rect / l_shape → Gable.

The ``RoofTilePattern`` overlay reads ``Building.wall_material``:
adobe → Pantile, wood → Thatch, everything else → Shingle (the
organic running-bond default). Forest watchtowers
(``roof_material="wood"``) override the geometry to WitchHat for
the iconic conical wooden-cap silhouette.
"""

from __future__ import annotations

from types import SimpleNamespace

from nhc.rendering.emit.roof import _pick_style, _pick_sub_pattern
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern


def _region(shape_tag: str, vertices: list[tuple[float, float]] | None = None):
    verts = (
        [SimpleNamespace(x=x, y=y) for (x, y) in vertices]
        if vertices is not None
        else None
    )
    outline = SimpleNamespace(vertices=verts)
    return SimpleNamespace(shapeTag=shape_tag, outline=outline)


def _building(
    *,
    wall_material: str = "brick",
    roof_material: str | None = None,
):
    return SimpleNamespace(
        wall_material=wall_material,
        roof_material=roof_material,
    )


class TestPickStyle:
    def test_square_rect_picks_pyramid(self) -> None:
        region = _region("rect", [(0, 0), (10, 0), (10, 10), (0, 10)])
        assert _pick_style(region) == RoofStyle.Pyramid

    def test_wide_rect_picks_gable(self) -> None:
        region = _region("rect", [(0, 0), (20, 0), (20, 5), (0, 5)])
        assert _pick_style(region) == RoofStyle.Gable

    def test_tall_rect_picks_gable(self) -> None:
        region = _region("rect", [(0, 0), (4, 0), (4, 12), (0, 12)])
        assert _pick_style(region) == RoofStyle.Gable

    def test_octagon_picks_pyramid(self) -> None:
        region = _region(
            "octagon",
            [(2, 0), (8, 0), (10, 2), (10, 8),
             (8, 10), (2, 10), (0, 8), (0, 2)],
        )
        assert _pick_style(region) == RoofStyle.Pyramid

    def test_circle_picks_pyramid(self) -> None:
        region = _region("circle", [(5, 0), (10, 5), (5, 10), (0, 5)])
        assert _pick_style(region) == RoofStyle.Pyramid

    def test_l_shape_picks_gable(self) -> None:
        region = _region("l_shape_nw")
        assert _pick_style(region) == RoofStyle.Gable

    def test_unknown_shape_falls_back_to_pyramid(self) -> None:
        region = _region("")
        assert _pick_style(region) == RoofStyle.Pyramid

    def test_rect_with_no_outline_falls_back_to_pyramid(self) -> None:
        region = _region("rect", None)
        assert _pick_style(region) == RoofStyle.Pyramid

    def test_bytes_shape_tag_decoded(self) -> None:
        region = SimpleNamespace(
            shapeTag=b"l_shape_se",
            outline=SimpleNamespace(vertices=None),
        )
        assert _pick_style(region) == RoofStyle.Gable

    def test_forest_watchtower_picks_witch_hat(self) -> None:
        # roof_material="wood" overrides the shape-driven pyramid
        # default — forest watchtowers read as a tall wooden cap.
        region = _region(
            "octagon",
            [(2, 0), (8, 0), (10, 2), (10, 8),
             (8, 10), (2, 10), (0, 8), (0, 2)],
        )
        building = _building(roof_material="wood")
        assert _pick_style(region, building) == RoofStyle.WitchHat

    def test_circle_watchtower_picks_witch_hat(self) -> None:
        region = _region("circle", [(5, 0), (10, 5), (5, 10), (0, 5)])
        building = _building(roof_material="wood")
        assert _pick_style(region, building) == RoofStyle.WitchHat

    def test_no_building_keeps_shape_default(self) -> None:
        # Synthetic / test buffers have no Building object; the
        # shape-driven default still fires.
        region = _region("octagon")
        assert _pick_style(region, None) == RoofStyle.Pyramid


class TestPickSubPattern:
    def test_brick_default_maps_to_shingle(self) -> None:
        # Default biome (brick walls) maps to Shingle — the
        # organic running-bond default that replaced the old
        # geometry-baked gable shingles.
        assert (
            _pick_sub_pattern(_building(wall_material="brick"))
            == RoofTilePattern.Shingle
        )

    def test_stone_default_maps_to_shingle(self) -> None:
        assert (
            _pick_sub_pattern(_building(wall_material="stone"))
            == RoofTilePattern.Shingle
        )

    def test_adobe_maps_to_pantile(self) -> None:
        # Drylands biome → adobe walls → Mediterranean S-curve
        # tile overlay.
        assert (
            _pick_sub_pattern(_building(wall_material="adobe"))
            == RoofTilePattern.Pantile
        )

    def test_wood_walls_map_to_thatch(self) -> None:
        # Marsh biome → wood walls → thatched-strand overlay.
        assert (
            _pick_sub_pattern(_building(wall_material="wood"))
            == RoofTilePattern.Thatch
        )

    def test_dungeon_walls_map_to_shingle(self) -> None:
        assert (
            _pick_sub_pattern(_building(wall_material="dungeon"))
            == RoofTilePattern.Shingle
        )

    def test_no_building_falls_back_to_shingle(self) -> None:
        # Synthetic / test buffers have no Building object.
        assert _pick_sub_pattern(None) == RoofTilePattern.Shingle

    def test_unknown_material_falls_back_to_shingle(self) -> None:
        assert (
            _pick_sub_pattern(_building(wall_material="ice"))
            == RoofTilePattern.Shingle
        )

    def test_thatch_roof_material_maps_to_thatch_pattern(self) -> None:
        # Explicit semantic roof_material wins over wall_material.
        assert (
            _pick_sub_pattern(_building(
                wall_material="brick", roof_material="thatch",
            ))
            == RoofTilePattern.Thatch
        )

    def test_slate_roof_material_maps_to_slate_pattern(self) -> None:
        assert (
            _pick_sub_pattern(_building(
                wall_material="stone", roof_material="slate",
            ))
            == RoofTilePattern.Slate
        )

    def test_tile_roof_material_maps_to_pantile_pattern(self) -> None:
        assert (
            _pick_sub_pattern(_building(
                wall_material="stone", roof_material="tile",
            ))
            == RoofTilePattern.Pantile
        )

    def test_fishscale_roof_material_maps_to_fishscale_pattern(self) -> None:
        assert (
            _pick_sub_pattern(_building(
                wall_material="stone", roof_material="fishscale",
            ))
            == RoofTilePattern.Fishscale
        )

    def test_wood_roof_material_does_not_apply_overlay(self) -> None:
        # roof_material="wood" already drives the WitchHat geometry
        # override; the overlay falls through to the wall_material
        # default (brick → Shingle). The WitchHat cap geometry is
        # what reads the wooden look; the running-bond default is
        # the neutral fallback here.
        assert (
            _pick_sub_pattern(_building(
                wall_material="brick", roof_material="wood",
            ))
            == RoofTilePattern.Shingle
        )

    def test_roof_material_overrides_wall_material(self) -> None:
        # An explicit roof_material wins over the wall_material
        # fallback even when both would map to a pattern.
        assert (
            _pick_sub_pattern(_building(
                wall_material="adobe", roof_material="slate",
            ))
            == RoofTilePattern.Slate
        )


class TestTownRoleRoofMaterial:
    """Pin the town role → roof_material mapping that gives a
    town skyline its per-building variety (commit
    38606e88-ish ladder)."""

    def test_residential_keeps_default_roof_material(self) -> None:
        # The bulk of a town is residential — no explicit
        # roof_material, so it takes the Shingle default and the
        # organic running-bond look stays dominant.
        from nhc.sites.town import _TOWN_ROLE_TO_ROOF

        assert _TOWN_ROLE_TO_ROOF.get("residential") is None

    def test_temple_role_picks_fishscale(self) -> None:
        from nhc.sites.town import _TOWN_ROLE_TO_ROOF

        assert _TOWN_ROLE_TO_ROOF["temple"] == "fishscale"

    def test_inn_and_stable_pick_thatch(self) -> None:
        from nhc.sites.town import _TOWN_ROLE_TO_ROOF

        assert _TOWN_ROLE_TO_ROOF["inn"] == "thatch"
        assert _TOWN_ROLE_TO_ROOF["stable"] == "thatch"

    def test_shop_and_training_pick_slate(self) -> None:
        from nhc.sites.town import _TOWN_ROLE_TO_ROOF

        assert _TOWN_ROLE_TO_ROOF["shop"] == "slate"
        assert _TOWN_ROLE_TO_ROOF["training"] == "slate"
