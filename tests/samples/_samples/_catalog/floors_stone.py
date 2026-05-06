"""Stone floor catalog pages.

One catalog page per Stone style group. Cobblestone (4 sub-patterns),
Brick (3 bonds), Ashlar (2 sub-patterns) get one page each that
sweeps every sub-pattern across rect / octagon / circle shape rows.
The remaining six single-layout styles (Flagstone, OpusRomano,
FieldStone, Pinwheel, Hopscotch, CrazyPaving) are split across one
or two "singles" pages.
"""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    STONE_COBBLESTONE,
    STONE_COBBLE_HERRINGBONE,
    STONE_COBBLE_STACK,
    STONE_COBBLE_RUBBLE,
    STONE_COBBLE_MOSAIC,
    material_stone,
)
from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.OpEntry import OpEntryT
from nhc.rendering.ir._fb.PaintOp import PaintOpT

from .._core import BuildResult, CATALOG, SampleSpec
from ._builder import (
    CatalogPageSpec, ColumnSpec, build_catalog_buffer,
)
from ._labels import inject_catalog_labels


# ── PaintOp factory helpers ─────────────────────────────────────


def _wrap_paint(paint_op: PaintOpT) -> OpEntryT:
    entry = OpEntryT()
    entry.opType = Op.PaintOp
    entry.op = paint_op
    return entry


def _stone_paint_op_factory(*, style: int, sub_pattern: int):
    """Return a column op_factory that emits a Stone paint op
    anchored to the cell's region.

    The page seed is XOR'd with ``(col, row, style, sub_pattern)``
    so seed-aware sub-patterns (Cobblestone Rubble / Mosaic, etc.)
    diverge across cells visibly without sharing identical RNG
    streams. Deterministic for a given (page_seed, col, row).
    """
    def factory(region_id: str, page_seed: int, col_idx: int, row_idx: int) -> OpEntryT:
        cell_seed = (
            page_seed
            ^ (col_idx * 0x9E37_79B9)
            ^ (row_idx * 0xBF58_476D)
            ^ (style * 0x94D0_49BB)
            ^ (sub_pattern * 0x4F1B_BCDC)
        ) & 0xFFFF_FFFF_FFFF_FFFF
        material = material_stone(
            style=style, sub_pattern=sub_pattern, seed=cell_seed,
        )
        op = PaintOpT()
        op.regionRef = region_id
        op.subtractRegionRefs = []
        op.material = material
        return _wrap_paint(op)
    return factory


# ── Sample-spec factory ─────────────────────────────────────────


def _register_catalog_page(spec: CatalogPageSpec) -> None:
    """Wrap a CatalogPageSpec in a SampleSpec and append to CATALOG.

    The build callable returns a ``BuildResult`` carrying the IR
    bytes plus an ``svg_post_process`` hook that injects the page's
    row / column labels into the SVG (PNG stays clean).
    """
    def build(_seed: int) -> BuildResult:
        # Catalog pages own their seed via ``spec.seed`` — the CLI's
        # global seed list is ignored (per-spec ``seeds=(spec.seed,)``
        # below pins it to one render).
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


# ── Cobblestone page (4 sub-patterns × 3 shapes) ────────────────


_register_catalog_page(CatalogPageSpec(
    name="cobblestone",
    category="synthetic/floors/stone",
    description=(
        "Stone Cobblestone — four sub-pattern layouts (Herringbone, "
        "Stack, Rubble, Mosaic) swept across rect / octagon / circle "
        "shape rows. Surfaces per-shape bleed at corners + curves."
    ),
    columns=[
        ColumnSpec(
            label="Herringbone",
            op_factory=_stone_paint_op_factory(
                style=STONE_COBBLESTONE,
                sub_pattern=STONE_COBBLE_HERRINGBONE,
            ),
        ),
        ColumnSpec(
            label="Stack",
            op_factory=_stone_paint_op_factory(
                style=STONE_COBBLESTONE,
                sub_pattern=STONE_COBBLE_STACK,
            ),
        ),
        ColumnSpec(
            label="Rubble",
            op_factory=_stone_paint_op_factory(
                style=STONE_COBBLESTONE,
                sub_pattern=STONE_COBBLE_RUBBLE,
            ),
        ),
        ColumnSpec(
            label="Mosaic",
            op_factory=_stone_paint_op_factory(
                style=STONE_COBBLESTONE,
                sub_pattern=STONE_COBBLE_MOSAIC,
            ),
        ),
    ],
    seed=7,
    params={"family": "Stone", "style": "Cobblestone"},
))


__all__ = []
