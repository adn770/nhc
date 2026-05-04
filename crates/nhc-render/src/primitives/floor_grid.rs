//! Floor-grid primitive — Phase 3 canary.
//!
//! Reproduces `nhc/rendering/_floor_detail.py:_render_floor_grid`
//! + `_svg_helpers.py:_wobbly_grid_seg` byte-for-byte. The Python
//! handler at `nhc/rendering/ir_to_svg.py:_draw_floor_grid_from_ir`
//! calls into this module via the PyO3 shim and wraps the returned
//! `d=` strings in `<path>` elements + the dungeon-interior clip
//! envelope.
//!
//! Determinism contract:
//!
//! - RNG is a fresh `PyRandom` seeded from `seed` (the legacy
//!   `random.Random(41)` — the fixed-41 seed is one of the
//!   documented code/design discrepancies in
//!   `design/ir_primitives.md`; Phase 1 honours the legacy
//!   behaviour and Phase 4 cleanup may promote to a derived
//!   seed once a major schema bump lands).
//! - Per-edge: 1 `randint(1, 4)` + 1 `random()` (only when
//!   `i == gap_pos`) — drift here biases the gap distribution.
//! - Perlin: `pnoise2(noise_x + t*0.5, noise_y, base)` with
//!   `base=20` for right edges and `base=24` for bottom edges.
//!   The legacy code computes a `base+4` companion sample that's
//!   then overwritten by both branches; Perlin is pure so the
//!   discarded sample is omitted here without affecting output.
//! - Coordinate strings use `{:.1}` — Rust and Python both
//!   round-half-to-even on f64, so the formatted strings match
//!   bit-for-bit on the inputs the rendering pipeline produces.
//!
//! Phase 2.19 retired the legacy `draw_floor_grid` SVG-string
//! emitter; the only remaining surface is the Painter-friendly
//! `paint_floor_grid_paths`, used by both `transform/png` (via
//! `SkiaPainter`) and `transform/svg` (via `SvgPainter`).

use crate::painter::{PathOps, Vec2};
use crate::perlin::pnoise2;
use crate::python_random::PyRandom;

const CELL: f64 = 32.0;
const WOBBLE: f64 = CELL * 0.05;
const N_SUB: i32 = 5;

/// One wobbly grid segment's polyline vertices, with optional
/// pen-lift gap encoded as a `None` separator. Mirrors
/// `_wobbly_grid_seg` in the Python helpers — the per-tile right
/// and bottom edges feed through here.
///
/// Returns a flat list of sub-segment runs: each run is a
/// contiguous sequence of points. A pen-lift gap (RNG-triggered
/// at `i == gap_pos` with `random() < 0.25`) starts a new run
/// after the gap. Both the SVG-string emitter and the PathOps
/// emitter consume this vertex shape — the SVG emitter formats
/// each run as `M x,y L x,y …` and the PathOps emitter walks
/// each run as `MoveTo, LineTo, …`.
fn wobbly_grid_seg_vertices(
    rng: &mut PyRandom,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    noise_x: f64,
    noise_y: f64,
    base: i32,
) -> Vec<Vec<(f64, f64)>> {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let mut pts: Vec<(f64, f64)> = Vec::with_capacity((N_SUB + 1) as usize);
    for i in 0..=N_SUB {
        let t = i as f64 / N_SUB as f64;
        let (lx, ly) = if dx.abs() > dy.abs() {
            // Mostly horizontal — wobble Y only.
            (
                x0 + dx * t,
                y0 + dy * t
                    + pnoise2(noise_x + t * 0.5, noise_y, base) * WOBBLE,
            )
        } else {
            // Mostly vertical — wobble X only.
            (
                x0 + dx * t
                    + pnoise2(noise_x + t * 0.5, noise_y, base) * WOBBLE,
                y0 + dy * t,
            )
        };
        pts.push((lx, ly));
    }
    let gap_pos = rng.randint(1, (N_SUB - 1) as i64) as usize;
    let mut runs: Vec<Vec<(f64, f64)>> = Vec::new();
    let mut current: Vec<(f64, f64)> = vec![pts[0]];
    for i in 1..pts.len() {
        // Python's `i == gap_pos and rng.random() < 0.25` short-
        // circuits — `rng.random()` only fires on the matching
        // sub-segment. Reproduce the same RNG consumption pattern
        // here or the parity gate fails on the very first floor.
        if i == gap_pos && rng.random() < 0.25 {
            // Pen-lift gap: close current run and start a new one
            // at the gap point.
            runs.push(std::mem::take(&mut current));
            current.push(pts[i]);
        } else {
            current.push(pts[i]);
        }
    }
    if !current.is_empty() {
        runs.push(current);
    }
    runs
}

/// Append a single wobbly segment's vertex runs to `path` as
/// `MoveTo, LineTo, LineTo, …` ops. Each new run starts with a
/// fresh `MoveTo`; no `Close` is emitted (the wobbly grid is
/// open polylines).
///
/// Coords round-trip through `format!("{:.1}", v).parse()` to
/// mirror the legacy SVG-string path's precision contract: the
/// SVG `d=` strings emit `{:.1}` truncated coords, then
/// `transform/png/path_parser.rs::parse_path_d` reparses them.
/// Without the round-trip, the new PathOps path lands at full
/// f32 precision, drifting tiny-skia anti-aliased pixels by
/// ~0-1 units along grid edges (visible at the byte-equal fixture
/// reference compare even though PSNR ≥ 35 holds).
fn append_seg_pathops(path: &mut PathOps, runs: &[Vec<(f64, f64)>]) {
    for run in runs {
        if run.is_empty() {
            continue;
        }
        let (x0, y0) = run[0];
        path.move_to(Vec2::new(round_legacy(x0), round_legacy(y0)));
        for &(x, y) in &run[1..] {
            path.line_to(Vec2::new(round_legacy(x), round_legacy(y)));
        }
    }
}

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`.
fn round_legacy(v: f64) -> f32 {
    let s = format!("{:.1}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

/// Layer-level driver. Walks pre-classified tiles in the IR's
/// y-major iteration order, emits per-tile right + bottom edges,
/// and routes each segment to the room or corridor bucket from
/// the tile's `is_corridor` flag.
///
/// Each `PathOps` walks the per-segment vertex list as
/// `MoveTo, LineTo, LineTo, …` and starts the next segment with
/// another `MoveTo`. No `Close` is emitted — the wobbly grid is
/// a collection of open polylines.
pub fn paint_floor_grid_paths(
    width_tiles: i32,
    height_tiles: i32,
    tiles: &[(i32, i32, bool)],
    seed: u64,
) -> (PathOps, PathOps) {
    let mut rng = PyRandom::from_seed(seed);
    let mut room_paths = PathOps::new();
    let mut corridor_paths = PathOps::new();
    for &(x, y, is_corridor) in tiles {
        let px = x as f64 * CELL;
        let py = y as f64 * CELL;

        // Right edge.
        if x + 1 < width_tiles {
            let runs = wobbly_grid_seg_vertices(
                &mut rng,
                px + CELL,
                py,
                px + CELL,
                py + CELL,
                x as f64 * 0.7,
                y as f64 * 0.7,
                20,
            );
            if is_corridor {
                append_seg_pathops(&mut corridor_paths, &runs);
            } else {
                append_seg_pathops(&mut room_paths, &runs);
            }
        }

        // Bottom edge.
        if y + 1 < height_tiles {
            let runs = wobbly_grid_seg_vertices(
                &mut rng,
                px,
                py + CELL,
                px + CELL,
                py + CELL,
                x as f64 * 0.3,
                y as f64 * 0.7,
                24,
            );
            if is_corridor {
                append_seg_pathops(&mut corridor_paths, &runs);
            } else {
                append_seg_pathops(&mut room_paths, &runs);
            }
        }
    }
    (room_paths, corridor_paths)
}

#[cfg(test)]
mod tests {
    use super::paint_floor_grid_paths;
    use crate::painter::PathOp;

    /// Empty tile list → both PathOps empty.
    #[test]
    fn paint_floor_grid_empty_tiles_returns_empty_paths() {
        let (room, corridor) = paint_floor_grid_paths(0, 0, &[], 41);
        assert!(room.is_empty(), "room PathOps should be empty");
        assert!(corridor.is_empty(), "corridor PathOps should be empty");
    }

    /// One non-corridor tile @ (1,1) in a 5×5 floor → the right
    /// + bottom edges fall inside the floor (x+1=2 < 5 and
    /// y+1=2 < 5), so room PathOps gets at least one MoveTo plus
    /// multiple LineTos; corridor PathOps stays empty.
    #[test]
    fn paint_floor_grid_room_tile_populates_room_path() {
        let tiles = [(1, 1, false)];
        let (room, corridor) = paint_floor_grid_paths(5, 5, &tiles, 41);
        assert!(corridor.is_empty(), "corridor PathOps should be empty");

        let move_count = room
            .ops
            .iter()
            .filter(|op| matches!(op, PathOp::MoveTo(_)))
            .count();
        let line_count = room
            .ops
            .iter()
            .filter(|op| matches!(op, PathOp::LineTo(_)))
            .count();
        assert!(
            move_count >= 1,
            "room path needs at least one MoveTo, got {move_count}"
        );
        assert!(
            line_count > 1,
            "room path needs multiple LineTos, got {line_count}"
        );
        // No Close ops — wobbly grid is open polylines.
        assert!(
            room.ops.iter().all(|op| !matches!(op, PathOp::Close)),
            "wobbly grid must not emit Close ops"
        );
    }

    /// One corridor tile @ (1,1) in a 5×5 floor → corridor
    /// PathOps populated, room PathOps empty.
    #[test]
    fn paint_floor_grid_corridor_tile_populates_corridor_path() {
        let tiles = [(1, 1, true)];
        let (room, corridor) = paint_floor_grid_paths(5, 5, &tiles, 41);
        assert!(room.is_empty(), "room PathOps should be empty");
        assert!(
            !corridor.is_empty(),
            "corridor PathOps should be populated"
        );
    }

    /// Bucket routing: a mixed fixture must populate both buckets
    /// — non-corridor tiles in `room_paths`, corridor tiles in
    /// `corridor_paths`.
    #[test]
    fn paint_floor_grid_routes_mixed_tiles_to_correct_bucket() {
        let tiles = [
            (0, 0, false),
            (1, 0, false),
            (0, 1, false),
            (1, 1, true),
            (2, 1, true),
        ];
        let (room_paths, corridor_paths) =
            paint_floor_grid_paths(5, 5, &tiles, 41);
        assert!(!room_paths.is_empty());
        assert!(!corridor_paths.is_empty());
    }
}
