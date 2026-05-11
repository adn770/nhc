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
from nhc.rendering.emit.materials import (
    material_cave, material_earth, material_liquid, material_plain,
    material_special, material_stone, material_wood,
    wall_material_adobe, wall_material_drystone,
    wall_material_drystone_low_wall, wall_material_fortification,
    wall_material_hedge, wall_material_iron, wall_material_masonry,
    wall_material_palisade, wall_material_partition,
    wall_material_plain_stroke, wall_material_post_and_rail,
    wall_material_wattle_and_daub,
)
from nhc.rendering.ir._fb.Anchor import AnchorT
from nhc.rendering.ir._fb.Cut import CutT
from nhc.rendering.ir._fb.CutStyle import CutStyle
from nhc.rendering.ir._fb.FixtureOp import FixtureOpT
from nhc.rendering.ir._fb.FloorIR import FloorIRT
from nhc.rendering.ir._fb.HatchKind import HatchKind
from nhc.rendering.ir._fb.HatchOp import HatchOpT
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.PaintOp import PaintOpT
from nhc.rendering.ir._fb.PathOp import PathOpT
from nhc.rendering.ir._fb.Region import RegionT
from nhc.rendering.ir._fb.RoofOp import RoofOpT
from nhc.rendering.ir._fb.ShadowKind import ShadowKind
from nhc.rendering.ir._fb.ShadowOp import ShadowOpT
from nhc.rendering.ir._fb.StampOp import StampOpT
from nhc.rendering.ir._fb.StrokeOp import StrokeOpT
from nhc.rendering.ir._fb.TileCoord import TileCoordT
from nhc.rendering.ir._fb.Vec2 import Vec2T
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
            -> OpEntryT | list[OpEntryT]`` callable that returns
            one or more ops (PaintOp / StrokeOp / FixtureOp / etc.)
            for the cell at this column. The page builder anchors
            ops to the cell's region by passing ``region_id`` for
            ``op.region_ref``. Multi-op cells (e.g. walls = base
            paint + wall stroke) return a list; single-op cells
            return one ``OpEntryT``.
    """

    label: str
    op_factory: Callable[
        [str, int, int, int], "OpEntryT | list[OpEntryT]",
    ]


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
        rows: Row labels — one entry per row. Default
            ``("rect", "octagon", "circle")`` doubles as the
            cell shape; pages with a non-shape row axis (e.g.
            corner styles) set ``cell_shape`` to override the
            per-row shape lookup.
        seed: Page seed — propagated to every op factory's
            ``page_seed`` argument.
        cell_shape: Optional per-page shape override. ``None``
            (default) ⇒ the row label IS the shape key
            (``rect``/``octagon``/``circle``). When set, every
            cell uses this shape and the row labels become free
            text annotations.
    """

    name: str
    category: str
    description: str
    columns: list[ColumnSpec]
    rows: tuple[str, ...] = DEFAULT_ROWS
    seed: int = 7
    # Static recipe echoed into the .json sidecar.
    params: dict[str, Any] = field(default_factory=dict)
    cell_shape: str | None = None
    # Optional inset applied to the cell's shape polygon (px on
    # every side). The cell GRID layout (cell_bbox) stays fixed,
    # only the shape outline shrinks. Pages whose painters can
    # overhang the cell rect (e.g. fortification corners) bump
    # this so adjacent cells' overhangs don't collide in the
    # 16-px gutter.
    cell_inset_px: int = 0


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

    The LAYOUT bbox — independent of any per-page inset. Labels
    + grid-positioning callers use this so they sit relative to
    the visible cell grid, not the (possibly insetted) wall
    polygon. Coordinates are in the page's content space (PADDING
    is added by the renderer's outer transform).
    """
    x0 = LEFT_MARGIN_PX + col * (CELL_PX + GUTTER_PX)
    y0 = TOP_MARGIN_PX + row * (CELL_PX + GUTTER_PX)
    return x0, y0, x0 + CELL_PX, y0 + CELL_PX


# Per-page cell inset, set by ``_build_page`` before walking the
# cell grid and reset back to 0 afterwards. ``cell_content_bbox``
# reads this so painters that overhang the cell rect (e.g.
# fortification corners) can opt their page into a smaller inner
# bbox without threading a spec through every closure.
_active_cell_inset: int = 0


def cell_content_bbox(col: int, row: int) -> tuple[int, int, int, int]:
    """Pixel bbox of the cell's content area at ``(col, row)``.

    Applies the page's ``cell_inset_px`` so the wall polygon /
    cuts / fill stay inside the cell rect. Defaults to
    ``cell_bbox`` when no inset is active.
    """
    x0, y0, x1, y1 = cell_bbox(col, row)
    inset = _active_cell_inset
    return x0 + inset, y0 + inset, x1 - inset, y1 - inset


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

    global _active_cell_inset
    prev_inset = _active_cell_inset
    _active_cell_inset = spec.cell_inset_px
    try:
        for col_idx, column in enumerate(spec.columns):
            for row_idx, row_label in enumerate(spec.rows):
                shape_key = spec.cell_shape if spec.cell_shape else row_label
                shape_builder = SHAPE_BUILDERS.get(shape_key)
                if shape_builder is None:
                    raise ValueError(
                        f"unknown shape {shape_key!r} "
                        f"(row label {row_label!r}, cell_shape {spec.cell_shape!r})"
                    )
                x0, y0, x1, y1 = cell_content_bbox(col_idx, row_idx)
                outline = shape_builder(x0, y0, x1, y1)
                region_id = f"cell.{col_idx}.{row_idx}"

                region = RegionT()
                region.id = region_id
                region.outline = outline
                region.parentId = ""
                region.cuts = []
                region.shapeTag = row_label
                regions.append(region)

                op_result = column.op_factory(
                    region_id, spec.seed, col_idx, row_idx,
                )
                # Multi-region cells return ``(extra_regions, ops)``;
                # the cell's main region is already in ``regions``.
                # Single-op or list-of-op returns just contribute ops.
                if (
                    isinstance(op_result, tuple) and len(op_result) == 2
                    and isinstance(op_result[0], list)
                ):
                    extra_regions, extra_ops = op_result
                    regions.extend(extra_regions)
                    ops.extend(extra_ops)
                elif isinstance(op_result, list):
                    ops.extend(op_result)
                else:
                    ops.append(op_result)
    finally:
        _active_cell_inset = prev_inset

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


# ── Paint-op factory helpers ─────────────────────────────────────


_SEED_MIX_COL = 0x9E37_79B9
_SEED_MIX_ROW = 0xBF58_476D
_SEED_MIX_AXIS = (0x94D0_49BB, 0x4F1B_BCDC, 0x2545_F491, 0x1B87_3593)


def derive_cell_seed(
    page_seed: int, col_idx: int, row_idx: int,
    *axis_keys: int,
) -> int:
    """Mix the page seed with the cell coords + arbitrary axis keys.

    Used by paint-op factories to give each cell its own RNG stream
    while keeping the page output deterministic for the page seed.
    Axis keys (style / sub_pattern / tone / etc.) make sub-patterns
    that share (col, row) but differ in axis diverge in the output.
    """
    seed = page_seed
    seed ^= (col_idx * _SEED_MIX_COL) & 0xFFFF_FFFF_FFFF_FFFF
    seed ^= (row_idx * _SEED_MIX_ROW) & 0xFFFF_FFFF_FFFF_FFFF
    for i, key in enumerate(axis_keys):
        mix = _SEED_MIX_AXIS[i % len(_SEED_MIX_AXIS)]
        seed ^= (key * mix) & 0xFFFF_FFFF_FFFF_FFFF
    return seed & 0xFFFF_FFFF_FFFF_FFFF


def _wrap_paint(paint_op: PaintOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.PaintOp
    entry.op = paint_op
    return entry


def _make_paint_op(region_id: str, material) -> OpEntryT:
    op = PaintOpT()
    op.regionRef = region_id
    op.subtractRegionRefs = []
    op.material = material
    return _wrap_paint(op)


def stone_factory(*, style: int, sub_pattern: int = 0, tone: int = 0):
    """Column op_factory emitting Stone PaintOps with the given axes."""
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, style, sub_pattern, tone,
        )
        return _make_paint_op(
            region_id,
            material_stone(
                style=style, sub_pattern=sub_pattern, tone=tone, seed=seed,
            ),
        )
    return factory


def wood_factory(*, species: int, layout: int = 0, tone: int = 1):
    """Column op_factory emitting Wood PaintOps. Default tone = Medium."""
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, species, layout, tone,
        )
        return _make_paint_op(
            region_id,
            material_wood(
                species=species, layout=layout, tone=tone, seed=seed,
            ),
        )
    return factory


def earth_factory(*, style: int):
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(page_seed, col_idx, row_idx, style)
        return _make_paint_op(
            region_id, material_earth(style=style, seed=seed),
        )
    return factory


def liquid_factory(*, style: int):
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(page_seed, col_idx, row_idx, style)
        return _make_paint_op(
            region_id, material_liquid(style=style, seed=seed),
        )
    return factory


def special_factory(*, style: int):
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(page_seed, col_idx, row_idx, style)
        return _make_paint_op(
            region_id, material_special(style=style, seed=seed),
        )
    return factory


def cave_factory(*, style: int):
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(page_seed, col_idx, row_idx, style)
        return _make_paint_op(
            region_id, material_cave(style=style, seed=seed),
        )
    return factory


def plain_factory():
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(page_seed, col_idx, row_idx)
        return _make_paint_op(region_id, material_plain(seed=seed))
    return factory


# ── StrokeOp factory helpers ────────────────────────────────────


def _wrap_stroke(stroke_op: StrokeOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.StrokeOp
    entry.op = stroke_op
    return entry


def _make_stroke_op(
    region_id: str, wall_material, *, cuts: list[CutT] | None = None,
) -> OpEntryT:
    op = StrokeOpT()
    op.regionRef = region_id
    op.outline = None
    op.wallMaterial = wall_material
    op.cuts = list(cuts or [])
    return _wrap_stroke(op)


def _v2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def make_cut(
    start: tuple[float, float], end: tuple[float, float],
    *, style: int = CutStyle.WoodGate,
) -> CutT:
    """Construct a single ``Cut`` from pixel-space endpoints."""
    cut = CutT()
    cut.start = _v2(*start)
    cut.end = _v2(*end)
    cut.style = style
    return cut


# Map treatment → wall_material factory. Used by ``wall_factory``
# below so callers pass a treatment name without importing the
# materials module.
_WALL_TREATMENT_BUILDERS = {
    "PlainStroke": wall_material_plain_stroke,
    "Masonry": wall_material_masonry,
    "Partition": wall_material_partition,
    "Palisade": wall_material_palisade,
    "Fortification": wall_material_fortification,
    "Drystone": wall_material_drystone,
    "Adobe": wall_material_adobe,
    "WattleAndDaub": wall_material_wattle_and_daub,
    "Iron": wall_material_iron,
    "PostAndRail": wall_material_post_and_rail,
    "Hedge": wall_material_hedge,
    "DrystoneLowWall": wall_material_drystone_low_wall,
}


def wall_factory(
    *,
    treatment: str,
    family=None,
    style=None,
    corner_style=None,
    base: "Callable[[], Any]" = None,
    cuts: "Callable[[int], list[CutT]] | None" = None,
):
    """Column op_factory emitting a base PaintOp + wall StrokeOp.

    - ``treatment`` picks the WallMaterial factory (PlainStroke,
      Masonry, Partition, Palisade, Fortification).
    - ``family`` / ``style`` / ``corner_style`` override the
      WallMaterial factory's defaults; pass ``None`` to keep them.
    - ``base``: ``() -> Material`` for the cell's interior fill.
      Defaults to Plain (white) so the wall stroke reads cleanly
      on a neutral substrate.
    - ``cuts``: ``(page_seed) -> list[Cut]`` for gates / doors
      cutting the wall. Default: no cuts.
    """
    builder_fn = _WALL_TREATMENT_BUILDERS.get(treatment)
    if builder_fn is None:
        raise ValueError(f"unknown wall treatment: {treatment!r}")

    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx,
            hash(treatment) & 0xFFFF_FFFF,
        )
        # Resolve WallMaterial using only the explicit overrides
        # — the materials.py factory carries family / style /
        # corner_style defaults appropriate for each treatment.
        kwargs = {"seed": seed}
        if family is not None:
            kwargs["family"] = family
        if style is not None:
            kwargs["style"] = style
        if corner_style is not None:
            kwargs["corner_style"] = corner_style
        wall_mat = builder_fn(**kwargs)

        if base is not None:
            base_material = base()
            if hasattr(base_material, "seed") and base_material.seed == 0:
                base_material.seed = seed
        else:
            base_material = material_plain(seed=seed)

        cut_list: list[CutT] = []
        if cuts is not None:
            cut_list = cuts(page_seed)

        return [
            _make_paint_op(region_id, base_material),
            _make_stroke_op(region_id, wall_mat, cuts=cut_list),
        ]

    return factory


# ── Roof / Fixture / Stamp / Path factory helpers ───────────────


def _wrap_roof(op: RoofOpT) -> OpEntryT:
    e = OpEntryT()
    e.opType = Op.RoofOp
    e.op = op
    return e


def _wrap_fixture(op: FixtureOpT) -> OpEntryT:
    e = OpEntryT()
    e.opType = Op.FixtureOp
    e.op = op
    return e


def _wrap_stamp(op: StampOpT) -> OpEntryT:
    e = OpEntryT()
    e.opType = Op.StampOp
    e.op = op
    return e


def _wrap_path(op: PathOpT) -> OpEntryT:
    e = OpEntryT()
    e.opType = Op.PathOp
    e.op = op
    return e


def make_anchor(
    *,
    x: int, y: int,
    variant: int = 0, orientation: int = 0,
    scale: int = 0, group_id: int = 0,
) -> AnchorT:
    a = AnchorT()
    a.x = x
    a.y = y
    a.variant = variant
    a.orientation = orientation
    a.scale = scale
    a.pad0 = 0
    a.groupId = group_id
    return a


def make_tile_coord(x: int, y: int) -> TileCoordT:
    t = TileCoordT()
    t.x = x
    t.y = y
    return t


def cell_tile_bounds(col_idx: int, row_idx: int) -> tuple[int, int, int, int]:
    """Tile-space bounds (tx0, ty0, tx1, ty1) of the cell at
    ``(col, row)``. Inclusive lower bound, exclusive upper bound.
    """
    x0, y0, x1, y1 = cell_bbox(col_idx, row_idx)
    return (
        x0 // CELL,
        y0 // CELL,
        (x1 + CELL - 1) // CELL,
        (y1 + CELL - 1) // CELL,
    )


def cell_center_tile(col_idx: int, row_idx: int) -> tuple[int, int]:
    """Tile-space (x, y) at the centre of the cell at ``(col, row)``."""
    tx0, ty0, tx1, ty1 = cell_tile_bounds(col_idx, row_idx)
    return ((tx0 + tx1) // 2, (ty0 + ty1) // 2)


def roof_factory(
    *, style: int, tone: int = 0, sub_pattern: int = 0,
):
    """Column op_factory emitting a base PaintOp (Plain) + RoofOp.

    The RoofOp consumes the cell's region outline; pairing it with
    a Plain base fill gives a clear roof silhouette. ``sub_pattern``
    selects an optional ``RoofTilePattern`` overlay (0 = Plain, the
    no-op default).
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, style, tone, sub_pattern,
        )
        op = RoofOpT()
        op.regionRef = region_id
        op.style = style
        op.tone = tone
        op.tint = ""
        op.seed = seed
        op.subPattern = sub_pattern
        return [
            _make_paint_op(region_id, material_plain(seed=seed)),
            _wrap_roof(op),
        ]
    return factory


def fixture_factory(
    *,
    kind: int,
    variant: int = 0,
    orientation: int = 0,
    scale: int = 0,
    base: "Callable[[], Any] | None" = None,
    tile_offset: tuple[int, int] = (0, 0),
):
    """Column op_factory emitting a base PaintOp + FixtureOp with
    one anchor at the cell centre.

    ``tile_offset = (dx, dy)`` shifts the anchor by ``(dx, dy)``
    tiles from ``cell_center_tile``. Most fixture primitives read
    ``Anchor.x, y`` as the *top-left* tile of a multi-tile
    footprint (2×2 fountain, 3×3 fountain, Cross fountain), so a
    centred placement needs an offset of ``(-N//2, -N//2)`` where
    ``N`` is the footprint side. Single-tile fixtures stay at the
    default ``(0, 0)``.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, kind, variant,
        )
        cx, cy = cell_center_tile(col_idx, row_idx)
        anchor = make_anchor(
            x=cx + tile_offset[0], y=cy + tile_offset[1],
            variant=variant, orientation=orientation, scale=scale,
        )
        fop = FixtureOpT()
        fop.regionRef = region_id
        fop.kind = kind
        fop.anchors = [anchor]
        fop.seed = seed

        base_material = (
            base() if base is not None else material_plain(seed=seed)
        )
        return [
            _make_paint_op(region_id, base_material),
            _wrap_fixture(fop),
        ]
    return factory


def small_fixture_factory(
    *,
    kind: int,
    variant: int = 0,
    orientation: int = 0,
    scale_byte: int = 0,
    zoom: float = 3.0,
    base: "Callable[[], Any] | None" = None,
):
    """Column op_factory rendering the SAME single-tile fixture
    twice in one cell:

    1. A natural-size copy anchored at the cell's top-left tile
       — exactly the pixel footprint the primitive draws in
       production.
    2. A zoomed copy anchored in the cell's centre, painted via
       ``FixtureOp.scale`` (catalog-only forward-compat field).
       Default zoom 3× lifts a 32-pixel primitive to 96 pixels —
       roughly the 3×3 remaining area of a 4-tile cell after the
       top-left preview tile.

    Suitable for fixtures whose drawn footprint stays within one
    tile (Chest, Crate, Pillar, etc.). Multi-tile primitives
    (Fountain, Well, Bed) should keep using ``fixture_factory``
    with a ``tile_offset`` instead.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, kind, variant,
        )
        tx0, ty0, _, _ = cell_tile_bounds(col_idx, row_idx)
        small_anchor = make_anchor(
            x=tx0, y=ty0,
            variant=variant, orientation=orientation, scale=scale_byte,
        )
        cx, cy = cell_center_tile(col_idx, row_idx)
        zoom_anchor = make_anchor(
            x=cx, y=cy,
            variant=variant, orientation=orientation, scale=scale_byte,
        )
        small_op = FixtureOpT()
        small_op.regionRef = region_id
        small_op.kind = kind
        small_op.anchors = [small_anchor]
        small_op.seed = seed
        zoom_op = FixtureOpT()
        zoom_op.regionRef = region_id
        zoom_op.kind = kind
        zoom_op.anchors = [zoom_anchor]
        zoom_op.seed = seed
        zoom_op.scale = zoom

        base_material = (
            base() if base is not None else material_plain(seed=seed)
        )
        return [
            _make_paint_op(region_id, base_material),
            _wrap_fixture(small_op),
            _wrap_fixture(zoom_op),
        ]
    return factory


def stamp_factory(
    *,
    decorator_mask: int,
    density: int = 128,
    base: "Callable[[], Any] | None" = None,
):
    """Column op_factory emitting a base PaintOp + StampOp.

    ``decorator_mask`` is a bitmask of decorator bits (1 << 0 =
    GridLines, 1 << 1 = Cracks, etc. — matching the Rust ``bit::``
    constants in ``transform/png/stamp_op.rs``).
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, decorator_mask, density,
        )
        sop = StampOpT()
        sop.regionRef = region_id
        sop.subtractRegionRefs = []
        sop.decoratorMask = decorator_mask
        sop.density = density
        sop.seed = seed

        base_material = (
            base() if base is not None else material_plain(seed=seed)
        )
        return [
            _make_paint_op(region_id, base_material),
            _wrap_stamp(sop),
        ]
    return factory


def path_factory(
    *,
    style: int,
    base: "Callable[[], Any] | None" = None,
):
    """Column op_factory emitting a base PaintOp + PathOp.

    The path tiles are picked from the cell's middle row (a
    horizontal stripe through the cell centre) so cart-tracks /
    ore-vein renders as a clear horizontal path inside the cell.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx, style,
        )
        tx0, ty0, tx1, ty1 = cell_tile_bounds(col_idx, row_idx)
        mid_y = (ty0 + ty1) // 2
        # Inset 1 tile from each side so the path doesn't sit on
        # the cell edge — visually clearer.
        tiles = [
            make_tile_coord(tx, mid_y) for tx in range(tx0 + 1, tx1 - 1)
        ]
        pop = PathOpT()
        pop.regionRef = region_id
        pop.tiles = tiles
        pop.style = style
        pop.seed = seed

        base_material = (
            base() if base is not None else material_plain(seed=seed)
        )
        return [
            _make_paint_op(region_id, base_material),
            _wrap_path(pop),
        ]
    return factory


# ── Shadow / Hatch factory helpers ──────────────────────────────


def _wrap_shadow(op: ShadowOpT) -> OpEntryT:
    e = OpEntryT()
    e.opType = Op.ShadowOp
    e.op = op
    return e


def _wrap_hatch(op: HatchOpT) -> OpEntryT:
    e = OpEntryT()
    e.opType = Op.HatchOp
    e.op = op
    return e


def shadow_factory(
    *,
    dx: float = 3.0, dy: float = 3.0, opacity: float = 0.08,
    base: "Callable[[], Any] | None" = None,
):
    """Column op_factory emitting a base PaintOp + ShadowOp.

    The ShadowOp anchors to the cell region; the painter offsets
    a translucent silhouette behind the cell to read as a drop
    shadow.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(page_seed, col_idx, row_idx)
        sop = ShadowOpT()
        sop.kind = ShadowKind.Room
        sop.regionRef = region_id
        sop.tiles = []
        sop.dx = dx
        sop.dy = dy
        sop.opacity = opacity

        base_material = (
            base() if base is not None else material_plain(seed=seed)
        )
        # ShadowOp first so it composites BEHIND the floor fill.
        return [
            _wrap_shadow(sop),
            _make_paint_op(region_id, base_material),
        ]
    return factory


def hatch_factory(
    *,
    extent_tiles: float = 2.0,
    is_outer: bool = True,
    base: "Callable[[], Any] | None" = None,
):
    """Column op_factory emitting a base PaintOp + HatchOp.

    Hatching draws around the region's outer perimeter (when
    ``is_outer=True``) at the given extent. The painter wraps the
    hatch lines in a group-opacity envelope so adjacent hatched
    regions composite correctly without double-darkening.

    The Rust hatch painter requires ``tiles[]`` to be populated
    even for Room kind (it treats them as the region's interior
    tile cluster); the catalog's per-cell tile list is the cell's
    full 4×4 tile block.
    """
    def factory(region_id, page_seed, col_idx, row_idx):
        seed = derive_cell_seed(
            page_seed, col_idx, row_idx,
            int(extent_tiles * 100),
        )
        tx0, ty0, tx1, ty1 = cell_tile_bounds(col_idx, row_idx)
        tiles = [
            make_tile_coord(tx, ty)
            for ty in range(ty0, ty1)
            for tx in range(tx0, tx1)
        ]
        hop = HatchOpT()
        hop.kind = HatchKind.Room
        hop.regionRef = region_id
        hop.subtractRegionRefs = []
        hop.tiles = tiles
        hop.isOuter = [is_outer] * len(tiles)
        hop.extentTiles = extent_tiles
        hop.seed = seed
        hop.hatchUnderlayColor = ""

        base_material = (
            base() if base is not None else material_plain(seed=seed)
        )
        return [
            _make_paint_op(region_id, base_material),
            _wrap_hatch(hop),
        ]
    return factory


# ── Sample-spec registration helper ──────────────────────────────


def register_catalog_page(spec: "CatalogPageSpec") -> None:
    """Wrap a CatalogPageSpec in a SampleSpec and append to CATALOG.

    The build callable returns a ``BuildResult`` carrying the IR
    bytes plus an ``svg_post_process`` hook that injects the page's
    row / column labels into the SVG. Catalog pages own their seed
    via ``spec.seed`` (the CLI's global seed list is ignored).
    """
    # Local imports to break circulars: _core ↔ _catalog.
    from .._core import BuildResult, CATALOG, SampleSpec
    from ._labels import inject_catalog_labels

    def build(_seed: int) -> BuildResult:
        buf = build_catalog_buffer(spec)
        return BuildResult(
            buf=buf,
            svg_post_process=lambda svg: inject_catalog_labels(svg, spec),
        )

    CATALOG.append(SampleSpec(
        name=spec.name,
        category=spec.category,
        description=spec.description,
        params={**spec.params, "page": spec.name, "seed": spec.seed},
        build=build,
        seeds=(spec.seed,),
    ))


__all__ = [
    "CELL_PX", "CELL_TILES", "GUTTER_PX",
    "LEFT_MARGIN_PX", "TOP_MARGIN_PX",
    "RIGHT_MARGIN_PX", "BOTTOM_MARGIN_PX",
    "MAX_COLS",
    "ColumnSpec", "CatalogPageSpec", "DEFAULT_ROWS",
    "build_catalog_buffer",
    "cell_bbox", "cell_content_bbox", "page_pixel_dimensions",
    "derive_cell_seed", "small_fixture_factory",
    "stone_factory", "wood_factory",
    "earth_factory", "liquid_factory", "special_factory",
    "cave_factory", "plain_factory",
    "wall_factory", "make_cut",
    "roof_factory", "fixture_factory",
    "stamp_factory", "path_factory",
    "shadow_factory", "hatch_factory",
    "make_anchor", "make_tile_coord",
    "cell_tile_bounds", "cell_center_tile",
    "register_catalog_page",
]
