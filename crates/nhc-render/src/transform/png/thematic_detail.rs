//! Thematic-detail op rasterisation — Phase 5.3.3 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.11 of `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors `_draw_thematic_detail_from_ir`: webs / bones /
//! skulls per theme, gated by `macabre_detail`. The structured
//! input lives on `ThematicDetailOp` (tiles, is_corridor,
//! wall_corners). `primitives::thematic_detail::thematic_detail_shapes`
//! returns the `(room, corridor)` shape buckets;
//! `paint_thematic_detail_side` paints them via the Painter
//! trait, wrapping each per-fragment composite in
//! `begin_group(opacity) / end_group()` (web 0.35, bone 0.4,
//! skull 0.45). Room-side fragments paint inside the dungeon-
//! interior clip via `push_clip(region_outline, EvenOdd)` /
//! `pop_clip`; corridor-side fragments paint unclipped.

use crate::ir::{FloorIR, OpEntry, Outline, ThematicDetailOp};
use crate::painter::{FillRule, PathOps, Painter, SkiaPainter, Vec2};
use crate::primitives::thematic_detail::{
    paint_thematic_detail_side, thematic_detail_shapes,
};

use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_thematic_detail_op() {
        Some(o) => o,
        None => return,
    };
    let tiles = op.tiles();
    let is_corridor = op.is_corridor();
    let wall_corners = op.wall_corners();
    let tiles = match (tiles, is_corridor) {
        (Some(t), Some(c)) => t
            .iter()
            .enumerate()
            .map(|(i, coord)| {
                let wc = wall_corners
                    .as_ref()
                    .map(|v| v.get(i))
                    .unwrap_or(0);
                (coord.x(), coord.y(), c.get(i), wc)
            })
            .collect::<Vec<_>>(),
        _ => return,
    };
    if tiles.is_empty() {
        return;
    }

    let theme = op.theme().unwrap_or("");
    let macabre = fir
        .flags()
        .map(|f| f.macabre_detail())
        .unwrap_or(true);
    let (room, corridor) =
        thematic_detail_shapes(&tiles, op.seed(), theme, macabre);

    let clip = build_clip_pathops(&op, fir);

    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);

    // Room: clipped inside the dungeon-interior outline (when
    // present), wrapped in per-fragment `<g opacity>` envelopes.
    match &clip {
        Some(clip_path) => {
            painter.push_clip(clip_path, FillRule::EvenOdd);
            paint_thematic_detail_side(&mut painter, &room);
            painter.pop_clip();
        }
        None => {
            paint_thematic_detail_side(&mut painter, &room);
        }
    }

    // Corridor: unclipped.
    paint_thematic_detail_side(&mut painter, &corridor);
}

/// Walk the thematic-detail op's `region_ref` outline into a
/// `PathOps` clip path. Returns `None` when the region is
/// missing / has no outline; the caller drops the clip and
/// paints the room buckets unclipped (matching the legacy
/// `Mask::new` falling back to `None`).
fn build_clip_pathops(
    op: &ThematicDetailOp<'_>,
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
