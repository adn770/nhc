"""Stone-decorator regions + PaintOps target real regions.

Regression cover for the Phase 2 emit gap where the stone-decorator
PaintOps (cobble / brick / flagstone / opus_romano / fieldstone) all
shipped with ``regionRef = ""``. The Rust ``paint_op::draw`` handler
returns ``false`` on empty ``region_ref`` so every stone-decorator
PaintOp was silently dropped, leaving keep courtyards (FLOOR + STREET
only, no GRASS background) rendering as plain page background.

The fix builds one ``Region(id="<prefix>.<i>")`` per disjoint
predicate-matching tile cluster (mirroring the water / lava / chasm
/ grass terrain regions) and emits one PaintOp per region. Per-tile
predicates live in ``nhc/rendering/_floor_detail.py``.
"""

from __future__ import annotations

import json

from nhc.dungeon.model import (
    Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
)
from nhc.rendering.ir.dump import dump
from nhc.rendering.ir_emitter import build_floor_ir


def _build_level_with_paved_tiles(
    coords: list[tuple[int, int]],
    surface_type: SurfaceType,
    terrain: Terrain = Terrain.FLOOR,
) -> Level:
    """Create a 12x12 Level with ``coords`` stamped as paved tiles.

    Wraps the level in a single rect Room so the v5 emit pipeline
    treats it as a normal dungeon-style level rather than a synthetic
    fixture.
    """
    level = Level.create_empty("L", "L", 1, 12, 12)
    for y in range(12):
        for x in range(12):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    for x, y in coords:
        level.tiles[y][x] = Tile(terrain=terrain, surface_type=surface_type)
    level.rooms = [
        Room(id="r1", rect=Rect(0, 0, 12, 12), shape=RectShape()),
    ]
    return level


def _emit_ir_dict(level: Level) -> dict:
    buf = bytes(build_floor_ir(level, seed=0))
    return json.loads(dump(buf))


def _regions_with_prefix(d: dict, prefix: str) -> list[str]:
    return [
        r["id"] for r in (d.get("regions") or [])
        if r["id"].startswith(f"{prefix}.")
    ]


def _paint_ops_for_region_ref(
    d: dict, region_ref: str,
) -> list[dict]:
    out: list[dict] = []
    for entry in (d.get("ops") or []):
        if entry.get("opType") != "PaintOp":
            continue
        op = entry.get("op") or {}
        if op.get("regionRef") == region_ref:
            out.append(op)
    return out


class TestPavedRegionEmission:
    """STREET tiles → ``paved.<i>`` Region + Stone-Cobble PaintOp."""

    def test_single_street_cluster_emits_one_paved_region(self):
        coords = [(2, 2), (3, 2), (4, 2), (2, 3), (3, 3), (4, 3)]
        level = _build_level_with_paved_tiles(coords, SurfaceType.STREET)
        d = _emit_ir_dict(level)
        paved = _regions_with_prefix(d, "paved")
        assert paved == ["paved.0"], (
            f"expected exactly one paved region, got {paved!r}"
        )
        ops = _paint_ops_for_region_ref(d, "paved.0")
        assert len(ops) == 1, (
            f"expected one PaintOp on paved.0, got {len(ops)}"
        )
        material = ops[0].get("material", {})
        assert material.get("family") == "Stone"
        assert material.get("style") == 0  # STONE_COBBLESTONE

    def test_two_disjoint_street_clusters_emit_two_paved_regions(self):
        coords = [(1, 1), (2, 1), (8, 8), (9, 8)]
        level = _build_level_with_paved_tiles(coords, SurfaceType.STREET)
        d = _emit_ir_dict(level)
        paved = sorted(_regions_with_prefix(d, "paved"))
        assert paved == ["paved.0", "paved.1"], (
            f"two disjoint STREET clusters must produce two paved.<i> "
            f"regions, got {paved!r}"
        )
        for rid in paved:
            assert _paint_ops_for_region_ref(d, rid), (
                f"missing PaintOp on {rid!r}"
            )

    def test_paved_region_outline_has_vertices(self):
        coords = [(2, 2), (3, 2), (2, 3), (3, 3)]
        level = _build_level_with_paved_tiles(coords, SurfaceType.STREET)
        d = _emit_ir_dict(level)
        paved_regions = [
            r for r in d["regions"] if r["id"].startswith("paved.")
        ]
        assert paved_regions, "expected at least one paved region"
        outline = paved_regions[0].get("outline") or {}
        verts = outline.get("vertices") or []
        assert len(verts) >= 4, (
            f"paved region outline must polygonise the tile cluster; "
            f"got {len(verts)} vertices"
        )

    def test_no_street_tiles_means_no_paved_region(self):
        level = _build_level_with_paved_tiles([], SurfaceType.STREET)
        d = _emit_ir_dict(level)
        assert _regions_with_prefix(d, "paved") == []
        # And no orphan cobble PaintOp either.
        for entry in (d.get("ops") or []):
            if entry.get("opType") != "PaintOp":
                continue
            op = entry.get("op") or {}
            mat = op.get("material") or {}
            assert not (
                mat.get("family") == "Stone"
                and mat.get("style") == 0
                and op.get("regionRef") == ""
            ), "no STREET tiles → no orphan empty-regionRef cobble PaintOp"


class TestStoneDecoratorPaintOpsNeverEmptyRegionRef:
    """Regression: the v5 stone-decorator PaintOps must always target
    a real region. Empty-regionRef PaintOps are silently dropped by
    ``crates/nhc-render/src/transform/png/paint_op.rs:28-31`` -- so a
    PaintOp emitted with ``regionRef = ""`` is a no-op for the
    rasteriser. None of the stone-decorator branches should leak one.
    """

    def test_street_cobble_emits_with_real_region_ref(self):
        coords = [(2, 2), (3, 2), (4, 2)]
        level = _build_level_with_paved_tiles(coords, SurfaceType.STREET)
        d = _emit_ir_dict(level)
        for entry in (d.get("ops") or []):
            if entry.get("opType") != "PaintOp":
                continue
            op = entry.get("op") or {}
            mat = op.get("material") or {}
            if mat.get("family") != "Stone":
                continue
            assert op.get("regionRef"), (
                f"stone-decorator PaintOp with material {mat!r} ships "
                f"empty regionRef; the Rust paint_op::draw handler "
                f"silently drops these. The PaintOp must target a "
                f"real region."
            )


class TestKeepSeedRendersCobbleOnCourtyard:
    """End-to-end: the keep generator's courtyard tiles must drive
    a paved region + Stone-Cobble PaintOp. Without this, the keep's
    fortified courtyard renders as page-background cream (cf. the
    keep_seed42 sample).
    """

    def test_keep_seed42_emits_paved_region_for_courtyard(self):
        import random
        from nhc.sites.keep import assemble_keep
        from nhc.rendering.ir_emitter import build_floor_ir

        site = assemble_keep("k", random.Random(42))
        buf = bytes(build_floor_ir(site.surface, seed=42, site=site))
        d = json.loads(dump(buf))
        paved = _regions_with_prefix(d, "paved")
        assert paved, (
            "keep_seed42 surface must register at least one paved.<i> "
            "region for the FLOOR + STREET courtyard tiles"
        )
        for rid in paved:
            assert _paint_ops_for_region_ref(d, rid), (
                f"missing Stone-Cobble PaintOp on {rid!r}"
            )
