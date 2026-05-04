//! Terrain-tints op rasterisation — Phase 5.2.3 of
//! `plans/nhc_ir_migration_plan.md`, ported to the Painter trait
//! in Phase 2.8 of `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors `_draw_terrain_tint_from_ir` in
//! `nhc/rendering/ir_to_svg.py`:
//!
//! - Per-tile WATER / GRASS / LAVA / CHASM rects, palette-keyed
//!   by the floor's theme. Painted inside the dungeon-interior
//!   clip mask (built from the region named by
//!   `op.region_ref()`).
//! - Per-room `ROOM_TYPE_TINTS` washes, painted unclipped on top
//!   of the tile rects.
//!
//! The palette table mirrors `THEME_PALETTES` in
//! `nhc/rendering/terrain_palette.py` — only the `(tint,
//! tint_opacity)` pairs travel with the rasteriser; `detail_ink`
//! belongs to the terrain-detail layer. The PNG handler keeps the
//! palette table inline (PNG-only theme dispatch) and converts the
//! IR's `TerrainKind` discriminant into the `(hex, opacity)` pairs
//! that the Painter primitive consumes.

use std::collections::HashMap;

use crate::ir::{FloorIR, Outline, OpEntry, TerrainKind, TerrainTintOp};
use crate::painter::{FillRule, Painter, PathOps, Vec2};
use crate::primitives::terrain_tints::paint_terrain_tints;

/// `(tint_hex, opacity)` pair for one terrain kind in one theme.
type TerrainStyle = (&'static str, f64);

/// `(water, lava, chasm, grass)`. Indexes match the
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

/// Build the discriminant-keyed palette map that
/// `paint_terrain_tints` consumes. Only the kinds present in the
/// theme row land in the map; unknown discriminants short-circuit
/// at the primitive level via `palette.get(&kind).is_none()`.
fn build_palette_map(palette: &ThemeRow) -> HashMap<u8, (String, f64)> {
    let mut map = HashMap::with_capacity(4);
    map.insert(TerrainKind::Water.0 as u8, (palette[0].0.to_string(), palette[0].1));
    map.insert(TerrainKind::Lava.0 as u8, (palette[1].0.to_string(), palette[1].1));
    map.insert(TerrainKind::Chasm.0 as u8, (palette[2].0.to_string(), palette[2].1));
    map.insert(TerrainKind::Grass.0 as u8, (palette[3].0.to_string(), palette[3].1));
    map
}

/// Walk an IR `Outline` (single-ring or multi-ring) into a
/// `PathOps` clip path. Each ring contributes `MoveTo` + `LineTo*`
/// + `Close`. Mirrors the helper introduced in Phase 2.7 (see
/// `transform/png/floor_grid.rs::outline_to_pathops`); duplicated
/// here intentionally — Phase 2.20 will tidy when the legacy
/// `polygon_path` / `path_parser` modules retire and a shared
/// helper home opens up.
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
    op: &TerrainTintOp<'_>,
    fir: &FloorIR<'_>,
) -> Option<PathOps> {
    let region_id = op.region_ref().filter(|r| !r.is_empty())?;
    let regions = fir.regions()?;
    let region = regions.iter().find(|r| r.id() == region_id)?;
    let outline = region.outline()?;
    outline_to_pathops(&outline)
}

/// Collect the IR's tile array into the `(x, y, kind_disc)`
/// triples that `paint_terrain_tints` consumes.
fn collect_tiles(op: &TerrainTintOp<'_>) -> Vec<(i32, i32, u8)> {
    let Some(tiles) = op.tiles() else {
        return Vec::new();
    };
    tiles
        .iter()
        .map(|t| (t.x(), t.y(), t.kind().0 as u8))
        .collect()
}

/// Collect the IR's room-wash array into the `(x, y, w, h, color,
/// opacity)` tuples that `paint_terrain_tints` consumes.
/// `RoomWash.opacity` is f32 in the IR; widen to f64 to match the
/// Painter primitive's signature, which mirrors the legacy
/// SVG-string emitter's `(String, f64)` API.
fn collect_washes(op: &TerrainTintOp<'_>) -> Vec<(i32, i32, i32, i32, String, f64)> {
    let Some(washes) = op.room_washes() else {
        return Vec::new();
    };
    let mut out = Vec::with_capacity(washes.len());
    for wash in washes.iter() {
        let Some(color) = wash.color() else { continue };
        out.push((
            wash.x(),
            wash.y(),
            wash.w(),
            wash.h(),
            color.to_string(),
            wash.opacity() as f64,
        ));
    }
    out
}

pub(super) fn draw(
    entry: &OpEntry<'_>,
    fir: &FloorIR<'_>,
    painter: &mut dyn Painter,
) {
    let op = match entry.op_as_terrain_tint_op() {
        Some(o) => o,
        None => return,
    };
    let theme = fir.theme().unwrap_or("dungeon");
    let palette = palette_for(theme);
    let palette_map = build_palette_map(palette);

    let tiles = collect_tiles(&op);
    let washes = collect_washes(&op);
    let clip = build_clip(&op, fir);

    // Tile tints: clipped to the dungeon-interior outline when the
    // op carries a region_ref. Mirrors the legacy
    // `Mask::new` + `mask.fill_path(EvenOdd)` envelope the prior
    // direct-call handler applied around the per-tile fill_rect
    // calls. Washes (below) run unclipped — the legacy handler
    // passed `None` as the mask there.
    if !tiles.is_empty() {
        match &clip {
            Some(clip_path) => {
                painter.push_clip(clip_path, FillRule::EvenOdd);
                paint_terrain_tints(painter, &tiles, &palette_map, &[]);
                painter.pop_clip();
            }
            None => {
                paint_terrain_tints(painter, &tiles, &palette_map, &[]);
            }
        }
    }
    // Washes layered on top, unclipped.
    if !washes.is_empty() {
        paint_terrain_tints(painter, &[], &palette_map, &washes);
    }
}
