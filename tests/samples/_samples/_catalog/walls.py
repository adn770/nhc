"""Wall catalog pages.

- ``walls/treatments`` — 5 wall treatments (PlainStroke, Masonry,
  Partition, Palisade, Fortification) × 3 shapes.
- ``walls/corner-styles`` — 3 CornerStyle variants on Fortification
  base × 3 shapes.
- ``walls/cuts-single-gate`` — single WoodGate cut on the top edge
  per shape, four columns showing different gate widths / cut
  styles for visual inspection.
- ``walls/cuts-multi`` — multi-cut variants per shape (2-3 gates,
  mixed cut styles).
"""

from __future__ import annotations

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.CutStyle import CutStyle

from ._builder import (
    CELL_PX, CatalogPageSpec, ColumnSpec,
    cell_bbox, make_cut, register_catalog_page, wall_factory,
)


# ── Wall treatments × shapes ────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="treatments",
    category="synthetic/walls",
    description=(
        "Five WallTreatment variants — PlainStroke, Masonry, "
        "Partition, Palisade, Fortification — across rect / "
        "octagon / circle shape rows. Each cell paints a Plain "
        "base then strokes the cell outline with the treatment's "
        "wall_material."
    ),
    columns=[
        ColumnSpec("PlainStroke", wall_factory(treatment="PlainStroke")),
        ColumnSpec("Masonry", wall_factory(treatment="Masonry")),
        ColumnSpec("Partition", wall_factory(treatment="Partition")),
        ColumnSpec("Palisade", wall_factory(treatment="Palisade")),
        ColumnSpec(
            "Fortification",
            wall_factory(treatment="Fortification"),
        ),
    ],
    seed=7,
    params={"axis": "treatments"},
))


# ── CornerStyle variants on Fortification ───────────────────────


register_catalog_page(CatalogPageSpec(
    name="corner-styles",
    category="synthetic/walls",
    description=(
        "CornerStyle variants (Merlon, Diamond, Tower) on the "
        "Fortification battlement, swept across rect / octagon / "
        "circle shape rows. Visualises corner rendering on "
        "non-axis-aligned edges (octagon / circle)."
    ),
    columns=[
        ColumnSpec("Merlon", wall_factory(
            treatment="Fortification", corner_style=CornerStyle.Merlon,
        )),
        ColumnSpec("Diamond", wall_factory(
            treatment="Fortification", corner_style=CornerStyle.Diamond,
        )),
        ColumnSpec("Tower", wall_factory(
            treatment="Fortification", corner_style=CornerStyle.Tower,
        )),
    ],
    seed=7,
    params={"treatment": "Fortification", "axis": "corner-styles"},
))


# ── Cut catalog: single gate on top edge ────────────────────────


def _top_edge_cut_factory(*, frac_lo: float, frac_hi: float, style: int):
    """Build a ``cuts(page_seed) -> list[Cut]`` callable that places
    one cut on the top edge of each cell.

    Cell bboxes are derived inside the closure from ``(col, row)``
    so the cut always lands relative to the cell currently being
    painted. Cell column 0 receives the smaller cut, etc.
    """
    def cuts_for_cell(_page_seed: int, col: int = 0, row: int = 0):
        x0, y0, x1, _ = cell_bbox(col, row)
        cx_lo = x0 + (x1 - x0) * frac_lo
        cx_hi = x0 + (x1 - x0) * frac_hi
        return [make_cut((cx_lo, y0), (cx_hi, y0), style=style)]
    return cuts_for_cell


def _wall_with_top_cut(*, frac_lo: float, frac_hi: float, style: int):
    """Wrap ``wall_factory`` so the cut callable receives the col/row
    indices via partial application. ``wall_factory`` calls
    ``cuts(page_seed)`` so we adapt by capturing col/row at the
    factory level.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        # Re-build a temporary wall_factory inline so we can pass
        # the col/row-aware cut list. Keeps ``wall_factory``'s
        # simple ``cuts: (seed) -> list[Cut]`` signature.
        x0, y0, x1, _ = cell_bbox(col_idx, row_idx)
        cx_lo = x0 + (x1 - x0) * frac_lo
        cx_hi = x0 + (x1 - x0) * frac_hi

        def cuts(_seed: int):
            return [make_cut((cx_lo, y0), (cx_hi, y0), style=style)]

        # Use Fortification so the cut visibly punches the
        # battlement; CornerStyle stays at default Merlon.
        wf = wall_factory(treatment="Fortification", cuts=cuts)
        return wf(region_id, page_seed, col_idx, row_idx)
    return factory


register_catalog_page(CatalogPageSpec(
    name="cuts-single-gate",
    category="synthetic/walls",
    description=(
        "Single-gate Cut on the top edge of each cell. Four columns "
        "vary cut width + style (narrow WoodGate, wider WoodGate, "
        "DoorWood, DoorIron) across rect / octagon / circle shapes. "
        "Cuts intersect the wall outline at pixel-space pairs; the "
        "v5 painter projects them back to per-edge intervals."
    ),
    columns=[
        ColumnSpec("Narrow Wood", _wall_with_top_cut(
            frac_lo=0.42, frac_hi=0.58, style=CutStyle.WoodGate,
        )),
        ColumnSpec("Wide Wood", _wall_with_top_cut(
            frac_lo=0.30, frac_hi=0.70, style=CutStyle.WoodGate,
        )),
        ColumnSpec("Door Wood", _wall_with_top_cut(
            frac_lo=0.40, frac_hi=0.55, style=CutStyle.DoorWood,
        )),
        ColumnSpec("Door Iron", _wall_with_top_cut(
            frac_lo=0.40, frac_hi=0.55, style=CutStyle.DoorIron,
        )),
    ],
    seed=7,
    params={"axis": "cuts"},
))


# ── Cut catalog: multi-cut variants ─────────────────────────────


def _wall_with_two_cuts(
    *,
    top_lo: float, top_hi: float, top_style: int,
    bottom_lo: float, bottom_hi: float, bottom_style: int,
):
    """Wall factory with one cut on the top edge + one on the bottom."""
    def factory(region_id, page_seed, col_idx, row_idx):
        x0, y0, x1, y1 = cell_bbox(col_idx, row_idx)
        top_lo_px = x0 + (x1 - x0) * top_lo
        top_hi_px = x0 + (x1 - x0) * top_hi
        bot_lo_px = x0 + (x1 - x0) * bottom_lo
        bot_hi_px = x0 + (x1 - x0) * bottom_hi

        def cuts(_seed: int):
            return [
                make_cut(
                    (top_lo_px, y0), (top_hi_px, y0),
                    style=top_style,
                ),
                make_cut(
                    (bot_lo_px, y1), (bot_hi_px, y1),
                    style=bottom_style,
                ),
            ]

        wf = wall_factory(treatment="Fortification", cuts=cuts)
        return wf(region_id, page_seed, col_idx, row_idx)
    return factory


def _wall_with_three_cuts(
    *,
    cuts_spec: list[tuple[str, float, float, int]],
):
    """Wall factory with multiple cuts on labelled edges.

    ``cuts_spec`` is a list of ``(edge, frac_lo, frac_hi, style)``
    where ``edge`` is one of ``"top"`` / ``"right"`` / ``"bottom"``
    / ``"left"``.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        x0, y0, x1, y1 = cell_bbox(col_idx, row_idx)

        def coords_for_edge(edge: str, lo: float, hi: float):
            if edge == "top":
                return ((x0 + (x1 - x0) * lo, y0), (x0 + (x1 - x0) * hi, y0))
            if edge == "bottom":
                return ((x0 + (x1 - x0) * lo, y1), (x0 + (x1 - x0) * hi, y1))
            if edge == "left":
                return ((x0, y0 + (y1 - y0) * lo), (x0, y0 + (y1 - y0) * hi))
            if edge == "right":
                return ((x1, y0 + (y1 - y0) * lo), (x1, y0 + (y1 - y0) * hi))
            raise ValueError(f"unknown edge: {edge!r}")

        def cuts(_seed: int):
            return [
                make_cut(*coords_for_edge(edge, lo, hi), style=style)
                for edge, lo, hi, style in cuts_spec
            ]

        wf = wall_factory(treatment="Fortification", cuts=cuts)
        return wf(region_id, page_seed, col_idx, row_idx)
    return factory


register_catalog_page(CatalogPageSpec(
    name="cuts-multi",
    category="synthetic/walls",
    description=(
        "Multi-cut variants — two and three gates per cell, mixed "
        "CutStyles + edges, across rect / octagon / circle shapes. "
        "Visualises projection of multiple cut intervals onto a "
        "single outline + gate styling on non-axis-aligned edges."
    ),
    columns=[
        ColumnSpec(
            "Top + Bottom",
            _wall_with_two_cuts(
                top_lo=0.40, top_hi=0.55, top_style=CutStyle.WoodGate,
                bottom_lo=0.40, bottom_hi=0.55,
                bottom_style=CutStyle.WoodGate,
            ),
        ),
        ColumnSpec(
            "T+L+R Doors",
            _wall_with_three_cuts(cuts_spec=[
                ("top", 0.40, 0.55, CutStyle.DoorWood),
                ("left", 0.40, 0.55, CutStyle.DoorWood),
                ("right", 0.40, 0.55, CutStyle.DoorWood),
            ]),
        ),
        ColumnSpec(
            "Mixed Styles",
            _wall_with_three_cuts(cuts_spec=[
                ("top", 0.30, 0.50, CutStyle.WoodGate),
                ("bottom", 0.50, 0.70, CutStyle.PortcullisGate),
                ("right", 0.40, 0.60, CutStyle.DoorSecret),
            ]),
        ),
        ColumnSpec(
            "Twin Top",
            _wall_with_three_cuts(cuts_spec=[
                ("top", 0.20, 0.35, CutStyle.WoodGate),
                ("top", 0.65, 0.80, CutStyle.WoodGate),
                ("bottom", 0.40, 0.60, CutStyle.DoorWood),
            ]),
        ),
    ],
    seed=7,
    params={"axis": "cuts-multi"},
))


__all__ = []
