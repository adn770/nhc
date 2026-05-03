//! Floor-detail op rasterisation — Phase 5.3.2 of
//! `plans/nhc_ir_migration_plan.md`, with the wood-floor short-
//! circuit ported in Phase 9.2c, and the floor-detail-proper path
//! migrated to the Painter trait in Phase 2.10 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors `_draw_floor_detail_from_ir`. Two modes:
//!
//! - Wood-floor short-circuit (`wood_tiles` / `wood_rooms` /
//!   `wood_building_polygon` populated) — dispatch through
//!   `primitives::wood_floor::draw_wood_floor` and paint with the
//!   dungeon-poly clip mask applied uniformly. Stays on the
//!   `paint_fragments` SVG-string round-trip until 2.15 ports the
//!   `wood_floor` primitive to the Painter trait.
//! - Otherwise: floor-detail-proper (`tiles` + `is_corridor` +
//!   `seed` + `theme` + `macabre`) flows through
//!   `primitives::floor_detail::floor_detail_shapes` to produce
//!   per-side `(cracks, scratches, stones)` buckets, then through
//!   `paint_floor_detail_side` against a `SkiaPainter`. Room
//!   buckets paint inside a `push_clip(region_outline, EvenOdd)` /
//!   `pop_clip` envelope; corridor buckets paint unclipped.
//!
//! Schema 3.1 (Phase 0.1 of plans/nhc_pure_ir_plan.md) drops the
//! legacy thematic passthrough reads on `room_groups` /
//! `corridor_groups`: ThematicDetailOp has owned thematic detail
//! since schema 2.0 and the fields haven't been populated since
//! 3.0. The schema fields stay declared until the 4.0 cut.
//!
//! Bucket compositing: the legacy SVG output wraps each non-empty
//! bucket in `<g opacity="…">` (`0.5` cracks, `0.45` scratches,
//! `0.8` stones). Pre-2.10 the PNG handler dispatched to
//! `paint_fragments`, which routes each `<g opacity>` envelope
//! through `paint_offscreen_group` (Phase 5.10's offscreen-buffer
//! composite). Phase 2.10 lifts that into the Painter trait via
//! `SkiaPainter::begin_group` / `end_group` so the SVG-string
//! round-trip is no longer needed for floor-detail-proper.

use tiny_skia::{FillRule as SkFillRule, Mask, PathBuilder};

use crate::ir::{FloorDetailOp, FloorIR, OpEntry, Outline};
use crate::painter::{FillRule, PathOps, Painter, SkiaPainter, Vec2};
use crate::primitives::floor_detail::{
    floor_detail_shapes, paint_floor_detail_side,
};
use crate::primitives::wood_floor::{
    draw_wood_floor, PolyVertex, WoodRoom,
};

use super::fragment::paint_fragments;
use super::polygon_path::build_outline_path;
use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_floor_detail_op() {
        Some(o) => o,
        None => return,
    };

    // Wood-floor short-circuit (Phase 9.2c). When any of the
    // structured fields is populated, dispatch through the
    // `wood_floor` primitive and short-circuit the regular
    // floor-detail flow. Stays on the `paint_fragments` SVG path
    // until Phase 2.15 ports `wood_floor` to the Painter trait.
    let wood_rooms: Vec<WoodRoom> = op
        .wood_rooms()
        .map(|v| {
            v.iter()
                .map(|r| WoodRoom {
                    x: r.x(),
                    y: r.y(),
                    w: r.w(),
                    h: r.h(),
                    region_ref: r.region_ref().unwrap_or("").to_string(),
                })
                .collect()
        })
        .unwrap_or_default();
    let wood_tiles: Vec<(i32, i32)> = op
        .wood_tiles()
        .map(|v| v.iter().map(|t| (t.x(), t.y())).collect())
        .unwrap_or_default();
    let wood_polygon: Vec<PolyVertex> = op
        .wood_building_polygon()
        .map(|v| {
            v.iter()
                .map(|p| PolyVertex {
                    x: f64::from(p.x()),
                    y: f64::from(p.y()),
                })
                .collect()
        })
        .unwrap_or_default();
    if !wood_rooms.is_empty()
        || !wood_tiles.is_empty()
        || !wood_polygon.is_empty()
    {
        let frags = draw_wood_floor(
            &wood_tiles, &wood_polygon, &wood_rooms, op.seed(),
        );
        // The wood base fill now lives in WallsAndFloorsOp
        // (structural layer); this op only paints grain + seam
        // strokes. Clip them to the building polygon so they
        // don't bleed past the chamfered / curved corners of
        // octagon / circle / L-shape buildings, intersected
        // with the dungeon clip when both are present.
        let clip_mask = build_wood_clip_mask(&op, fir, &wood_polygon, ctx);
        paint_fragments(&frags, 1.0, clip_mask.as_ref(), ctx);
        return;
    }

    let theme = op.theme().unwrap_or("");
    let macabre = fir
        .flags()
        .map(|f| f.macabre_detail())
        .unwrap_or(true);
    let tiles: Vec<(i32, i32, bool)> = match (op.tiles(), op.is_corridor()) {
        (Some(t), Some(c)) => t
            .iter()
            .enumerate()
            .map(|(i, coord)| (coord.x(), coord.y(), c.get(i)))
            .collect(),
        _ => Vec::new(),
    };
    if tiles.is_empty() {
        return;
    }

    let (room, corridor) =
        floor_detail_shapes(&tiles, op.seed(), theme, macabre);

    let clip = build_clip_pathops(&op, fir);

    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);

    // Room: clipped inside the dungeon-interior outline (when
    // present), wrapped in `<g opacity>` group envelopes.
    match &clip {
        Some(clip_path) => {
            painter.push_clip(clip_path, FillRule::EvenOdd);
            paint_floor_detail_side(&mut painter, &room);
            painter.pop_clip();
        }
        None => {
            paint_floor_detail_side(&mut painter, &room);
        }
    }

    // Corridor: unclipped.
    paint_floor_detail_side(&mut painter, &corridor);
}

/// Walk the floor-detail op's `region_ref` outline into a
/// `PathOps` clip path. Returns `None` when the region is
/// missing / has no outline; the caller drops the clip and
/// paints the room buckets unclipped (matching the legacy
/// `Mask::new` falling back to `None`).
fn build_clip_pathops(
    op: &FloorDetailOp<'_>,
    fir: &FloorIR<'_>,
) -> Option<PathOps> {
    let region_id = op.region_ref().filter(|r| !r.is_empty())?;
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let outline = region.outline()?;
    outline_to_pathops(&outline)
}

fn outline_to_pathops(outline: &Outline<'_>) -> Option<PathOps> {
    let verts = outline.vertices()?;
    if verts.is_empty() {
        return None;
    }
    let rings = outline.rings();
    let ring_iter: Vec<(usize, usize)> = match rings {
        Some(r) if r.len() > 0 => r
            .iter()
            .map(|pr| (pr.start() as usize, pr.count() as usize))
            .collect(),
        _ => vec![(0, verts.len())],
    };
    let mut path = PathOps::new();
    let mut any = false;
    for (start, count) in ring_iter {
        if count < 2 {
            continue;
        }
        for j in 0..count {
            let v = verts.get(start + j);
            let p = Vec2::new(v.x(), v.y());
            if j == 0 {
                path.move_to(p);
            } else {
                path.line_to(p);
            }
        }
        path.close();
        any = true;
    }
    if !any {
        return None;
    }
    Some(path)
}

/// Wood-floor clip mask: building polygon intersected with the
/// dungeon clip when both are present. The grain + seam strokes
/// from `draw_wood_floor` are bbox-aligned to each room rect, so
/// without this mask they bleed past the chamfered corners of
/// octagon / circle / L-shape building footprints.
///
/// Used only by the wood-floor short-circuit path which still
/// dispatches through `paint_fragments` (the legacy SVG-string
/// route). Phase 2.15 will port that dispatch to the Painter
/// trait too.
fn build_wood_clip_mask(
    op: &FloorDetailOp<'_>,
    fir: &FloorIR<'_>,
    polygon: &[PolyVertex],
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let dungeon = build_dungeon_mask(op, fir, ctx);
    if polygon.len() < 3 {
        return dungeon;
    }
    let mut pb = PathBuilder::new();
    let first = polygon[0];
    pb.move_to(first.x as f32, first.y as f32);
    for v in &polygon[1..] {
        pb.line_to(v.x as f32, v.y as f32);
    }
    pb.close();
    let bldg_path = pb.finish()?;
    if let Some(mut mask) = dungeon {
        // Mask::intersect_path keeps only the pixels inside the
        // building polygon AND the dungeon clip mask.
        mask.intersect_path(
            &bldg_path, SkFillRule::EvenOdd, true, ctx.transform,
        );
        return Some(mask);
    }
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&bldg_path, SkFillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}

fn build_dungeon_mask(
    op: &FloorDetailOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let region_id = op.region_ref().filter(|r| !r.is_empty())?;
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let outline = region.outline()?;
    let path = build_outline_path(&outline)?;
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&path, SkFillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}
