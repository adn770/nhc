"""Enclosure catalog pages — Palisade and Fortification across
square cells with various gate / corner-style configurations.

The user explicitly requested: "all enclosures using just square
regions (multiple samples on same page)". Catalog pages here
override ``cell_shape`` to ``"rect"`` so every cell uses a square
outline regardless of row label; the row axis carries
treatment / corner-style annotations instead.

- ``enclosures/palisade`` — single row × 5 columns of gate
  configurations on Palisade walls.
- ``enclosures/fortification-corners`` — 3 rows (Merlon, Diamond,
  Tower) × 4 columns of gate configurations on Fortification
  battlements.
"""

from __future__ import annotations

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.CutStyle import CutStyle

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    cell_bbox, make_cut, register_catalog_page, wall_factory,
)


# ── Cut-config helpers ──────────────────────────────────────────


def _build_cuts(col_idx: int, row_idx: int, edges: list[tuple[str, float, float, int]]):
    """Build a list of Cuts placed on the named edges of a cell.

    ``edges`` is a list of ``(edge, frac_lo, frac_hi, style)`` where
    ``edge`` is one of ``"top"`` / ``"bottom"`` / ``"left"`` /
    ``"right"`` and ``frac_lo`` / ``frac_hi`` are fractions of the
    edge length. Pixel coords are derived from the cell bbox at
    op-factory time.
    """
    x0, y0, x1, y1 = cell_bbox(col_idx, row_idx)
    cuts = []
    for edge, lo, hi, style in edges:
        if edge == "top":
            start = (x0 + (x1 - x0) * lo, y0)
            end = (x0 + (x1 - x0) * hi, y0)
        elif edge == "bottom":
            start = (x0 + (x1 - x0) * lo, y1)
            end = (x0 + (x1 - x0) * hi, y1)
        elif edge == "left":
            start = (x0, y0 + (y1 - y0) * lo)
            end = (x0, y0 + (y1 - y0) * hi)
        elif edge == "right":
            start = (x1, y0 + (y1 - y0) * lo)
            end = (x1, y0 + (y1 - y0) * hi)
        else:
            raise ValueError(f"unknown edge: {edge!r}")
        cuts.append(make_cut(start, end, style=style))
    return cuts


def _enclosure_factory(
    *,
    treatment: str,
    corner_style=None,
    edges: list[tuple[str, float, float, int]] | None = None,
):
    """Column op_factory wrapping ``wall_factory`` with col/row-aware
    cuts. ``edges`` is the gate spec; ``None`` ⇒ ungated.
    """
    edges_spec = edges or []

    def factory(region_id, page_seed, col_idx, row_idx):
        def cuts(_seed):
            return _build_cuts(col_idx, row_idx, edges_spec)

        wf = wall_factory(
            treatment=treatment,
            corner_style=corner_style,
            cuts=cuts if edges_spec else None,
        )
        return wf(region_id, page_seed, col_idx, row_idx)
    return factory


# ── Palisade — gate variants ────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="palisade",
    category="synthetic/enclosures",
    description=(
        "Palisade enclosure — vertical stake-pole wall on square "
        "regions, sweeping five gate configurations. Single row "
        "(no corner-style axis on Palisade). Surfaces gate-cut "
        "projection on the simplest enclosure treatment."
    ),
    columns=[
        ColumnSpec("Ungated", _enclosure_factory(treatment="Palisade")),
        ColumnSpec("Narrow Top", _enclosure_factory(
            treatment="Palisade",
            edges=[("top", 0.42, 0.58, CutStyle.WoodGate)],
        )),
        ColumnSpec("Wide Top", _enclosure_factory(
            treatment="Palisade",
            edges=[("top", 0.30, 0.70, CutStyle.WoodGate)],
        )),
        ColumnSpec("Top + Bottom", _enclosure_factory(
            treatment="Palisade",
            edges=[
                ("top", 0.40, 0.55, CutStyle.WoodGate),
                ("bottom", 0.40, 0.55, CutStyle.WoodGate),
            ],
        )),
        ColumnSpec("Four Edges", _enclosure_factory(
            treatment="Palisade",
            edges=[
                ("top", 0.42, 0.58, CutStyle.WoodGate),
                ("bottom", 0.42, 0.58, CutStyle.WoodGate),
                ("left", 0.42, 0.58, CutStyle.WoodGate),
                ("right", 0.42, 0.58, CutStyle.WoodGate),
            ],
        )),
    ],
    rows=("Palisade",),
    cell_shape="rect",
    seed=7,
    params={"treatment": "Palisade", "axis": "gate-configs"},
))


# ── Fortification — corner styles × gate configs ────────────────


def _fortification_columns_for_corner(corner_style: int) -> list[ColumnSpec]:
    """Build the 4 gate-config columns for a single corner style."""
    return [
        ColumnSpec("Ungated", _enclosure_factory(
            treatment="Fortification",
            corner_style=corner_style,
        )),
        ColumnSpec("Top Gate", _enclosure_factory(
            treatment="Fortification",
            corner_style=corner_style,
            edges=[("top", 0.40, 0.55, CutStyle.WoodGate)],
        )),
        ColumnSpec("Top + Bottom", _enclosure_factory(
            treatment="Fortification",
            corner_style=corner_style,
            edges=[
                ("top", 0.40, 0.55, CutStyle.WoodGate),
                ("bottom", 0.40, 0.55, CutStyle.WoodGate),
            ],
        )),
        ColumnSpec("T+L+R", _enclosure_factory(
            treatment="Fortification",
            corner_style=corner_style,
            edges=[
                ("top", 0.40, 0.55, CutStyle.WoodGate),
                ("left", 0.40, 0.55, CutStyle.WoodGate),
                ("right", 0.40, 0.55, CutStyle.WoodGate),
            ],
        )),
    ]


# Each row in this page uses a different corner style; columns are
# the gate configs. Since wall_factory's ``corner_style`` is fixed
# per-column (closure over corner_style at column build time), we
# need the same column-set repeated per row but parameterised on
# the row's corner style. The catalog-page model assumes columns
# are uniform across rows, so we take the easy route: have each row
# carry its own ColumnSpec set sharing a corner style. The page
# builder iterates ``columns`` once per row regardless, so we pin
# corner_style to the FIRST row's corner style and rely on a
# row-aware wrapper to swap it per row instead.

# Implementation: factor a single column set with row-aware
# corner_style lookup. The page's ``rows`` carry the corner-style
# enum codes serialised as labels; the factory looks up the
# corresponding CornerStyle via a side table.

_CORNER_STYLE_ROW = {
    "Merlon": CornerStyle.Merlon,
    "Diamond": CornerStyle.Diamond,
    "Tower": CornerStyle.Tower,
}


def _fort_row_aware_factory(
    *, edges: list[tuple[str, float, float, int]] | None = None,
):
    """Fortification factory whose corner_style depends on the row.

    Reads the row label via a closure on ``CatalogPageSpec.rows``
    indirectly — at op-factory time we know ``row_idx`` but not the
    row label. The page below pins rows to ``("Merlon", "Diamond",
    "Tower")`` so the index → label mapping is stable.
    """
    edges_spec = edges or []
    row_labels = ("Merlon", "Diamond", "Tower")

    def factory(region_id, page_seed, col_idx, row_idx):
        row_label = row_labels[row_idx] if row_idx < len(row_labels) else "Merlon"
        corner = _CORNER_STYLE_ROW[row_label]

        def cuts(_seed):
            return _build_cuts(col_idx, row_idx, edges_spec)

        wf = wall_factory(
            treatment="Fortification",
            corner_style=corner,
            cuts=cuts if edges_spec else None,
        )
        return wf(region_id, page_seed, col_idx, row_idx)
    return factory


register_catalog_page(CatalogPageSpec(
    name="fortification-corners",
    category="synthetic/enclosures",
    description=(
        "Fortification enclosure — crenellated battlement on square "
        "regions, sweeping three CornerStyles (Merlon, Diamond, "
        "Tower) × four gate configurations. Corner-style varies by "
        "row; gate config varies by column."
    ),
    columns=[
        ColumnSpec("Ungated", _fort_row_aware_factory()),
        ColumnSpec("Top Gate", _fort_row_aware_factory(edges=[
            ("top", 0.40, 0.55, CutStyle.WoodGate),
        ])),
        ColumnSpec("Top + Bottom", _fort_row_aware_factory(edges=[
            ("top", 0.40, 0.55, CutStyle.WoodGate),
            ("bottom", 0.40, 0.55, CutStyle.WoodGate),
        ])),
        ColumnSpec("T+L+R", _fort_row_aware_factory(edges=[
            ("top", 0.40, 0.55, CutStyle.WoodGate),
            ("left", 0.40, 0.55, CutStyle.WoodGate),
            ("right", 0.40, 0.55, CutStyle.WoodGate),
        ])),
    ],
    rows=("Merlon", "Diamond", "Tower"),
    cell_shape="rect",
    seed=7,
    params={"treatment": "Fortification", "axis": "corner-styles × gates"},
))


__all__ = []
