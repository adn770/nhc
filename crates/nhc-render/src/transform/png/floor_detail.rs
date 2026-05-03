//! Floor-detail op rasterisation — Phase 5.3.2 of
//! `plans/nhc_ir_migration_plan.md`, with the wood-floor short-
//! circuit ported in Phase 9.2c, the floor-detail-proper path
//! migrated to the Painter trait in Phase 2.10 of
//! `plans/nhc_pure_ir_plan.md`, and the wood-floor short-circuit
//! ported to the Painter trait in Phase 2.15a.
//!
//! Mirrors `_draw_floor_detail_from_ir`. Two modes:
//!
//! - Wood-floor short-circuit (`wood_tiles` / `wood_rooms` /
//!   `wood_building_polygon` populated) — dispatch through
//!   `primitives::wood_floor::paint_wood_floor` against a
//!   `SkiaPainter`. The dungeon-interior outline (when present)
//!   and the building polygon are pushed onto the painter's clip
//!   stack as `PathOps`; nested `push_clip` calls intersect, so
//!   the grain + seam strokes paint inside `dungeon ∩ building`
//!   without bleeding past the chamfered corners of octagon /
//!   circle / L-shape buildings.
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
//! `0.8` stones for floor-detail-proper; `0.35` grain for
//! wood-floor). Pre-2.10 the PNG handler dispatched to
//! `paint_fragments`, which routes each `<g opacity>` envelope
//! through `paint_offscreen_group` (Phase 5.10's offscreen-buffer
//! composite). Phases 2.10 / 2.15a lift that into the Painter
//! trait via `SkiaPainter::begin_group` / `end_group` so the
//! SVG-string round-trip is no longer needed for either path —
//! the `paint_fragments` import is gone.

use crate::ir::{FloorDetailOp, FloorIR, OpEntry, Outline};
use crate::painter::{FillRule, PathOps, Painter, SkiaPainter, Vec2};
use crate::primitives::floor_detail::{
    floor_detail_shapes, paint_floor_detail_side,
};
use crate::primitives::wood_floor::{
    paint_wood_floor, PolyVertex, WoodRoom,
};

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

    // Wood-floor short-circuit (Phase 9.2c, ported to the
    // Painter trait in Phase 2.15a). When any of the structured
    // fields is populated, dispatch through the `wood_floor`
    // primitive and short-circuit the regular floor-detail flow.
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
        // The wood base fill now lives in WallsAndFloorsOp
        // (structural layer); this op only paints the per-room
        // overlay rect, the grain + seam strokes. Clip them to
        // the building polygon so they don't bleed past the
        // chamfered / curved corners of octagon / circle /
        // L-shape buildings, intersected with the dungeon clip
        // when both are present.
        let dungeon_clip = build_clip_pathops(&op, fir);
        let building_clip = polygon_to_pathops(&wood_polygon);

        let mut painter =
            SkiaPainter::with_transform(ctx.pixmap, ctx.transform);

        // Push dungeon clip first (when present), then the
        // building polygon — push_clip intersects with the
        // current top, so the result is `dungeon ∩ building`.
        let mut pushed = 0;
        if let Some(clip) = dungeon_clip.as_ref() {
            painter.push_clip(clip, FillRule::EvenOdd);
            pushed += 1;
        }
        if let Some(clip) = building_clip.as_ref() {
            painter.push_clip(clip, FillRule::EvenOdd);
            pushed += 1;
        }
        paint_wood_floor(
            &mut painter, &wood_tiles, &wood_polygon, &wood_rooms, op.seed(),
        );
        for _ in 0..pushed {
            painter.pop_clip();
        }
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

/// Build a `PathOps` clip from the wood-floor's building polygon.
/// Returns `None` when the polygon has fewer than 3 vertices —
/// the caller drops that clip layer and falls back to the
/// dungeon clip alone (matching the legacy `build_wood_clip_mask`
/// short-circuit).
fn polygon_to_pathops(polygon: &[PolyVertex]) -> Option<PathOps> {
    if polygon.len() < 3 {
        return None;
    }
    let mut path = PathOps::new();
    let first = polygon[0];
    path.move_to(Vec2::new(first.x as f32, first.y as f32));
    for v in &polygon[1..] {
        path.line_to(Vec2::new(v.x as f32, v.y as f32));
    }
    path.close();
    Some(path)
}
