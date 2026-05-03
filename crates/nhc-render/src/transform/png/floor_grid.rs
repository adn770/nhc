//! Floor-grid op rasterisation — Phase 5.2.4 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.7 of `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors `_draw_floor_grid_from_ir`: the per-edge wobbly grid
//! polyline generator stays in `primitives::floor_grid` (it owns
//! the `PyRandom` + Perlin parity contract); the PNG handler
//! wraps the active `tiny_skia::Pixmap` in a `SkiaPainter` and
//! forwards the room/corridor `PathOps` returned by
//! `paint_floor_grid_paths` through `stroke_path`. The room
//! stroke is wrapped in `push_clip(region_outline, EvenOdd)` /
//! `pop_clip()` to mirror the legacy `Mask::new` +
//! `mask.fill_path(EvenOdd)` envelope; the corridor stroke runs
//! unclipped.

use crate::ir::{FloorGridOp, FloorIR, OpEntry, Outline};
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, SkiaPainter,
    Stroke, Vec2,
};
use crate::primitives::floor_grid::paint_floor_grid_paths;

use super::RasterCtx;

const GRID_WIDTH: f32 = 0.3;
const GRID_OPACITY: f32 = 0.7;
const INK_PAINT: Paint = Paint {
    color: Color { r: 0, g: 0, b: 0, a: GRID_OPACITY },
};

fn grid_stroke() -> Stroke {
    Stroke {
        width: GRID_WIDTH,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    }
}

/// Walk an IR `Outline` (single-ring or multi-ring) into a
/// `PathOps` clip path. Each ring contributes `MoveTo` + `LineTo*`
/// + `Close`. The legacy `polygon_path::build_outline_path`
/// applied the same shape against a `tiny_skia::PathBuilder`;
/// here we route through `PathOps` so the same clip can target
/// any `Painter` backend.
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

fn build_clip(
    op: &FloorGridOp<'_>,
    fir: &FloorIR<'_>,
) -> Option<PathOps> {
    let region_id = op.region_ref().filter(|r| !r.is_empty())?;
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let outline = region.outline()?;
    outline_to_pathops(&outline)
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_floor_grid_op() {
        Some(o) => o,
        None => return,
    };
    let tiles: Vec<(i32, i32, bool)> = op
        .tiles()
        .map(|v| {
            v.iter()
                .map(|t| (t.x(), t.y(), t.is_corridor()))
                .collect()
        })
        .unwrap_or_default();
    let (room_paths, corridor_paths) = paint_floor_grid_paths(
        fir.width_tiles() as i32,
        fir.height_tiles() as i32,
        &tiles,
        op.seed(),
    );
    let stroke = grid_stroke();
    let clip = build_clip(&op, fir);

    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);

    if !room_paths.is_empty() {
        match &clip {
            Some(clip_path) => {
                painter.push_clip(clip_path, FillRule::EvenOdd);
                painter.stroke_path(&room_paths, &INK_PAINT, &stroke);
                painter.pop_clip();
            }
            None => {
                painter.stroke_path(&room_paths, &INK_PAINT, &stroke);
            }
        }
    }
    if !corridor_paths.is_empty() {
        painter.stroke_path(&corridor_paths, &INK_PAINT, &stroke);
    }
}
