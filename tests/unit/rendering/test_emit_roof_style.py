"""Pin the v5 emit_roof shape→style mapping and the
material→pattern overlay mapping.

The Rust roof painter dispatches per RoofStyle. To keep
production roof rendering byte-identical to the legacy
shape-driven dispatch, ``emit_roofs`` picks the style that the
painter would have auto-picked from ``shape_tag`` + bbox: square
rect / octagon / circle → Pyramid; wide-rect / l_shape → Gable.

The ``RoofTilePattern`` overlay reads ``Building.wall_material``:
adobe → Pantile, wood → Thatch, everything else → Plain. Forest
watchtowers (``roof_material="wood"``) override the geometry to
WitchHat for the iconic conical wooden-cap silhouette.
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
    def test_brick_default_maps_to_plain(self) -> None:
        # Default biome (brick walls) keeps Plain so the seed-7
        # town parity fixture stays byte-identical.
        assert (
            _pick_sub_pattern(_building(wall_material="brick"))
            == RoofTilePattern.Plain
        )

    def test_stone_default_maps_to_plain(self) -> None:
        assert (
            _pick_sub_pattern(_building(wall_material="stone"))
            == RoofTilePattern.Plain
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

    def test_dungeon_walls_map_to_plain(self) -> None:
        assert (
            _pick_sub_pattern(_building(wall_material="dungeon"))
            == RoofTilePattern.Plain
        )

    def test_no_building_falls_back_to_plain(self) -> None:
        # Synthetic / test buffers have no Building object.
        assert _pick_sub_pattern(None) == RoofTilePattern.Plain

    def test_unknown_material_falls_back_to_plain(self) -> None:
        assert (
            _pick_sub_pattern(_building(wall_material="ice"))
            == RoofTilePattern.Plain
        )
