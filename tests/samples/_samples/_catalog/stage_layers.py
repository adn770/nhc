"""Stage-layer catalog pages — per-cell ShadowOp / HatchOp /
group-opacity overlap demonstrations across rect / octagon /
circle shape rows.

- ``shadow-envelopes`` — same cell with / without shadow, varying
  offset + opacity per column.
- ``hatching-density`` — varying ``extent_tiles`` per column to
  show the hatch envelope wrap behaviour at different sizes.
- ``group-opacity-overlap`` — twin sub-regions inside each cell so
  hatch envelopes overlap; pins the load-bearing Phase 5.10
  begin_group/end_group composite (overlap pixels stay at the
  group's opacity, not the per-element double-darkened value).
"""

from __future__ import annotations

from nhc.rendering.ir._fb.HatchKind import HatchKind
from nhc.rendering.ir._fb.HatchOp import HatchOpT
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.PaintOp import PaintOpT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.Vec2 import Vec2T
from nhc.rendering.emit.materials import material_plain

from nhc.rendering._svg_helpers import CELL

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    cell_content_bbox, derive_cell_seed,
    hatch_factory, make_tile_coord, plain_factory,
    register_catalog_page, shadow_factory,
)


# ── Shadow envelopes ────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="shadow-envelopes",
    category="synthetic/stage-layers",
    description=(
        "ShadowOp envelopes at varying offset / opacity over a "
        "Plain base, swept across rect / octagon / circle shape "
        "rows. Surfaces shadow rendering on chamfer corners + "
        "polygonised circle edges."
    ),
    columns=[
        ColumnSpec("None", plain_factory()),
        ColumnSpec("Default (3px, 0.08)", shadow_factory(
            dx=3.0, dy=3.0, opacity=0.08,
        )),
        ColumnSpec("Large (6px, 0.15)", shadow_factory(
            dx=6.0, dy=6.0, opacity=0.15,
        )),
        ColumnSpec("Dark (3px, 0.30)", shadow_factory(
            dx=3.0, dy=3.0, opacity=0.30,
        )),
    ],
    seed=7,
    params={"axis": "shadow-envelopes"},
))


# ── Hatching density ────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="hatching-density",
    category="synthetic/stage-layers",
    description=(
        "HatchOp envelopes at varying extent_tiles per column over "
        "a Plain base, swept across rect / octagon / circle shape "
        "rows. Pins the hatch-line wrap geometry on different "
        "outline curvatures."
    ),
    columns=[
        ColumnSpec("Narrow (1)", hatch_factory(extent_tiles=1.0)),
        ColumnSpec("Default (2)", hatch_factory(extent_tiles=2.0)),
        ColumnSpec("Wide (3)", hatch_factory(extent_tiles=3.0)),
        ColumnSpec("Very Wide (4)", hatch_factory(extent_tiles=4.0)),
    ],
    seed=7,
    params={"axis": "hatching-density"},
))


# ── Group-opacity overlap (twin sub-regions per cell) ──────────


def _v2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def _rect_outline(x0: float, y0: float, x1: float, y1: float):
    from nhc.rendering.ir._fb.Outline import OutlineT
    o = OutlineT()
    o.vertices = [
        _v2(x0, y0), _v2(x1, y0),
        _v2(x1, y1), _v2(x0, y1),
    ]
    o.closed = True
    o.descriptorKind = OutlineKind.Polygon
    o.rings = []
    return o


def _wrap(entry_op_type: int, op: object) -> OpEntryT:
    e = OpEntryT()
    e.opType = entry_op_type
    e.op = op
    return e


def _make_paint(region_id: str) -> OpEntryT:
    p = PaintOpT()
    p.regionRef = region_id
    p.subtractRegionRefs = []
    p.material = material_plain(seed=0)
    return _wrap(Op.PaintOp, p)


def _make_hatch(
    region_id: str, extent_tiles: float, seed: int,
    *, sub_bbox: tuple[float, float, float, float],
) -> OpEntryT:
    """Build a HatchOp for a sub-region, populating tiles[] from
    the sub-region's pixel bbox.
    """
    sx0, sy0, sx1, sy1 = sub_bbox
    tx0 = int(sx0 // CELL)
    ty0 = int(sy0 // CELL)
    tx1 = int((sx1 + CELL - 1) // CELL)
    ty1 = int((sy1 + CELL - 1) // CELL)
    tiles = [
        make_tile_coord(tx, ty)
        for ty in range(ty0, ty1)
        for tx in range(tx0, tx1)
    ]
    h = HatchOpT()
    h.kind = HatchKind.Room
    h.regionRef = region_id
    h.subtractRegionRefs = []
    h.tiles = tiles
    h.isOuter = [True] * len(tiles)
    h.extentTiles = extent_tiles
    h.seed = seed
    h.hatchUnderlayColor = ""
    return _wrap(Op.HatchOp, h)


def _twin_overlap_factory(*, extent_tiles: float, gap_frac: float):
    """Op factory that splits the cell into two sub-regions side-by-side.

    The cell's main region is unused (kept for grid alignment + label
    anchoring). Two sub-regions ``cell.<col>.<row>.left`` and
    ``cell.<col>.<row>.right`` are added with a ``gap_frac``-fraction
    gutter between them; both carry HatchOps at the given extent so
    their hatch envelopes overlap in the centre.

    Returns ``(extra_regions, ops)`` per the multi-region cell
    contract documented in ``_builder.py``.
    """
    def factory(_region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, int(extent_tiles * 100),
        )
        x0, y0, x1, y1 = cell_content_bbox(col_idx, row_idx)
        cw = x1 - x0
        gap = cw * gap_frac
        mid_x = (x0 + x1) / 2.0
        # Left sub-region
        left_x1 = mid_x - gap / 2.0
        left = RegionT()
        left.id = f"cell.{col_idx}.{row_idx}.left"
        left.outline = _rect_outline(x0, y0, left_x1, y1)
        left.parentId = ""
        left.cuts = []
        left.shapeTag = "twin-left"
        # Right sub-region
        right_x0 = mid_x + gap / 2.0
        right = RegionT()
        right.id = f"cell.{col_idx}.{row_idx}.right"
        right.outline = _rect_outline(right_x0, y0, x1, y1)
        right.parentId = ""
        right.cuts = []
        right.shapeTag = "twin-right"

        ops = [
            _make_paint(left.id),
            _make_paint(right.id),
            _make_hatch(
                left.id, extent_tiles, seed,
                sub_bbox=(x0, y0, left_x1, y1),
            ),
            _make_hatch(
                right.id, extent_tiles, seed ^ 0x9E37_79B9,
                sub_bbox=(right_x0, y0, x1, y1),
            ),
        ]
        return ([left, right], ops)
    return factory


register_catalog_page(CatalogPageSpec(
    name="group-opacity-overlap",
    category="synthetic/stage-layers",
    description=(
        "Twin sub-regions per cell with hatch envelopes overlapping "
        "in the central gutter — pins the Phase 5.10 group-opacity "
        "composite. Overlap pixels MUST land at the group's opacity "
        "(≈ 128/255 for 0.5) rather than the pre-Phase-5.10 "
        "double-darkened (≈ 64/255) per-element multiply. Each cell "
        "varies the gap fraction + hatch extent so the overlap zone "
        "scales across columns."
    ),
    columns=[
        ColumnSpec(
            "Wide gap, narrow hatch",
            _twin_overlap_factory(extent_tiles=1.5, gap_frac=0.15),
        ),
        ColumnSpec(
            "Default",
            _twin_overlap_factory(extent_tiles=2.0, gap_frac=0.10),
        ),
        ColumnSpec(
            "Narrow gap, wide hatch",
            _twin_overlap_factory(extent_tiles=3.0, gap_frac=0.05),
        ),
        ColumnSpec(
            "Touching, wide hatch",
            _twin_overlap_factory(extent_tiles=3.0, gap_frac=0.0),
        ),
    ],
    seed=7,
    params={"axis": "group-opacity-overlap"},
))


__all__ = []
