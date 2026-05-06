"""Catalog page builder.

A catalog page = one FloorIR FlatBuffer with a grid of cell
regions. Each cell carries one paint / stroke / fixture op
showcasing the column's material (or wall treatment / fixture
kind / etc.) on the row's shape.

Bypasses the ``emit_all`` v5 pipeline (which derives ops from a
``Level`` + ``ctx``); the page builder hand-constructs regions +
ops and packs them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import flatbuffers

from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.ir._fb.FloorIR import FloorIRT
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir_emitter import (
    _FILE_IDENTIFIER, _SCHEMA_MAJOR, _SCHEMA_MINOR,
)

from ._shapes import SHAPE_BUILDERS


# ── Layout constants ─────────────────────────────────────────────

# Maximum columns per page. The user requested 6 columns as the
# manageable cap; pages with fewer cell columns shrink horizontally.
MAX_COLS = 6

# Each cell is a 4-tile × 4-tile content area (128 × 128 px at
# CELL = 32). Gives painters room to show seam grids + grain noise
# without crushing detail at the catalog cell scale.
CELL_TILES = 4
CELL_PX = CELL_TILES * CELL  # 128

# Gutter between adjacent cells in pixels. Half a tile is enough to
# read the cell boundary without wasting canvas space.
GUTTER_PX = CELL // 2  # 16

# Margins for axis labels: left for shape names (rotated 90°), top
# for column header (material name), right + bottom modest padding.
LEFT_MARGIN_PX = 24
TOP_MARGIN_PX = 32
RIGHT_MARGIN_PX = 16
BOTTOM_MARGIN_PX = 16


# ── Page spec ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ColumnSpec:
    """One column of a catalog page.

    Attributes:
        label: Header text rendered above the column (e.g.
            ``"Cobblestone Herringbone"``).
        op_factory: ``(region_id, page_seed, col_idx, row_idx)
            -> OpEntryT`` callable that returns the op (PaintOp /
            StrokeOp / FixtureOp / etc.) for the cell at this
            column. The page builder anchors the op to the cell's
            region by passing ``region_id`` for ``PaintOp.region_ref``
            (or its equivalent on other op types).
    """

    label: str
    op_factory: Callable[[str, int, int, int], OpEntryT]


# Default row sweep: rect / octagon / circle. Pages can override
# (e.g. enclosures use square only) by passing a custom rows list.
DEFAULT_ROWS: tuple[str, ...] = ("rect", "octagon", "circle")


@dataclass(frozen=True)
class CatalogPageSpec:
    """One catalog page.

    Attributes:
        name: Filename stem under ``<category>/`` (e.g.
            ``"cobblestone"``).
        category: Output category path (e.g. ``"synthetic/floors/stone"``).
        description: One-line summary echoed into the JSON sidecar.
        columns: 1 .. ``MAX_COLS`` ``ColumnSpec``s. Page width
            scales with column count.
        rows: Row labels — one per shape. Default
            ``("rect", "octagon", "circle")``.
        seed: Page seed — propagated to every op factory's
            ``page_seed`` argument.
    """

    name: str
    category: str
    description: str
    columns: list[ColumnSpec]
    rows: tuple[str, ...] = DEFAULT_ROWS
    seed: int = 7
    # Static recipe echoed into the .json sidecar.
    params: dict[str, Any] = field(default_factory=dict)


# ── Page geometry ────────────────────────────────────────────────


def page_pixel_dimensions(n_cols: int, n_rows: int) -> tuple[int, int]:
    """Pixel size of the page content area (excluding PADDING).

    The renderer adds ``PADDING`` (32 px) around the content; the
    final PNG size is ``(width + 2*PADDING, height + 2*PADDING)``.
    """
    if n_cols < 1 or n_cols > MAX_COLS:
        raise ValueError(f"n_cols {n_cols} not in 1..{MAX_COLS}")
    width = (
        LEFT_MARGIN_PX
        + n_cols * CELL_PX + (n_cols - 1) * GUTTER_PX
        + RIGHT_MARGIN_PX
    )
    height = (
        TOP_MARGIN_PX
        + n_rows * CELL_PX + (n_rows - 1) * GUTTER_PX
        + BOTTOM_MARGIN_PX
    )
    return width, height


def cell_bbox(col: int, row: int) -> tuple[int, int, int, int]:
    """Pixel bbox ``(x0, y0, x1, y1)`` of the cell at ``(col, row)``.

    Coordinates are in the page's content space (PADDING is added
    by the renderer's outer transform).
    """
    x0 = LEFT_MARGIN_PX + col * (CELL_PX + GUTTER_PX)
    y0 = TOP_MARGIN_PX + row * (CELL_PX + GUTTER_PX)
    return x0, y0, x0 + CELL_PX, y0 + CELL_PX


def _ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


# ── Buffer assembly ──────────────────────────────────────────────


def build_catalog_buffer(spec: CatalogPageSpec) -> bytes:
    """Pack a catalog page into a FloorIR FlatBuffer.

    Each cell becomes one ``Region`` (with its shape outline) plus
    one op produced by the column's ``op_factory``. Regions are
    named ``"cell.{col}.{row}"`` so factories can reference them.
    """
    n_cols = len(spec.columns)
    n_rows = len(spec.rows)
    width_px, height_px = page_pixel_dimensions(n_cols, n_rows)

    # FloorIR's width_tiles / height_tiles set the canvas extent.
    # Round up so the bbox covers every cell.
    width_tiles = _ceil_div(width_px, CELL)
    height_tiles = _ceil_div(height_px, CELL)

    regions: list[RegionT] = []
    ops: list[OpEntryT] = []

    for col_idx, column in enumerate(spec.columns):
        for row_idx, row_shape in enumerate(spec.rows):
            shape_builder = SHAPE_BUILDERS.get(row_shape)
            if shape_builder is None:
                raise ValueError(f"unknown row shape: {row_shape!r}")
            x0, y0, x1, y1 = cell_bbox(col_idx, row_idx)
            outline = shape_builder(x0, y0, x1, y1)
            region_id = f"cell.{col_idx}.{row_idx}"

            region = RegionT()
            region.id = region_id
            region.outline = outline
            region.parentId = ""
            region.cuts = []
            region.shapeTag = row_shape
            regions.append(region)

            op_entry = column.op_factory(
                region_id, spec.seed, col_idx, row_idx,
            )
            ops.append(op_entry)

    fir = FloorIRT()
    fir.major = _SCHEMA_MAJOR
    fir.minor = _SCHEMA_MINOR
    fir.widthTiles = width_tiles
    fir.heightTiles = height_tiles
    fir.cell = CELL
    fir.padding = PADDING
    fir.baseSeed = spec.seed
    fir.regions = regions
    fir.ops = ops

    fbb = flatbuffers.Builder(2048)
    fbb.Finish(fir.Pack(fbb), _FILE_IDENTIFIER)
    return bytes(fbb.Output())


__all__ = [
    "CELL_PX", "CELL_TILES", "GUTTER_PX",
    "LEFT_MARGIN_PX", "TOP_MARGIN_PX",
    "RIGHT_MARGIN_PX", "BOTTOM_MARGIN_PX",
    "MAX_COLS",
    "ColumnSpec", "CatalogPageSpec", "DEFAULT_ROWS",
    "build_catalog_buffer",
    "cell_bbox", "page_pixel_dimensions",
]
