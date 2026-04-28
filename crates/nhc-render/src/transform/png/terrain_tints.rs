//! Terrain-tints op rasterisation — Phase 5.2.3 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Mirrors `_draw_terrain_tint_from_ir` in
//! `nhc/rendering/ir_to_svg.py`:
//!
//! - Per-tile WATER / GRASS / LAVA / CHASM rects, palette-keyed
//!   by the floor's theme. Painted inside the dungeon-interior
//!   clip mask (built from the region named by
//!   `op.clip_region()`).
//! - Per-room `ROOM_TYPE_TINTS` washes, painted unclipped on top
//!   of the tile rects.
//!
//! The palette table mirrors `THEME_PALETTES` in
//! `nhc/rendering/terrain_palette.py` — only the `(tint,
//! tint_opacity)` pairs travel with the rasteriser; `detail_ink`
//! belongs to the terrain-detail layer.

use tiny_skia::{
    Color, FillRule, Mask, Paint, PathBuilder, Rect, Transform,
};

use crate::ir::{FloorIR, OpEntry, Polygon, TerrainKind, TerrainTintOp};

use super::RasterCtx;

const CELL: f32 = 32.0;

/// `(tint_hex, opacity)` pair for one terrain kind in one theme.
type TerrainStyle = (&'static str, f32);

/// `(water, grass, lava, chasm)`. Indexes match the
/// `TerrainKind` enum from `floor_ir.fbs` minus 1 (Water=1 →
/// idx 0, Grass=4 → idx 3).
type ThemeRow = [TerrainStyle; 4];

/// Look up the palette for `theme`. Falls back to "dungeon" —
/// matches `terrain_palette.py:get_palette`.
fn palette_for(theme: &str) -> &'static ThemeRow {
    // Order: Water=1, Lava=2, Chasm=3, Grass=4.
    match theme {
        "crypt" => &[
            ("#7A9EAA", 0.12), // water
            ("#C47060", 0.15), // lava
            ("#777777", 0.12), // chasm
            ("#6B8B6B", 0.10), // grass
        ],
        "cave" => &[
            ("#5B8FA0", 0.18),
            ("#D49070", 0.20),
            ("#666666", 0.15),
            ("#5A7A5A", 0.15),
        ],
        "sewer" => &[
            ("#6A9A80", 0.20),
            ("#C48060", 0.15),
            ("#707070", 0.12),
            ("#5A8A5A", 0.18),
        ],
        "castle" => &[
            ("#90C0D8", 0.12),
            ("#D4816B", 0.15),
            ("#999999", 0.08),
            ("#88B888", 0.10),
        ],
        "forest" => &[
            ("#7AACB8", 0.15),
            ("#C48060", 0.15),
            ("#777777", 0.10),
            ("#5A9A5A", 0.20),
        ],
        "abyss" => &[
            ("#4A7888", 0.22),
            ("#E06040", 0.25),
            ("#444444", 0.20),
            ("#3A5A3A", 0.08),
        ],
        "tower" => &[
            ("#8AAABE", 0.12),
            ("#C08070", 0.12),
            ("#9A9AAA", 0.10),
            ("#7A9A7A", 0.08),
        ],
        "settlement" => &[
            ("#90C0D0", 0.10),
            ("#D4816B", 0.10),
            ("#999999", 0.08),
            ("#88B888", 0.12),
        ],
        "town" => &[
            ("#90C0D0", 0.15),
            ("#D4816B", 0.10),
            ("#999999", 0.10),
            ("#88C878", 0.30),
        ],
        "mine" => &[
            ("#6A8A8A", 0.15),
            ("#D08050", 0.20),
            ("#5A4A3A", 0.18),
            ("#6A7A5A", 0.10),
        ],
        "fungal_cavern" => &[
            ("#5A8A70", 0.18),
            ("#C07060", 0.12),
            ("#5A5A4A", 0.15),
            ("#4A8A4A", 0.25),
        ],
        "lava_chamber" => &[
            ("#4A6878", 0.12),
            ("#E06030", 0.28),
            ("#3A2A1A", 0.22),
            ("#4A5A3A", 0.06),
        ],
        "underground_lake" => &[
            ("#4A7898", 0.25),
            ("#C08060", 0.10),
            ("#3A4A5A", 0.18),
            ("#4A6A4A", 0.10),
        ],
        // dungeon (default)
        _ => &[
            ("#8BB8D0", 0.15),
            ("#D4816B", 0.18),
            ("#888888", 0.10),
            ("#7BA87B", 0.12),
        ],
    }
}

fn style_for(palette: &ThemeRow, kind: TerrainKind) -> Option<TerrainStyle> {
    let idx = match kind {
        TerrainKind::Water => 0,
        TerrainKind::Lava => 1,
        TerrainKind::Chasm => 2,
        TerrainKind::Grass => 3,
        _ => return None,
    };
    Some(palette[idx])
}

fn parse_hex_rgb(s: &str) -> Option<(u8, u8, u8)> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let r = u8::from_str_radix(&s[0..2], 16).ok()?;
    let g = u8::from_str_radix(&s[2..4], 16).ok()?;
    let b = u8::from_str_radix(&s[4..6], 16).ok()?;
    Some((r, g, b))
}

fn paint_for(hex: &str, opacity: f32) -> Paint<'static> {
    let mut p = Paint::default();
    let (r, g, b) = parse_hex_rgb(hex).unwrap_or((0, 0, 0));
    let color = Color::from_rgba(
        r as f32 / 255.0,
        g as f32 / 255.0,
        b as f32 / 255.0,
        opacity.clamp(0.0, 1.0),
    )
    .unwrap_or(Color::TRANSPARENT);
    p.set_color(color);
    p.anti_alias = true;
    p
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    ctx: &mut RasterCtx<'_>,
) {
    let op = match entry.op_as_terrain_tint_op() {
        Some(o) => o,
        None => return,
    };
    let theme = fir.theme().unwrap_or("dungeon");
    let palette = palette_for(theme);

    let clip_mask = build_clip_mask(&op, fir, ctx);
    draw_tiles(&op, palette, ctx, clip_mask.as_ref());
    draw_washes(&op, ctx);
}

fn draw_tiles(
    op: &TerrainTintOp<'_>,
    palette: &ThemeRow,
    ctx: &mut RasterCtx<'_>,
    mask: Option<&Mask>,
) {
    let tiles = match op.tiles() {
        Some(t) => t,
        None => return,
    };
    for tile in tiles.iter() {
        let style = match style_for(palette, tile.kind()) {
            Some(s) => s,
            None => continue,
        };
        let px = tile.x() as f32 * CELL;
        let py = tile.y() as f32 * CELL;
        let rect = match Rect::from_xywh(px, py, CELL, CELL) {
            Some(r) => r,
            None => continue,
        };
        let paint = paint_for(style.0, style.1);
        ctx.pixmap.fill_rect(rect, &paint, ctx.transform, mask);
    }
}

fn draw_washes(op: &TerrainTintOp<'_>, ctx: &mut RasterCtx<'_>) {
    let washes = match op.room_washes() {
        Some(w) => w,
        None => return,
    };
    for wash in washes.iter() {
        let color = match wash.color() {
            Some(c) => c,
            None => continue,
        };
        let px = wash.x() as f32 * CELL;
        let py = wash.y() as f32 * CELL;
        let pw = wash.w() as f32 * CELL;
        let ph = wash.h() as f32 * CELL;
        let rect = match Rect::from_xywh(px, py, pw, ph) {
            Some(r) => r,
            None => continue,
        };
        let paint = paint_for(color, wash.opacity());
        ctx.pixmap.fill_rect(rect, &paint, ctx.transform, None);
    }
}

fn build_clip_mask(
    op: &TerrainTintOp<'_>,
    fir: &FloorIR<'_>,
    ctx: &RasterCtx<'_>,
) -> Option<Mask> {
    let region_id = op.clip_region()?;
    if region_id.is_empty() {
        return None;
    }
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let polygon = region.polygon()?;
    let path = build_polygon_path(&polygon)?;
    let (w, h) = (ctx.pixmap.width(), ctx.pixmap.height());
    let mut mask = Mask::new(w, h)?;
    mask.fill_path(&path, FillRule::EvenOdd, true, ctx.transform);
    Some(mask)
}

fn build_polygon_path(polygon: &Polygon<'_>) -> Option<tiny_skia::Path> {
    let paths = polygon.paths()?;
    let rings = polygon.rings()?;
    let mut pb = PathBuilder::new();
    for ring in rings.iter() {
        let start = ring.start() as usize;
        let count = ring.count() as usize;
        if count < 2 {
            continue;
        }
        for j in 0..count {
            let v = paths.get(start + j);
            let x = v.x();
            let y = v.y();
            if j == 0 {
                pb.move_to(x, y);
            } else {
                pb.line_to(x, y);
            }
        }
        pb.close();
    }
    pb.finish()
}

// Suppress dead-code on Transform import — used by tests + future
// sub-phases; current handler reaches it via ctx.transform.
#[allow(dead_code)]
const _UNUSED: Option<Transform> = None;
