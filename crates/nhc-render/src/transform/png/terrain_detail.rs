//! Terrain-detail op rasterisation — Phase 9.1c port.
//!
//! Reads the structured ``tiles[]`` directly: water / lava /
//! chasm tiles are bucketed by `is_corridor`, dispatched through
//! the per-kind `primitives::terrain_detail::draw_*` painter to
//! get one `<g>` envelope per (kind, bucket), then routed
//! through `paint_fragments`. The room bucket is rasterised under
//! the `clip_region` mask; the corridor bucket renders unclipped.

use tiny_skia::{FillRule, Mask};

use crate::ir::{FloorIR, OpEntry, TerrainDetailOp, TerrainKind};
use crate::primitives;

use super::fragment::paint_fragments;
use super::polygon_path::build_outline_path;
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

    let seed = op.seed();
    let ember_ink = lava_ember_ink(op.theme());

    let mut room: Vec<String> = Vec::new();
    room.extend(primitives::terrain_detail::draw_water(&water_room, seed));
    room.extend(primitives::terrain_detail::draw_lava(
        &lava_room, seed, ember_ink,
    ));
    room.extend(primitives::terrain_detail::draw_chasm(&chasm_room, seed));

    let mut corridor: Vec<String> = Vec::new();
    corridor.extend(primitives::terrain_detail::draw_water(&water_corr, seed));
    corridor.extend(primitives::terrain_detail::draw_lava(
        &lava_corr, seed, ember_ink,
    ));
    corridor.extend(primitives::terrain_detail::draw_chasm(&chasm_corr, seed));

    if room.is_empty() && corridor.is_empty() {
        return;
    }

    let clip_mask = build_clip_mask(&op, fir, ctx);
    paint_fragments(&room, 1.0, clip_mask.as_ref(), ctx);
    paint_fragments(&corridor, 1.0, None, ctx);
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

fn build_clip_mask(
    op: &TerrainDetailOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let region_id = op.region_ref().filter(|r| !r.is_empty())?;
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let outline = region.outline()?;
    let path = build_outline_path(&outline)?;
    let mut mask = Mask::new(ctx.pixmap.width(), ctx.pixmap.height())?;
    mask.fill_path(&path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}
