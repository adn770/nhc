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

use crate::perlin::pnoise2;
use crate::python_random::PyRandom;

const CELL: f64 = 32.0;
const WOBBLE: f64 = CELL * 0.05;
const N_SUB: i32 = 5;

/// One wobbly grid segment with optional pen-lift gap. Mirrors
/// `_wobbly_grid_seg` in the Python helpers — the per-tile right
/// and bottom edges feed through here.
fn wobbly_grid_seg(
    rng: &mut PyRandom,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    noise_x: f64,
    noise_y: f64,
    base: i32,
) -> String {
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
    let mut seg = format!("M{:.1},{:.1}", pts[0].0, pts[0].1);
    for i in 1..pts.len() {
        // Python's `i == gap_pos and rng.random() < 0.25` short-
        // circuits — `rng.random()` only fires on the matching
        // sub-segment. Reproduce the same RNG consumption pattern
        // here or the parity gate fails on the very first floor.
        if i == gap_pos && rng.random() < 0.25 {
            seg.push_str(&format!(" M{:.1},{:.1}", pts[i].0, pts[i].1));
        } else {
            seg.push_str(&format!(" L{:.1},{:.1}", pts[i].0, pts[i].1));
        }
    }
    seg
}

/// Layer-level driver. Walks pre-classified tiles in the IR's
/// y-major iteration order, emits per-tile right + bottom edges,
/// and routes each segment to the room or corridor bucket from
/// the tile's `is_corridor` flag.
///
/// Returns `(room_d, corridor_d)` — joined `d=` attribute strings
/// ready to splice into the layer's `<path>` elements. Empty
/// buckets return empty strings; the Python caller decides
/// whether to emit anything based on emptiness.
pub fn draw_floor_grid(
    width_tiles: i32,
    height_tiles: i32,
    tiles: &[(i32, i32, bool)],
    seed: u64,
) -> (String, String) {
    let mut rng = PyRandom::from_seed(seed);
    let mut room_segments: Vec<String> = Vec::new();
    let mut corridor_segments: Vec<String> = Vec::new();
    for &(x, y, is_corridor) in tiles {
        let px = x as f64 * CELL;
        let py = y as f64 * CELL;

        // Right edge.
        if x + 1 < width_tiles {
            let seg = wobbly_grid_seg(
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
                corridor_segments.push(seg);
            } else {
                room_segments.push(seg);
            }
        }

        // Bottom edge.
        if y + 1 < height_tiles {
            let seg = wobbly_grid_seg(
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
                corridor_segments.push(seg);
            } else {
                room_segments.push(seg);
            }
        }
    }
    (room_segments.join(" "), corridor_segments.join(" "))
}

#[cfg(test)]
mod tests {
    use super::draw_floor_grid;

    /// Empty tile list returns empty buckets — sanity check that
    /// the layer-level driver doesn't panic on a no-op call.
    #[test]
    fn empty_tiles_returns_empty_buckets() {
        let (room, corridor) = draw_floor_grid(0, 0, &[], 41);
        assert!(room.is_empty());
        assert!(corridor.is_empty());
    }

    /// Smoke test: a single non-corridor tile in a 2×2 grid
    /// produces a non-empty room bucket and an empty corridor
    /// bucket. The exact byte-equal contract is enforced by the
    /// Python parity gate; this test just locks down the bucket
    /// routing.
    #[test]
    fn single_room_tile_routes_to_room_bucket() {
        let tiles = [(0, 0, false)];
        let (room, corridor) = draw_floor_grid(2, 2, &tiles, 41);
        assert!(!room.is_empty(), "room bucket should be populated");
        assert!(corridor.is_empty(), "corridor bucket should be empty");
        assert!(
            room.starts_with('M'),
            "room d= should start with a move-to: {room:?}"
        );
    }

    /// A single corridor tile routes to the corridor bucket; the
    /// room bucket stays empty. Symmetric to the previous test.
    #[test]
    fn single_corridor_tile_routes_to_corridor_bucket() {
        let tiles = [(0, 0, true)];
        let (room, corridor) = draw_floor_grid(2, 2, &tiles, 41);
        assert!(room.is_empty(), "room bucket should be empty");
        assert!(
            !corridor.is_empty(),
            "corridor bucket should be populated"
        );
    }
}
