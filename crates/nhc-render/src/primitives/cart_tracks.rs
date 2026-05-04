//! Cart-tracks decorator — Phase 4, sub-step 11 (plan §8 Q2),
//! ported to the Painter trait in Phase 2.13f of
//! `plans/nhc_pure_ir_plan.md` (the **sixth decorator port**;
//! ore_deposit follows as 2.13g).
//!
//! Reproduces ``CART_TRACK_RAILS`` (two parallel rails per
//! TRACK tile) and ``CART_TRACK_TIES`` (single cross-tie per
//! TRACK tile) from ``nhc/rendering/_floor_detail.py``. Both
//! decorators share the same predicate; orientation per tile
//! comes from the IR's pre-resolved
//! ``CartTracksVariant.open_sides[]`` parallel array — a 4-bit
//! mask of TRACK-tile neighbours (bit 0 = N, 1 = S, 2 = E,
//! 3 = W). The emitter resolves the neighbour walk so the
//! consumer doesn't need level access.
//!
//! Commit 2 of the cart-track topology refactor renames the
//! IR field from ``is_horizontal`` (bool) to ``open_sides``
//! (u8 bitmask) but keeps the painter's tile-local rendering
//! unchanged: ``horizontal`` is derived from
//! ``mask & (OPEN_E | OPEN_W) != 0``. Commit 3 lifts the
//! tile-local stamp into a topology dispatch (straight, corner,
//! T-junction, cross, dead-end).
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. RNG-free painters
//! (geometry is fully determined by tile + orientation), so the
//! Painter and SVG paths emit identical stamp counts without
//! needing lock-step RNG.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_cart_tracks` SVG-string emitter (used by
//!   the FFI / `nhc/rendering/ir_to_svg.py` Python path until
//!   2.17 ships the `SvgPainter`-based PyO3 export and 2.19
//!   retires the Python `ir_to_svg` path).
//! - The new `paint_cart_tracks` Painter-based emitter (used by
//!   the Rust `transform/png` path via `SkiaPainter` and, after
//!   2.17, by the Rust `ir_to_svg` path via `SvgPainter`).
//!
//! Both paths share the private `cart_tracks_shapes` shape-stream
//! generator. RNG-free, so consumption order doesn't carry a
//! lock-step contract — but keeping the single source of truth
//! mirrors the pattern from cobblestone / brick / flagstone /
//! opus_romano / field_stone.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps its output in TWO sibling groups:
//! `<g id="cart-tracks" opacity="0.55">` for rails and
//! `<g id="cart-track-ties" opacity="0.5">` for ties. The pre-
//! 2.13f PNG handler dispatched to `paint_fragments`, which
//! routed each `<g opacity>` envelope through
//! `paint_offscreen_group` (Phase 5.10's offscreen-buffer
//! composite). The Painter port replaces the SVG-string round-
//! trip with two native `begin_group(opacity) / end_group()`
//! pairs (one per bucket) so the Painter trait owns the
//! offscreen-buffer mechanism end-to-end. PNG output should be
//! pixel-equal with the pre-port PNG references — only the
//! intermediate SVG-string emission disappears.

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, Stroke, Vec2,
};

const CELL: f64 = 32.0;
const TRACK_RAIL: &str = "#6A5A4A";
const TRACK_TIE: &str = "#8A7A5A";

/// Group-opacity envelope for the rails bucket. Lifts the
/// `<g id="cart-tracks" opacity="0.55">` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const RAIL_OPACITY: f32 = 0.55;
/// Group-opacity envelope for the ties bucket. Lifts the
/// `<g id="cart-track-ties" opacity="0.5">` wrapper from
/// `nhc/rendering/_floor_detail.py`.
pub const TIE_OPACITY: f32 = 0.5;

const RAIL_WIDTH: f32 = 0.9;
const TIE_WIDTH: f32 = 1.4;

/// Bit positions inside ``CartTracksVariant.open_sides[]``: bit
/// ``OPEN_N`` is set when the tile's N neighbour is also a
/// TRACK tile, etc. Mirrors the constants in
/// ``nhc/rendering/_floor_detail.py``.
pub const OPEN_N: u8 = 1 << 0;
pub const OPEN_S: u8 = 1 << 1;
pub const OPEN_E: u8 = 1 << 2;
pub const OPEN_W: u8 = 1 << 3;

/// Rail offsets from the perpendicular axis: the inner rail sits
/// at ``RAIL_INNER_FRAC`` of the cell, the outer at ``RAIL_OUTER_FRAC``.
/// Together they match the historical 0.35 / 0.65 placement.
const RAIL_INNER_FRAC: f64 = 0.35;
const RAIL_OUTER_FRAC: f64 = 0.65;

/// Quarter-arc tessellation: 8 segments produce a 9-vertex
/// polyline. Each segment is ~2-4 px at CELL = 32, plenty
/// smooth for the painter's round line-cap to round off.
const ARC_SEGMENTS: usize = 8;

/// Tie positions along a straight or arc-length axis. Three
/// evenly distributed ties (1/6, 3/6, 5/6) read as a proper
/// railroad — ~10-11 px between ties at CELL = 32.
const STRAIGHT_TIE_TS: [f64; 3] = [1.0 / 6.0, 3.0 / 6.0, 5.0 / 6.0];

/// Tie positions along a corner-arc parameter. Same ratios as
/// straight ties; the painter resolves these to an angle along
/// the arc and emits a radial tie line connecting the inner and
/// outer rails.
const CORNER_TIE_TS: [f64; 3] = [1.0 / 6.0, 3.0 / 6.0, 5.0 / 6.0];

/// Per-tile geometry record — backend-agnostic. Each topology
/// produces a variable-length list of rail polylines and tie
/// segments, dispatched from the per-tile open-sides bitmask.
///
/// Topologies (counted by ``mask.count_ones()``):
/// * 0 sides: isolated → empty (defensive — Phase 1 strips
///   sub-3-tile runs before TRACK tagging).
/// * 1 side: dead-end → 2 half-cell rails + 2 ties (midpoint +
///   terminus bumper).
/// * 2 opposite (N|S, E|W): straight → 2 full-cell rails + 3 ties.
/// * 2 perpendicular (corner): 2 concentric quarter-arc rails
///   centered at the cell corner where the open edges meet,
///   inner radius ``RAIL_INNER_FRAC * CELL``, outer
///   ``RAIL_OUTER_FRAC * CELL`` + 3 radial ties.
/// * 3 sides (T-junction): through-line straight (full + 3 ties)
///   on the opposite-pair axis + 2 half-cell branch stubs to the
///   third edge (no ties on the branch).
/// * 4 sides (cross): 2 full vertical rails crossing 2 full
///   horizontal rails. No ties (would clutter the intersection).
#[derive(Clone, Debug, Default, PartialEq)]
struct CartTrackShape {
    rails: Vec<Vec<Vec2>>,
    ties: Vec<[Vec2; 2]>,
}

/// Walk every tile once and resolve rail / tie geometry from
/// the open-sides bitmask. Each topology branches to its own
/// builder; the assembled ``CartTrackShape`` carries variable-
/// length rail polylines (straight = 2 verts, arc = 9 verts) and
/// tie segments (always 2 verts).
fn cart_tracks_shapes(tiles: &[(i32, i32, u8)]) -> Vec<CartTrackShape> {
    let mut out: Vec<CartTrackShape> = Vec::with_capacity(tiles.len());
    for &(x, y, mask) in tiles {
        let px = f64::from(x) * CELL;
        let py = f64::from(y) * CELL;
        out.push(shape_for_mask(px, py, mask));
    }
    out
}

fn shape_for_mask(px: f64, py: f64, mask: u8) -> CartTrackShape {
    let n = mask & OPEN_N != 0;
    let s = mask & OPEN_S != 0;
    let e = mask & OPEN_E != 0;
    let w = mask & OPEN_W != 0;
    let count = (n as u8) + (s as u8) + (e as u8) + (w as u8);
    match count {
        0 => CartTrackShape::default(),
        1 => dead_end_shape(px, py, n, s, e, w),
        2 => {
            if n && s {
                straight_vertical_shape(px, py)
            } else if e && w {
                straight_horizontal_shape(px, py)
            } else {
                corner_shape(px, py, n, s, e, w)
            }
        }
        3 => t_junction_shape(px, py, n, s, e, w),
        _ => cross_shape(px, py),
    }
}

// ── Straight glyphs ──────────────────────────────────────────

fn straight_horizontal_shape(px: f64, py: f64) -> CartTrackShape {
    let y_in = py + CELL * RAIL_INNER_FRAC;
    let y_out = py + CELL * RAIL_OUTER_FRAC;
    let mut shape = CartTrackShape {
        rails: vec![
            vec![pt(px, y_in), pt(px + CELL, y_in)],
            vec![pt(px, y_out), pt(px + CELL, y_out)],
        ],
        ties: Vec::with_capacity(STRAIGHT_TIE_TS.len()),
    };
    for &t in &STRAIGHT_TIE_TS {
        let x = px + CELL * t;
        shape.ties.push([
            pt(x, y_in - 1.0),
            pt(x, y_out + 1.0),
        ]);
    }
    shape
}

fn straight_vertical_shape(px: f64, py: f64) -> CartTrackShape {
    let x_in = px + CELL * RAIL_INNER_FRAC;
    let x_out = px + CELL * RAIL_OUTER_FRAC;
    let mut shape = CartTrackShape {
        rails: vec![
            vec![pt(x_in, py), pt(x_in, py + CELL)],
            vec![pt(x_out, py), pt(x_out, py + CELL)],
        ],
        ties: Vec::with_capacity(STRAIGHT_TIE_TS.len()),
    };
    for &t in &STRAIGHT_TIE_TS {
        let y = py + CELL * t;
        shape.ties.push([
            pt(x_in - 1.0, y),
            pt(x_out + 1.0, y),
        ]);
    }
    shape
}

// ── Corner glyph ─────────────────────────────────────────────

/// Quarter-arc corner. Center is at the cell corner where the
/// two open edges meet; rails are concentric quarter arcs at
/// inner / outer radii. Three radial ties at arc-parameter
/// positions ``CORNER_TIE_TS``.
fn corner_shape(
    px: f64, py: f64, n: bool, s: bool, e: bool, _w: bool,
) -> CartTrackShape {
    // Center of the arc is the cell corner where the two open
    // edges meet. e.g. N+E → NE corner = (px+CELL, py).
    let cx = if e { px + CELL } else { px };
    let cy = if n { py } else { py + CELL };
    // Sweep direction differs per quadrant. Resolve start / end
    // so the entry tangent is along the open edge that comes
    // first in (N, S, E, W) iteration.
    let (start_deg, end_deg) = match (n, s, e) {
        // N+E: arc from N edge (180° from NE corner) to E edge (90°).
        (true, false, true) => (180.0_f64, 90.0_f64),
        // N+W: arc from N edge (0° from NW corner) to W edge (90°).
        (true, false, false) => (0.0_f64, 90.0_f64),
        // S+E: arc from S edge (180° from SE corner) to E edge (270°).
        (false, true, true) => (180.0_f64, 270.0_f64),
        // S+W: arc from S edge (0° from SW corner) to W edge (-90°).
        (false, true, false) => (0.0_f64, -90.0_f64),
        _ => unreachable!("corner_shape called with non-corner mask"),
    };
    let inner_r = CELL * RAIL_INNER_FRAC;
    let outer_r = CELL * RAIL_OUTER_FRAC;
    let mut shape = CartTrackShape {
        rails: vec![
            arc_polyline(cx, cy, inner_r, start_deg, end_deg),
            arc_polyline(cx, cy, outer_r, start_deg, end_deg),
        ],
        ties: Vec::with_capacity(CORNER_TIE_TS.len()),
    };
    for &t in &CORNER_TIE_TS {
        let angle = (start_deg + (end_deg - start_deg) * t).to_radians();
        let cos_a = angle.cos();
        let sin_a = angle.sin();
        shape.ties.push([
            pt(cx + inner_r * cos_a, cy + inner_r * sin_a),
            pt(cx + outer_r * cos_a, cy + outer_r * sin_a),
        ]);
    }
    shape
}

fn arc_polyline(
    cx: f64, cy: f64, r: f64,
    start_deg: f64, end_deg: f64,
) -> Vec<Vec2> {
    let mut verts = Vec::with_capacity(ARC_SEGMENTS + 1);
    for i in 0..=ARC_SEGMENTS {
        let t = i as f64 / ARC_SEGMENTS as f64;
        let angle = (start_deg + (end_deg - start_deg) * t).to_radians();
        verts.push(pt(cx + r * angle.cos(), cy + r * angle.sin()));
    }
    verts
}

// ── T-junction glyph ─────────────────────────────────────────

/// T-junction: two opposite open sides form the through line
/// (full straight rails + 3 ties); the third side gets two
/// half-cell branch stubs from the cell center to the
/// perpendicular open edge. No ties on the branch stubs.
fn t_junction_shape(
    px: f64, py: f64, n: bool, s: bool, e: bool, w: bool,
) -> CartTrackShape {
    if n && s {
        // Through is N-S; branch is E or W (whichever is set).
        let mut shape = straight_vertical_shape(px, py);
        let cx = px + CELL / 2.0;
        let y_in = py + CELL * RAIL_INNER_FRAC;
        let y_out = py + CELL * RAIL_OUTER_FRAC;
        if e {
            // Branch from cell center to E edge.
            shape.rails.push(vec![pt(cx, y_in), pt(px + CELL, y_in)]);
            shape.rails.push(vec![pt(cx, y_out), pt(px + CELL, y_out)]);
        } else if w {
            shape.rails.push(vec![pt(px, y_in), pt(cx, y_in)]);
            shape.rails.push(vec![pt(px, y_out), pt(cx, y_out)]);
        }
        shape
    } else {
        // Through is E-W; branch is N or S.
        let mut shape = straight_horizontal_shape(px, py);
        let cy = py + CELL / 2.0;
        let x_in = px + CELL * RAIL_INNER_FRAC;
        let x_out = px + CELL * RAIL_OUTER_FRAC;
        if n {
            shape.rails.push(vec![pt(x_in, py), pt(x_in, cy)]);
            shape.rails.push(vec![pt(x_out, py), pt(x_out, cy)]);
        } else {
            // s
            shape.rails.push(vec![pt(x_in, cy), pt(x_in, py + CELL)]);
            shape.rails.push(vec![pt(x_out, cy), pt(x_out, py + CELL)]);
        }
        shape
    }
}

// ── Cross glyph ──────────────────────────────────────────────

/// Cross: two full vertical rails crossing two full horizontal
/// rails. No ties — the four crossing points are visually
/// unambiguous on their own.
fn cross_shape(px: f64, py: f64) -> CartTrackShape {
    let x_in = px + CELL * RAIL_INNER_FRAC;
    let x_out = px + CELL * RAIL_OUTER_FRAC;
    let y_in = py + CELL * RAIL_INNER_FRAC;
    let y_out = py + CELL * RAIL_OUTER_FRAC;
    CartTrackShape {
        rails: vec![
            vec![pt(x_in, py), pt(x_in, py + CELL)],
            vec![pt(x_out, py), pt(x_out, py + CELL)],
            vec![pt(px, y_in), pt(px + CELL, y_in)],
            vec![pt(px, y_out), pt(px + CELL, y_out)],
        ],
        ties: Vec::new(),
    }
}

// ── Dead-end glyph ───────────────────────────────────────────

/// Dead-end: two half-cell rails extending from the open edge to
/// the cell center. One tie at the rail midpoint plus a wider
/// "bumper" tie at the terminus marks the rail end.
fn dead_end_shape(
    px: f64, py: f64, n: bool, s: bool, e: bool, _w: bool,
) -> CartTrackShape {
    let cx = px + CELL / 2.0;
    let cy = py + CELL / 2.0;
    let in_pos = CELL * RAIL_INNER_FRAC;
    let out_pos = CELL * RAIL_OUTER_FRAC;
    if n {
        let x_in = px + in_pos;
        let x_out = px + out_pos;
        let mid_y = py + CELL * 0.25;
        CartTrackShape {
            rails: vec![
                vec![pt(x_in, py), pt(x_in, cy)],
                vec![pt(x_out, py), pt(x_out, cy)],
            ],
            ties: vec![
                [pt(x_in - 1.0, mid_y), pt(x_out + 1.0, mid_y)],
                [pt(x_in - 1.0, cy), pt(x_out + 1.0, cy)],
            ],
        }
    } else if s {
        let x_in = px + in_pos;
        let x_out = px + out_pos;
        let mid_y = py + CELL * 0.75;
        CartTrackShape {
            rails: vec![
                vec![pt(x_in, cy), pt(x_in, py + CELL)],
                vec![pt(x_out, cy), pt(x_out, py + CELL)],
            ],
            ties: vec![
                [pt(x_in - 1.0, mid_y), pt(x_out + 1.0, mid_y)],
                [pt(x_in - 1.0, cy), pt(x_out + 1.0, cy)],
            ],
        }
    } else if e {
        let y_in = py + in_pos;
        let y_out = py + out_pos;
        let mid_x = px + CELL * 0.75;
        CartTrackShape {
            rails: vec![
                vec![pt(cx, y_in), pt(px + CELL, y_in)],
                vec![pt(cx, y_out), pt(px + CELL, y_out)],
            ],
            ties: vec![
                [pt(mid_x, y_in - 1.0), pt(mid_x, y_out + 1.0)],
                [pt(cx, y_in - 1.0), pt(cx, y_out + 1.0)],
            ],
        }
    } else {
        // w
        let y_in = py + in_pos;
        let y_out = py + out_pos;
        let mid_x = px + CELL * 0.25;
        CartTrackShape {
            rails: vec![
                vec![pt(px, y_in), pt(cx, y_in)],
                vec![pt(px, y_out), pt(cx, y_out)],
            ],
            ties: vec![
                [pt(mid_x, y_in - 1.0), pt(mid_x, y_out + 1.0)],
                [pt(cx, y_in - 1.0), pt(cx, y_out + 1.0)],
            ],
        }
    }
}

// ── Vec2 helper ──────────────────────────────────────────────

fn pt(x: f64, y: f64) -> Vec2 {
    Vec2::new(round_legacy(x), round_legacy(y))
}
/// Painter-trait entry point — Phase 2.13f port.
///
/// Walks the same shape stream as `draw_cart_tracks` and dispatches
/// each tile's two rail lines plus one tie line through the Painter
/// trait. Two `begin_group` / `end_group` pairs wrap the buckets to
/// match the legacy SVG envelopes:
///
/// - Rails group at `RAIL_OPACITY` (0.55), `RAIL_WIDTH` (0.9).
/// - Ties group at `TIE_OPACITY` (0.5), `TIE_WIDTH` (1.4).
///
/// Both buckets use `LineCap::Round` to match the legacy
/// `stroke-linecap="round"`. PNG output stays pixel-equal with the
/// pre-port `paint_fragments` path — only the intermediate SVG-
/// string round-trip disappears.
pub fn paint_cart_tracks(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32, u8)],
    _seed: u64,
) {
    if tiles.is_empty() {
        return;
    }
    let shapes = cart_tracks_shapes(tiles);
    if shapes.is_empty() {
        return;
    }

    let rail_paint = paint_for_hex(TRACK_RAIL);
    let rail_stroke = Stroke {
        width: round_legacy(RAIL_WIDTH as f64),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    painter.begin_group(RAIL_OPACITY);
    for s in &shapes {
        for rail in &s.rails {
            if rail.len() >= 2 {
                painter.stroke_polyline(
                    rail,
                    &rail_paint,
                    &rail_stroke,
                );
            }
        }
    }
    painter.end_group();

    let tie_paint = paint_for_hex(TRACK_TIE);
    let tie_stroke = Stroke {
        width: round_legacy(TIE_WIDTH as f64),
        line_cap: LineCap::Round,
        line_join: LineJoin::Miter,
    };
    painter.begin_group(TIE_OPACITY);
    for s in &shapes {
        for tie in &s.ties {
            painter.stroke_polyline(
                tie,
                &tie_paint,
                &tie_stroke,
            );
        }
    }
    painter.end_group();
}

// ── Painter helpers ───────────────────────────────────────────

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`. Duplicated locally for the 10th
/// time (also lives in floor_grid / floor_detail / thematic_detail
/// / terrain_detail / cobblestone / brick / flagstone /
/// opus_romano / field_stone); a shared crate-level helper would
/// cut diff noise but bloat this commit, so leave it for a
/// follow-up.
fn round_legacy(v: f64) -> f32 {
    let s = format!("{:.1}", v);
    s.parse::<f64>().unwrap_or(v) as f32
}

fn parse_hex_rgb(s: &str) -> (u8, u8, u8) {
    s.strip_prefix('#')
        .filter(|t| t.len() == 6)
        .and_then(|t| {
            let r = u8::from_str_radix(&t[0..2], 16).ok()?;
            let g = u8::from_str_radix(&t[2..4], 16).ok()?;
            let b = u8::from_str_radix(&t[4..6], 16).ok()?;
            Some((r, g, b))
        })
        .unwrap_or((0, 0, 0))
}

fn paint_for_hex(hex: &str) -> Paint {
    let (r, g, b) = parse_hex_rgb(hex);
    Paint::solid(Color::rgb(r, g, b))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::painter::{
        FillRule, Paint, Painter, PathOps, Rect, Stroke, Vec2,
    };
    // ── Painter-path tests ─────────────────────────────────────

    /// Records every Painter call. Mirrors the trait-level
    /// `MockPainter` in `painter::tests` but lives in this module
    /// so the assertions stay close to the primitive.
    #[derive(Debug, Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
        group_depth: i32,
        max_group_depth: i32,
    }

    #[derive(Debug, Clone, PartialEq)]
    enum Call {
        StrokePolyline(usize, u32),
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {}
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint,
        ) {
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(
            &mut self,
            vertices: &[Vec2],
            _: &Paint,
            stroke: &Stroke,
        ) {
            self.calls.push(Call::StrokePolyline(
                vertices.len(),
                (stroke.width * 100.0).round() as u32,
            ));
        }
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {}
        fn stroke_path(&mut self, _: &PathOps, _: &Paint, _: &Stroke) {}
        fn begin_group(&mut self, opacity: f32) {
            self.group_depth += 1;
            if self.group_depth > self.max_group_depth {
                self.max_group_depth = self.group_depth;
            }
            self.calls.push(Call::BeginGroup(
                (opacity * 100.0).round() as u32,
            ));
        }
        fn end_group(&mut self) {
            self.group_depth -= 1;
            self.calls.push(Call::EndGroup);
        }
        fn push_clip(&mut self, _: &PathOps, _: FillRule) {}
        fn pop_clip(&mut self) {}
        fn push_transform(&mut self, _: crate::painter::Transform) {}
        fn pop_transform(&mut self) {}
    }

    impl CaptureCalls {
        fn polyline_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokePolyline(_, _)))
                .count()
        }
        fn begin_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
        fn end_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::EndGroup))
                .count()
        }
        fn opacities(&self) -> Vec<u32> {
            self.calls
                .iter()
                .filter_map(|c| match c {
                    Call::BeginGroup(op) => Some(*op),
                    _ => None,
                })
                .collect()
        }
        fn stroke_widths(&self) -> Vec<u32> {
            self.calls
                .iter()
                .filter_map(|c| match c {
                    Call::StrokePolyline(_, w) => Some(*w),
                    _ => None,
                })
                .collect()
        }
    }

    fn mixed_tiles(n: i32) -> Vec<(i32, i32, u8)> {
        // Alternate horizontal / vertical to exercise both branches.
        // Horizontal = open on E|W, vertical = open on N|S — the
        // tile-local renderer only checks the H/V-axis bits.
        (0..n)
            .flat_map(|y| {
                (0..n).map(move |x| {
                    let mask = if (x + y) % 2 == 0 {
                        OPEN_E | OPEN_W
                    } else {
                        OPEN_N | OPEN_S
                    };
                    (x, y, mask)
                })
            })
            .collect()
    }

    #[test]
    fn paint_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &[], 0);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// Two non-nested groups (rails + ties), balanced.
    #[test]
    fn paint_emits_two_balanced_groups() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &mixed_tiles(4), 0);
        let begins = painter.begin_group_count();
        let ends = painter.end_group_count();
        assert_eq!(begins, 2, "expected rails + ties groups");
        assert_eq!(begins, ends, "begin/end groups must balance");
        assert_eq!(painter.group_depth, 0);
        assert_eq!(painter.max_group_depth, 1, "groups never nest");
    }

    /// Documented bucket opacities — rails 0.55, ties 0.5 (in that
    /// order, since the legacy SVG emits rails before ties).
    #[test]
    fn paint_uses_documented_opacities() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &mixed_tiles(4), 0);
        let opacities = painter.opacities();
        assert_eq!(opacities.len(), 2);
        assert_eq!(
            opacities[0],
            (RAIL_OPACITY * 100.0).round() as u32,
            "rails group should be at {RAIL_OPACITY}",
        );
        assert_eq!(
            opacities[1],
            (TIE_OPACITY * 100.0).round() as u32,
            "ties group should be at {TIE_OPACITY}",
        );
    }

    /// First call must be BeginGroup; last must be EndGroup —
    /// nothing paints outside the group envelopes.
    #[test]
    fn paints_only_inside_group_envelopes() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &mixed_tiles(4), 0);
        assert!(matches!(painter.calls.first(), Some(Call::BeginGroup(_))));
        assert!(matches!(painter.calls.last(), Some(Call::EndGroup)));
    }

    /// Straight tiles emit 2 rail polylines + 3 tie polylines =
    /// 5 strokes per tile. Every line is 2-vertex (no arcs in
    /// straight topologies).
    #[test]
    fn paint_emits_five_polylines_per_straight_tile() {
        let tiles = mixed_tiles(4);
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &tiles, 0);
        assert_eq!(
            painter.polyline_count(),
            tiles.len() * 5,
            "expected 2 rails + 3 ties per straight tile",
        );
        for c in &painter.calls {
            if let Call::StrokePolyline(n, _) = c {
                assert_eq!(
                    *n, 2,
                    "every straight cart-track line is 2-vertex",
                );
            }
        }
    }

    /// Rails use stroke-width 0.9; ties use stroke-width 1.4.
    /// Straight tiles emit 2 rails followed by 3 ties per tile;
    /// the rails group emits before the ties group, so widths
    /// land as rail*2n then tie*3n.
    #[test]
    fn paint_uses_documented_stroke_widths() {
        let tiles = mixed_tiles(3);
        let n = tiles.len();
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &tiles, 0);
        let widths = painter.stroke_widths();
        assert_eq!(widths.len(), n * 5);
        let rail_w = (RAIL_WIDTH * 100.0).round() as u32;
        let tie_w = (TIE_WIDTH * 100.0).round() as u32;
        for w in &widths[..n * 2] {
            assert_eq!(*w, rail_w, "rails group uses rail width");
        }
        for w in &widths[n * 2..] {
            assert_eq!(*w, tie_w, "ties group uses tie width");
        }
    }

    // ── Topology dispatch tests ─────────────────────────────────

    /// 0-side mask emits no geometry (defensive — Phase 1 strips
    /// sub-3-tile runs but the painter handles isolated tiles
    /// gracefully).
    #[test]
    fn isolated_tile_emits_no_strokes() {
        let mut painter = CaptureCalls::default();
        paint_cart_tracks(&mut painter, &[(0, 0, 0)], 0);
        // Empty groups still bracket the paint pass; group calls
        // count to 4 (two begin/end pairs) but no polylines fire.
        assert_eq!(painter.polyline_count(), 0);
    }

    /// L-corner tiles emit 2 rail polylines (each a 9-vertex
    /// quarter-arc tessellation) + 3 radial tie segments.
    #[test]
    fn corner_tile_emits_two_arc_rails() {
        // N+E corner.
        let tiles = vec![(2, 2, OPEN_N | OPEN_E)];
        let shapes = cart_tracks_shapes(&tiles);
        assert_eq!(shapes.len(), 1);
        assert_eq!(shapes[0].rails.len(), 2);
        for rail in &shapes[0].rails {
            assert_eq!(
                rail.len(),
                ARC_SEGMENTS + 1,
                "arc rail has SEGMENTS + 1 vertices",
            );
        }
        assert_eq!(shapes[0].ties.len(), 3);
    }

    /// T-junction emits the through pair (2 full rails) +
    /// two branch stubs (2 half rails) = 4 rails. Ties only
    /// on the through line (3 ties). Branch stubs are unadorned.
    #[test]
    fn t_junction_emits_four_rails_three_ties() {
        // N+S+E.
        let shapes = cart_tracks_shapes(
            &[(0, 0, OPEN_N | OPEN_S | OPEN_E)],
        );
        assert_eq!(shapes.len(), 1);
        assert_eq!(
            shapes[0].rails.len(),
            4,
            "T-junction = 2 through + 2 branch rails",
        );
        assert_eq!(shapes[0].ties.len(), 3);
    }

    /// Cross emits 4 full rails (2 vertical + 2 horizontal),
    /// no ties.
    #[test]
    fn cross_emits_four_rails_no_ties() {
        let shapes = cart_tracks_shapes(
            &[(0, 0, OPEN_N | OPEN_S | OPEN_E | OPEN_W)],
        );
        assert_eq!(shapes.len(), 1);
        assert_eq!(shapes[0].rails.len(), 4);
        assert_eq!(shapes[0].ties.len(), 0);
    }

    /// Dead-end emits 2 half-cell rails + 2 ties (midpoint +
    /// terminus bumper).
    #[test]
    fn dead_end_emits_two_rails_two_ties() {
        for &mask in &[OPEN_N, OPEN_S, OPEN_E, OPEN_W] {
            let shapes = cart_tracks_shapes(&[(0, 0, mask)]);
            assert_eq!(shapes.len(), 1);
            assert_eq!(
                shapes[0].rails.len(),
                2,
                "dead-end has 2 half-cell rails (mask={mask:#06b})",
            );
            assert_eq!(
                shapes[0].ties.len(),
                2,
                "dead-end has 1 tie + 1 bumper (mask={mask:#06b})",
            );
        }
    }

    /// Each of the 4 corner orientations produces a distinct arc
    /// geometry. Confirms the start / end angle table doesn't
    /// collapse rotations.
    #[test]
    fn all_four_corners_have_distinct_geometries() {
        let masks = [
            OPEN_N | OPEN_E,
            OPEN_N | OPEN_W,
            OPEN_S | OPEN_E,
            OPEN_S | OPEN_W,
        ];
        let shapes: Vec<_> = masks
            .iter()
            .map(|&m| cart_tracks_shapes(&[(0, 0, m)]).remove(0))
            .collect();
        for i in 0..shapes.len() {
            for j in (i + 1)..shapes.len() {
                assert_ne!(
                    shapes[i], shapes[j],
                    "corner masks {} and {} produced identical shapes",
                    masks[i], masks[j],
                );
            }
        }
    }
    /// Painter-path determinism: same input → same call sequence.
    #[test]
    fn paint_deterministic_for_same_input() {
        let tiles = mixed_tiles(3);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_cart_tracks(&mut a, &tiles, 0);
        paint_cart_tracks(&mut b, &tiles, 0);
        assert_eq!(
            a.calls, b.calls,
            "same tiles must produce identical Painter calls",
        );
    }

    /// Orientation sensitivity: flipping every tile's orientation
    /// must change the polyline geometry (so the sequence of
    /// recorded calls differs even though stamp counts match).
    #[test]
    fn paint_orientation_changes_geometry() {
        let h_tiles: Vec<_> = (0..3)
            .map(|x| (x, 0_i32, OPEN_E | OPEN_W))
            .collect();
        let v_tiles: Vec<_> = (0..3)
            .map(|x| (x, 0_i32, OPEN_N | OPEN_S))
            .collect();
        // Geometry differs between horizontal and vertical, so the
        // shape stream itself must differ.
        let h_shapes = cart_tracks_shapes(&h_tiles);
        let v_shapes = cart_tracks_shapes(&v_tiles);
        assert_ne!(h_shapes, v_shapes);
    }
}
