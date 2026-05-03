//! Terrain-detail op rasterisation — Phase 9.1c port, ported to
//! the Painter trait in Phase 2.12 of `plans/nhc_pure_ir_plan.md`.
//!
//! Reads the structured ``tiles[]`` directly: water / lava /
//! chasm tiles are bucketed by `is_corridor`, then painted via
//! the per-kind `primitives::terrain_detail::paint_*` Painter-
//! trait emitters. The room buckets paint inside a
//! `push_clip(region_outline, EvenOdd)` / `pop_clip` envelope;
//! the corridor buckets paint unclipped.
//!
//! Unlike floor_detail / thematic_detail (Phases 2.10 / 2.11),
//! the terrain_detail primitive has **no FFI export** — only this
//! handler consumes it. So Phase 2.12 REPLACES the legacy
//! `draw_water` / `draw_lava` / `draw_chasm` SVG-string emitters
//! with the new `paint_*` Painter-trait emitters outright; no
//! dual path is required. Python SVG output flows through its
//! own `nhc.rendering._terrain_detail` module.

use crate::ir::{FloorIR, OpEntry, Outline, TerrainDetailOp, TerrainKind};
use crate::painter::{FillRule, PathOps, Painter, SkiaPainter, Vec2};
use crate::primitives::terrain_detail::{
    paint_chasm, paint_lava, paint_water,
};

use super::RasterCtx;

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_terrain_detail_op() {
        Some(o) => o,
        None => return,
    };
    let tiles = match op.tiles() {
        Some(v) if !v.is_empty() => v,
        _ => return,
    };

    let mut water_room: Vec<(i32, i32)> = Vec::new();
    let mut water_corr: Vec<(i32, i32)> = Vec::new();
    let mut lava_room: Vec<(i32, i32)> = Vec::new();
    let mut lava_corr: Vec<(i32, i32)> = Vec::new();
    let mut chasm_room: Vec<(i32, i32)> = Vec::new();
    let mut chasm_corr: Vec<(i32, i32)> = Vec::new();

    for tile in tiles.iter() {
        let coord = (tile.x(), tile.y());
        let dest = match (tile.kind(), tile.is_corridor()) {
            (TerrainKind::Water, false) => &mut water_room,
            (TerrainKind::Water, true) => &mut water_corr,
            (TerrainKind::Lava, false) => &mut lava_room,
            (TerrainKind::Lava, true) => &mut lava_corr,
            (TerrainKind::Chasm, false) => &mut chasm_room,
            (TerrainKind::Chasm, true) => &mut chasm_corr,
            _ => continue,
        };
        dest.push(coord);
    }

    let room_empty = water_room.is_empty()
        && lava_room.is_empty()
        && chasm_room.is_empty();
    let corr_empty = water_corr.is_empty()
        && lava_corr.is_empty()
        && chasm_corr.is_empty();
    if room_empty && corr_empty {
        return;
    }

    let seed = op.seed();
    let ember_ink = lava_ember_ink(op.theme());

    let clip = build_clip_pathops(&op, fir);

    let mut painter = SkiaPainter::with_transform(ctx.pixmap, ctx.transform);

    // Room: clipped inside the dungeon-interior outline (when
    // present). Each kind wraps its own `<g opacity>` envelope
    // through begin_group / end_group.
    if !room_empty {
        match &clip {
            Some(clip_path) => {
                painter.push_clip(clip_path, FillRule::EvenOdd);
                paint_water(&mut painter, &water_room, seed);
                paint_lava(&mut painter, &lava_room, seed, ember_ink);
                paint_chasm(&mut painter, &chasm_room, seed);
                painter.pop_clip();
            }
            None => {
                paint_water(&mut painter, &water_room, seed);
                paint_lava(&mut painter, &lava_room, seed, ember_ink);
                paint_chasm(&mut painter, &chasm_room, seed);
            }
        }
    }

    // Corridor: unclipped.
    if !corr_empty {
        paint_water(&mut painter, &water_corr, seed);
        paint_lava(&mut painter, &lava_corr, seed, ember_ink);
        paint_chasm(&mut painter, &chasm_corr, seed);
    }
}

/// Theme-specific lava ember `fill` colour. Mirrors
/// `terrain_palette.THEME_PALETTES[theme].lava.detail_ink`.
fn lava_ember_ink(theme: Option<&str>) -> &'static str {
    match theme.unwrap_or("dungeon") {
        "crypt" => "#903828",
        "cave" => "#A06040",
        "castle" => "#A04030",
        "swamp" => "#904830",
        "abyss" => "#B03020",
        "forest" => "#904830",
        "ruins" => "#904830",
        _ => "#A04030",
    }
}

/// Walk the terrain-detail op's `region_ref` outline into a
/// `PathOps` clip path. Returns `None` when the region is missing
/// / has no outline; the caller drops the clip and paints the
/// room buckets unclipped (matching the legacy `Mask::new` falling
/// back to `None`).
fn build_clip_pathops(
    op: &TerrainDetailOp<'_>,
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
