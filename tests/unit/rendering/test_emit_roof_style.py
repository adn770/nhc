"""Pin the v5 emit_roof shape→style mapping.

The Rust roof painter dispatches per RoofStyle. To keep
production roof rendering byte-identical to the legacy
shape-driven dispatch, ``emit_roofs`` picks the style that the
painter would have auto-picked from ``shape_tag`` + bbox: square
rect / octagon / circle → Pyramid; wide-rect / l_shape → Gable.
"""

from __future__ import annotations

from types import SimpleNamespace

from nhc.rendering.emit.roof import _pick_style
from nhc.rendering.ir._fb.RoofStyle import RoofStyle


def _region(shape_tag: str, vertices: list[tuple[float, float]] | None = None):
    verts = (
        [SimpleNamespace(x=x, y=y) for (x, y) in vertices]
        if vertices is not None
        else None
    )
    outline = SimpleNamespace(vertices=verts)
    return SimpleNamespace(shapeTag=shape_tag, outline=outline)


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
