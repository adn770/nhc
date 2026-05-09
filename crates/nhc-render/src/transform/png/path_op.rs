//! PathOp consumer — connected tile networks with style-driven
//! topology.
//!
//! Phase 2.10 of `plans/nhc_pure_ir_v5_migration_plan.md`. Lifts
//! the v4e CartTracks 4-neighbour topology painter (the L-corner /
//! T-junction dispatch shipped at d82c9900, lifted here from
//! `crates/nhc-render/src/primitives/cart_tracks.rs::paint_cart_tracks`)
//! and the OreVein contour painter
//! (`primitives/ore_deposit.rs::paint_ore_deposit`) into the v5
//! handler. The unordered tile list in `PathOp.tiles` is enough
//! for both pipelines: CartTracks derives the per-tile open-sides
//! 4-bit mask from the set, OreVein consumes the raw set.

use std::collections::HashSet;
use std::f64::consts::PI;

use flatbuffers::{ForwardsUOffset, Vector};
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::ir::{PathOp, PathStyle, Region};
use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};
use crate::primitives::cart_tracks::{
    paint_cart_tracks, OPEN_E, OPEN_N, OPEN_S, OPEN_W,
};
use crate::primitives::ore_deposit::paint_ore_deposit;

/// Tile size in pixel space — matches ``crate::primitives::CELL``.
/// Inlined here to avoid pulling in the full primitives module
/// boundary.
const CELL: f64 = 32.0;

/// Compute the 4-bit open-sides mask for each tile in `tiles`. Bit
/// `OPEN_N` is set when the tile's N neighbour is also in the set,
/// etc. Mirrors the v4 `_open_sides_for_tracks` helper that the
/// emitter used to fill `CartTracksVariant.open_sides[]`.
fn open_sides_for(tiles: &[(i32, i32)]) -> Vec<(i32, i32, u8)> {
    let set: HashSet<(i32, i32)> = tiles.iter().copied().collect();
    tiles
        .iter()
        .map(|&(x, y)| {
            let mut mask: u8 = 0;
            if set.contains(&(x, y - 1)) {
                mask |= OPEN_N;
            }
            if set.contains(&(x, y + 1)) {
                mask |= OPEN_S;
            }
            if set.contains(&(x + 1, y)) {
                mask |= OPEN_E;
            }
            if set.contains(&(x - 1, y)) {
                mask |= OPEN_W;
            }
            (x, y, mask)
        })
        .collect()
}

pub fn draw<'a>(
    op: PathOp<'a>,
    _regions: Vector<'a, ForwardsUOffset<Region<'a>>>,
    painter: &mut dyn Painter,
) -> bool {
    let tiles = match op.tiles() {
        Some(t) if !t.is_empty() => t,
        _ => return false,
    };
    let coords: Vec<(i32, i32)> = (0..tiles.len())
        .map(|i| {
            let t = tiles.get(i);
            (t.x(), t.y())
        })
        .collect();
    let seed = op.seed();
    match op.style() {
        PathStyle::CartTracks => {
            let with_mask = open_sides_for(&coords);
            paint_cart_tracks(painter, &with_mask, seed);
            true
        }
        PathStyle::OreVein => {
            paint_ore_deposit(painter, &coords, seed);
            true
        }
        PathStyle::RailLine => {
            let with_mask = open_sides_for(&coords);
            paint_rail_line(painter, &with_mask);
            true
        }
        PathStyle::Vines => {
            paint_vines(painter, &coords, seed);
            true
        }
        PathStyle::RootSystem => {
            paint_root_system(painter, &coords, seed);
            true
        }
        PathStyle::RiverBed => {
            paint_river_bed(painter, &coords, seed);
            true
        }
        PathStyle::LavaSeam => {
            paint_lava_seam(painter, &coords, seed);
            true
        }
        _ => false,
    }
}

// ── Post-Phase-5 deferred-polish PathStyle painters ────────────

const PATH_GROUP_OPACITY: f32 = 0.85;

/// RailLine — single clean steel rail. Per tile, draws a short
/// stroke segment through the tile centre along the local
/// connectivity direction (derived from the open-sides mask).
/// Cleaner / lighter than ``CartTracks``: one rail line, no
/// ties, no double-rail weight.
fn paint_rail_line(
    painter: &mut dyn Painter,
    tiles_with_mask: &[(i32, i32, u8)],
) {
    const RAIL_INK: Color = Color::rgba(0x55, 0x55, 0x55, 1.0);
    let stroke = Stroke {
        width: 1.4,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let paint = Paint::solid(RAIL_INK);
    painter.begin_group(PATH_GROUP_OPACITY);
    for &(x, y, mask) in tiles_with_mask {
        let cx = x as f64 * CELL + CELL * 0.5;
        let cy = y as f64 * CELL + CELL * 0.5;
        let half = CELL * 0.55;
        // Walk each open side and stroke a half-segment from the
        // tile centre toward that side. Disconnected tiles get a
        // single short horizontal rail nub so isolated stamps
        // still read as ``rail-ish``.
        let mut emitted = false;
        for (bit, dx, dy) in [
            (OPEN_N, 0.0_f64, -half),
            (OPEN_S, 0.0, half),
            (OPEN_E, half, 0.0),
            (OPEN_W, -half, 0.0),
        ] {
            if mask & bit == 0 {
                continue;
            }
            let mut path = PathOps::new();
            path.move_to(Vec2::new(cx as f32, cy as f32));
            path.line_to(Vec2::new(
                (cx + dx) as f32, (cy + dy) as f32,
            ));
            painter.stroke_path(&path, &paint, &stroke);
            emitted = true;
        }
        if !emitted {
            let mut path = PathOps::new();
            path.move_to(Vec2::new(
                (cx - CELL * 0.30) as f32, cy as f32,
            ));
            path.line_to(Vec2::new(
                (cx + CELL * 0.30) as f32, cy as f32,
            ));
            painter.stroke_path(&path, &paint, &stroke);
        }
    }
    painter.end_group();
}

/// Vines — sinuous green tendrils per tile. Stamps a wavy
/// quadratic spline through each tile centre with a small
/// per-tile RNG-driven amplitude jitter.
fn paint_vines(
    painter: &mut dyn Painter,
    coords: &[(i32, i32)],
    seed: u64,
) {
    const VINE_INK: Color = Color::rgba(0x35, 0x6E, 0x2A, 1.0);
    const VINE_SEED_SALT: u64 = 0x_71_E5_C0FF_EE00_0001;
    let stroke = Stroke {
        width: 0.9,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let paint = Paint::solid(VINE_INK);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ VINE_SEED_SALT);
    painter.begin_group(PATH_GROUP_OPACITY);
    for &(x, y) in coords {
        let px = x as f64 * CELL;
        let py = y as f64 * CELL;
        let amp = rng.gen_range((CELL * 0.10)..(CELL * 0.18));
        let phase: f64 = rng.gen_range(0.0..(2.0 * PI));
        // Two-control-point quadratic curve: enter on the left
        // edge, dip / arch around the centre, exit on the right.
        let entry = Vec2::new(px as f32, (py + CELL * 0.5) as f32);
        let mid_ctrl = Vec2::new(
            (px + CELL * 0.5) as f32,
            (py + CELL * 0.5 + phase.sin() * amp) as f32,
        );
        let exit = Vec2::new(
            (px + CELL) as f32, (py + CELL * 0.5) as f32,
        );
        let mut path = PathOps::new();
        path.move_to(entry);
        path.quad_to(mid_ctrl, exit);
        painter.stroke_path(&path, &paint, &stroke);
    }
    painter.end_group();
}

/// RootSystem — branching brown root segments per tile. Draws
/// 3-4 short stroke fragments from the tile centre toward random
/// outward directions; reads as a network of root threads
/// spreading through the substrate.
fn paint_root_system(
    painter: &mut dyn Painter,
    coords: &[(i32, i32)],
    seed: u64,
) {
    const ROOT_INK: Color = Color::rgba(0x55, 0x3A, 0x22, 1.0);
    const ROOT_SEED_SALT: u64 = 0x_7007_C0FF_EE00_0001;
    let stroke = Stroke {
        width: 0.8,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let paint = Paint::solid(ROOT_INK);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ ROOT_SEED_SALT);
    painter.begin_group(PATH_GROUP_OPACITY);
    for &(x, y) in coords {
        let cx = x as f64 * CELL + CELL * 0.5;
        let cy = y as f64 * CELL + CELL * 0.5;
        let n_branches = rng.gen_range(3..=4);
        for _ in 0..n_branches {
            let theta: f64 = rng.gen_range(0.0..(2.0 * PI));
            let len = rng.gen_range((CELL * 0.20)..(CELL * 0.40));
            let ex = cx + theta.cos() * len;
            let ey = cy + theta.sin() * len;
            let mut path = PathOps::new();
            path.move_to(Vec2::new(cx as f32, cy as f32));
            path.line_to(Vec2::new(ex as f32, ey as f32));
            painter.stroke_path(&path, &paint, &stroke);
        }
    }
    painter.end_group();
}

/// RiverBed — flowing-water channel. Per tile, fills the tile
/// with a translucent blue substrate plus a thin lighter ripple
/// stroke through the tile centre. Reads as a contiguous water
/// channel where the path tiles connect.
fn paint_river_bed(
    painter: &mut dyn Painter,
    coords: &[(i32, i32)],
    seed: u64,
) {
    const RIVER_BASE: Color = Color::rgba(0x4A, 0x78, 0x98, 1.0);
    const RIVER_RIPPLE: Color = Color::rgba(0xA0, 0xC0, 0xD8, 1.0);
    const RIVER_SEED_SALT: u64 = 0x_71_C5_E2_FF_EE00_0001;
    let ripple_stroke = Stroke {
        width: 0.6,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let base_paint = Paint::solid(RIVER_BASE);
    let ripple_paint = Paint::solid(RIVER_RIPPLE);
    let mut rng = Pcg64Mcg::seed_from_u64(seed ^ RIVER_SEED_SALT);
    painter.begin_group(PATH_GROUP_OPACITY);
    for &(x, y) in coords {
        let px = x as f64 * CELL;
        let py = y as f64 * CELL;
        // Tile-fill the substrate.
        let mut path = PathOps::new();
        path.move_to(Vec2::new(px as f32, py as f32));
        path.line_to(Vec2::new((px + CELL) as f32, py as f32));
        path.line_to(Vec2::new((px + CELL) as f32, (py + CELL) as f32));
        path.line_to(Vec2::new(px as f32, (py + CELL) as f32));
        path.close();
        painter.fill_path(&path, &base_paint, FillRule::Winding);
        // One ripple line per tile — small phase jitter so the
        // overall surface doesn't look like a uniform grid.
        let phase: f64 = rng.gen_range(0.0..PI);
        let mut ripple = PathOps::new();
        ripple.move_to(Vec2::new(
            px as f32, (py + CELL * 0.5 + phase.cos() * CELL * 0.08) as f32,
        ));
        ripple.line_to(Vec2::new(
            (px + CELL) as f32,
            (py + CELL * 0.5 + (phase + PI * 0.5).cos() * CELL * 0.08) as f32,
        ));
        painter.stroke_path(&ripple, &ripple_paint, &ripple_stroke);
    }
    painter.end_group();
}

/// LavaSeam — glowing molten crack. Per tile, fills a narrow
/// path centre-line with bright orange and rims it with a
/// deeper red glow stroke. RNG-free per-tile orientation jitter
/// is intentionally absent — the seam reads as a contiguous
/// crack network when the tiles connect.
fn paint_lava_seam(
    painter: &mut dyn Painter,
    coords: &[(i32, i32)],
    _seed: u64,
) {
    const LAVA_CORE: Color = Color::rgba(0xFF, 0xC8, 0x40, 1.0);
    const LAVA_GLOW: Color = Color::rgba(0xC8, 0x50, 0x20, 1.0);
    let core_stroke = Stroke {
        width: 1.6,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let glow_stroke = Stroke {
        width: 3.4,
        line_cap: LineCap::Round,
        line_join: LineJoin::Round,
    };
    let core_paint = Paint::solid(LAVA_CORE);
    let glow_paint = Paint::solid(LAVA_GLOW);
    painter.begin_group(PATH_GROUP_OPACITY);
    for &(x, y) in coords {
        let cx = x as f64 * CELL + CELL * 0.5;
        let cy = y as f64 * CELL + CELL * 0.5;
        let half = CELL * 0.45;
        let mut path = PathOps::new();
        path.move_to(Vec2::new((cx - half) as f32, cy as f32));
        path.line_to(Vec2::new((cx + half) as f32, cy as f32));
        // Wide deep-red glow stroked first; bright core overlaid
        // so the center reads as the molten line and the glow
        // halos either side.
        painter.stroke_path(&path, &glow_paint, &glow_stroke);
        painter.stroke_path(&path, &core_paint, &core_stroke);
    }
    painter.end_group();
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{
        finish_floor_ir_buffer, root_as_floor_ir, FloorIR, FloorIRArgs,
        TileCoord, OpEntry, OpEntryArgs, Op,
        PathOp as FbPathOp, PathOpArgs, PathStyle, Region as FbRegion,
    };
    use crate::painter::test_util::{MockPainter, PainterCall};

    fn build_path_op(style: PathStyle, tiles: &[(i32, i32)]) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let tiles_vec: Vec<TileCoord> = tiles
            .iter()
            .map(|&(x, y)| TileCoord::new(x, y))
            .collect();
        let tiles_offset = fbb.create_vector(&tiles_vec);
        let region_ref = fbb.create_string("corridor.0");
        let path_op = FbPathOp::create(
            &mut fbb,
            &PathOpArgs {
                region_ref: Some(region_ref),
                tiles: Some(tiles_offset),
                style,
                seed: 0xFACE,
            },
        );
        let op_entry = OpEntry::create(
            &mut fbb,
            &OpEntryArgs {
                op_type: Op::PathOp,
                op: Some(path_op.as_union_value()),
            },
        );
        let v5_ops = fbb.create_vector(&[op_entry]);
        let v5_regions = fbb
            .create_vector::<flatbuffers::ForwardsUOffset<FbRegion>>(&[]);
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 4,
                minor: 0,
                width_tiles: 16,
                height_tiles: 16,
                cell: 32,
                padding: 32,
                regions: Some(v5_regions),
                ops: Some(v5_ops),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    fn run_draw(buf: &[u8]) -> MockPainter {
        let fir = root_as_floor_ir(buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_path_op()
            .expect("path op");
        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(painted);
        painter
    }

    /// Three connected tiles `(0,5)-(1,5)-(2,5)` form a horizontal
    /// straight track segment. Cart-tracks paints rail strokes (in a
    /// group envelope) and tie strokes (in another group envelope).
    /// Pin that the lifted painter ran by asserting at least one
    /// `BeginGroup` + `StrokePolyline` + `EndGroup` triple.
    #[test]
    fn draw_runs_cart_tracks_painter_for_connected_tiles() {
        let tiles = [(0, 5), (1, 5), (2, 5)];
        let buf = build_path_op(PathStyle::CartTracks, &tiles);
        let painter = run_draw(&buf);
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::BeginGroup(_))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::StrokePolyline(_, _, _))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::EndGroup)));
    }

    /// OreVein paints diamonds (fill_path + stroke_path per diamond)
    /// inside one `BeginGroup` envelope. Pin that the lifted painter
    /// ran by checking for `FillPath` + `StrokePath` calls inside
    /// the group envelope.
    #[test]
    fn draw_runs_ore_vein_painter_for_tile_set() {
        let tiles = [(2, 4), (3, 4), (4, 4), (4, 5)];
        let buf = build_path_op(PathStyle::OreVein, &tiles);
        let painter = run_draw(&buf);
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::BeginGroup(_))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::FillPath(_, _, _))));
        assert!(painter.calls.iter().any(|c| matches!(c, PainterCall::StrokePath(_, _, _))));
    }

    /// open_sides_for derives the 4-bit neighbour mask correctly
    /// from an unordered tile set. A 3-tile horizontal run `(0,5)-
    /// (1,5)-(2,5)` produces masks: left tile open-E only, middle
    /// open-E|W, right open-W only.
    #[test]
    fn open_sides_for_derives_neighbour_mask_from_tile_set() {
        let tiles = vec![(0, 5), (1, 5), (2, 5)];
        let with_mask = open_sides_for(&tiles);
        let lookup: std::collections::HashMap<(i32, i32), u8> = with_mask
            .iter()
            .map(|&(x, y, m)| ((x, y), m))
            .collect();
        assert_eq!(lookup[&(0, 5)], OPEN_E);
        assert_eq!(lookup[&(1, 5)], OPEN_E | OPEN_W);
        assert_eq!(lookup[&(2, 5)], OPEN_W);
    }

    /// Every post-Phase-5 PathStyle dispatches successfully on a
    /// non-trivial tile list and emits at least one paint call
    /// inside a balanced ``begin_group`` / ``end_group`` envelope.
    /// Pin the dispatch shape so a future enum addition that
    /// forgets to add a match arm surfaces here as a panic /
    /// failure.
    #[test]
    fn deferred_path_styles_dispatch_to_their_painters() {
        let tiles = [(2, 4), (3, 4), (4, 4), (4, 5)];
        for style in [
            PathStyle::RailLine, PathStyle::Vines,
            PathStyle::RootSystem, PathStyle::RiverBed,
            PathStyle::LavaSeam,
        ] {
            let buf = build_path_op(style, &tiles);
            let painter = run_draw(&buf);
            let begins = painter
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::BeginGroup(_)))
                .count();
            let ends = painter
                .calls
                .iter()
                .filter(|c| matches!(c, PainterCall::EndGroup))
                .count();
            assert!(
                begins >= 1,
                "{style:?}: expected at least one begin_group",
            );
            assert_eq!(
                begins, ends,
                "{style:?}: begin_group / end_group balance",
            );
            // Every new painter touches the painter at least once
            // beyond the envelope.
            assert!(
                painter.calls.len() > begins + ends,
                "{style:?}: expected paint calls inside the envelope",
            );
        }
    }

    /// LavaSeam emits two stroke widths per tile (wide deep-red
    /// glow + narrow bright core); pin the two-stroke-per-tile
    /// shape so a future tweak to the glow / core split surfaces
    /// here.
    #[test]
    fn lava_seam_emits_glow_plus_core_stroke_pair_per_tile() {
        let tiles = [(0, 0), (1, 0), (2, 0)];
        let buf = build_path_op(PathStyle::LavaSeam, &tiles);
        let painter = run_draw(&buf);
        let strokes = painter
            .calls
            .iter()
            .filter(|c| matches!(c, PainterCall::StrokePath(_, _, _)))
            .count();
        // 3 tiles × 2 strokes (glow + core) = 6.
        assert_eq!(strokes, 6, "lava seam should emit 2 strokes per tile");
    }

    #[test]
    fn draw_skips_empty_tile_list() {
        let buf = build_path_op(PathStyle::CartTracks, &[]);
        let fir = root_as_floor_ir(&buf).expect("parse");
        let regions = fir.regions().expect("v5_regions");
        let op = fir
            .ops()
            .expect("v5_ops")
            .get(0)
            .op_as_path_op()
            .expect("path op");

        let mut painter = MockPainter::default();
        let painted = draw(op, regions, &mut painter);
        assert!(!painted);
        assert!(painter.calls.is_empty());
    }
}
