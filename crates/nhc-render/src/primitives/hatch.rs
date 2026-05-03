//! Hatch primitive — Phase 4, sub-step 1.d (plan §8 Q1 strategy A),
//! ported to the Painter trait in Phase 2.9 of
//! `plans/nhc_pure_ir_plan.md` — the **first group-opacity port**.
//!
//! Reproduces `_render_corridor_hatching` and the per-tile body of
//! `_render_hatching` from `nhc/rendering/_hatching.py`. The room
//! candidate-walk + Perlin distance filter ran emit-side in
//! sub-step 1.b — both Rust entry points (`draw_hatch_corridor`
//! and `draw_hatch_room`) just iterate the pre-filtered tile list
//! and emit SVG fragments.
//!
//! **Parity contract (relaxed gate, plan §8 carve-out):** byte-
//! equal-with-legacy is *not* required. Output is gated by
//! structural invariants
//! (`tests/unit/test_emit_hatch_invariants.py`) plus a snapshot
//! lock that pins the new Rust output (lands in sub-step 1.f).
//! The RNG (`Pcg64Mcg`) and the polygon-line clip backend (`geo`
//! crate) are Rust-native; nothing here tracks the legacy
//! CPython `random.Random` / Shapely numerics.
//!
//! Two emit paths coexist during Phase 2:
//!
//! - The legacy `draw_hatch_corridor` / `draw_hatch_room`
//!   SVG-string emitters (used by the FFI / `nhc/rendering/
//!   ir_to_svg.py` Python path until 2.17 ships the
//!   `SvgPainter`-based PyO3 export and 2.19 retires the Python
//!   `ir_to_svg` path).
//! - The new `paint_hatch_corridor` / `paint_hatch_room` Painter-
//!   based emitters (used by the Rust `transform/png` path via
//!   `SkiaPainter` and, after 2.17, by the Rust `ir_to_svg` path
//!   via `SvgPainter`).
//!
//! Both paths share the private `tile_shapes_into_buckets` shape-
//! stream generator — the per-tile geometry is RNG- and Perlin-
//! driven and the snapshot/structural-invariants gates require a
//! single source of truth for the per-tile shape sequence.
//!
//! ## Group-opacity contract (Phase 5.10 of parent migration)
//!
//! The legacy SVG output wraps each non-empty bucket in
//! `<g opacity="…">` — `0.3` for `tile_fills`, `0.5` for
//! `hatch_lines`, **no opacity attr** for `hatch_stones` (full
//! opacity, the SVG path uses bare `<g>`). The pre-2.9 PNG
//! handler bypassed Phase 5.10's `paint_offscreen_group` and
//! used per-element alpha, which over-darkens overlapping hatch
//! stamps relative to the SVG-spec offscreen-buffer composite.
//! The Painter port restores SVG-spec semantics by wrapping each
//! coloured bucket in `begin_group(opacity)` / `end_group()`;
//! `hatch_stones` runs at full opacity with no group wrapper to
//! match the bare `<g>` in the SVG envelope.

use geo::{
    BooleanOps, Coord, LineString, MultiLineString, Polygon,
};
use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, FillRule, LineCap, LineJoin, Paint, Painter, PathOps, Stroke, Vec2,
};
use crate::perlin::pnoise2;

const CELL: f64 = 32.0;
const HATCH_UNDERLAY: &str = "#D0D0D0";
const INK: &str = "#000000";
const STONE_STROKE: &str = "#666666";

/// Group-opacity envelope for the `tile_fills` bucket. Lifts the
/// `<g opacity="0.3">` wrapper from `nhc/rendering/ir_to_svg.py`.
pub const TILE_FILLS_OPACITY: f32 = 0.3;
/// Group-opacity envelope for the `hatch_lines` bucket. Lifts the
/// `<g opacity="0.5">` wrapper from `nhc/rendering/ir_to_svg.py`.
pub const HATCH_LINES_OPACITY: f32 = 0.5;

/// Three SVG fragment buckets emitted per hatch call:
/// `(tile_fills, hatch_lines, hatch_stones)`. The Python handler
/// stitches them into the legacy `<g opacity="...">` envelopes.
type Buckets = (Vec<String>, Vec<String>, Vec<String>);

/// Per-tile shape — backend-agnostic record. The shape stream is
/// the single source of truth: `draw_hatch_*` formats each shape
/// as an SVG fragment string, `paint_hatch_*` dispatches each
/// shape through the Painter trait. Both paths consume the same
/// RNG sequence in lock-step, so the Painter and SVG output stay
/// stamp-for-stamp aligned.
#[derive(Clone, Copy, Debug, PartialEq)]
enum HatchShape {
    /// Grey underlay rect at integer pixel coords (`px`, `py`).
    /// Width and height are `CELL` (32). Drawn at
    /// `TILE_FILLS_OPACITY` group opacity.
    TileFill { x: i64, y: i64 },
    /// Rotated stone ellipse. `cx`, `cy` are the centre; `rx`, `ry`
    /// the radii; `angle_deg` the rotation. Stroke width `sw`
    /// uses `STONE_STROKE` ink. Drawn at full opacity.
    HatchStone {
        cx: f64,
        cy: f64,
        rx: f64,
        ry: f64,
        angle_deg: f64,
        sw: f64,
    },
    /// Perlin-wobbled hatch line from `(x1, y1)` to `(x2, y2)`,
    /// stroke width `sw` in `INK`. Drawn at `HATCH_LINES_OPACITY`
    /// group opacity. `LineCap::Round` for both ends.
    HatchLine {
        x1: f64,
        y1: f64,
        x2: f64,
        y2: f64,
        sw: f64,
    },
}

/// Per-bucket `HatchShape` streams in legacy emission order.
/// `(tile_fills, hatch_lines, hatch_stones)` — same bucketing as
/// `Buckets` (the SVG-string version) so the SVG emitter and the
/// Painter emitter stay symmetrical at the bucket boundary.
type ShapeBuckets = (Vec<HatchShape>, Vec<HatchShape>, Vec<HatchShape>);

/// Corridor halo — adjacent-VOID tiles around corridors / doors.
/// `tiles` is the pre-sorted list emitted by `_floor_layers.py`
/// 1.c.1; the seed already includes the legacy `+7` offset. No
/// 10 % skip applies (caves and corridor halos take the dense
/// path in the legacy renderer).
pub fn draw_hatch_corridor(tiles: &[(i32, i32)], seed: u64) -> Buckets {
    let shapes = corridor_shapes(tiles, seed);
    shapes_to_svg_buckets(&shapes)
}

/// Room (perimeter) halo — candidate tiles emitted by
/// `_floor_layers.py` 1.b after the Perlin distance filter.
/// `is_outer[i]` carries the cave-aware `dist > base_distance_limit
/// * 0.5` flag; the 10 % RNG skip fires only on outer tiles, in
/// lock-step with the consumer-side legacy walk.
pub fn draw_hatch_room(
    tiles: &[(i32, i32)],
    is_outer: &[bool],
    seed: u64,
) -> Buckets {
    let shapes = room_shapes(tiles, is_outer, seed);
    shapes_to_svg_buckets(&shapes)
}

/// Painter-path twin of `draw_hatch_corridor`. Wraps each non-empty
/// coloured bucket in `begin_group(opacity)` / `end_group()` to
/// match the legacy SVG `<g opacity="…">` envelopes; the
/// `hatch_stones` bucket runs at full opacity with no group
/// wrapper (the SVG path emits a bare `<g>` for it). Per-tile
/// emission order is preserved verbatim within each bucket.
pub fn paint_hatch_corridor(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    seed: u64,
) {
    let shapes = corridor_shapes(tiles, seed);
    paint_shape_buckets(painter, &shapes);
}

/// Painter-path twin of `draw_hatch_room`. Same group-opacity
/// envelope contract as `paint_hatch_corridor`; the room-only
/// `is_outer` 10 % RNG-skip fires in lock-step with the SVG-string
/// path.
pub fn paint_hatch_room(
    painter: &mut dyn Painter,
    tiles: &[(i32, i32)],
    is_outer: &[bool],
    seed: u64,
) {
    let shapes = room_shapes(tiles, is_outer, seed);
    paint_shape_buckets(painter, &shapes);
}

// ── Shape-stream generators ──────────────────────────────────

fn corridor_shapes(tiles: &[(i32, i32)], seed: u64) -> ShapeBuckets {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut buckets: ShapeBuckets = (
        Vec::with_capacity(tiles.len()),
        Vec::new(),
        Vec::new(),
    );
    for &(gx, gy) in tiles {
        tile_shapes_into_buckets(
            gx,
            gy,
            &CORRIDOR_STONE_DIST,
            &mut rng,
            &mut buckets,
        );
    }
    buckets
}

fn room_shapes(
    tiles: &[(i32, i32)],
    is_outer: &[bool],
    seed: u64,
) -> ShapeBuckets {
    let mut rng = Pcg64Mcg::seed_from_u64(seed);
    let mut buckets: ShapeBuckets = (
        Vec::with_capacity(tiles.len()),
        Vec::new(),
        Vec::new(),
    );
    for (i, &(gx, gy)) in tiles.iter().enumerate() {
        let outer = is_outer.get(i).copied().unwrap_or(false);
        if outer && rng.gen::<f64>() < 0.10 {
            continue;
        }
        tile_shapes_into_buckets(
            gx,
            gy,
            &ROOM_STONE_DIST,
            &mut rng,
            &mut buckets,
        );
    }
    buckets
}

// ── Bucket → SVG / Painter dispatchers ───────────────────────

fn shapes_to_svg_buckets(shapes: &ShapeBuckets) -> Buckets {
    let (tile_fills, hatch_lines, hatch_stones) = shapes;
    (
        tile_fills.iter().map(format_shape_svg).collect(),
        hatch_lines.iter().map(format_shape_svg).collect(),
        hatch_stones.iter().map(format_shape_svg).collect(),
    )
}

fn paint_shape_buckets(
    painter: &mut dyn Painter,
    shapes: &ShapeBuckets,
) {
    let (tile_fills, hatch_lines, hatch_stones) = shapes;

    if !tile_fills.is_empty() {
        painter.begin_group(TILE_FILLS_OPACITY);
        for shape in tile_fills {
            paint_shape(painter, shape);
        }
        painter.end_group();
    }
    if !hatch_lines.is_empty() {
        painter.begin_group(HATCH_LINES_OPACITY);
        for shape in hatch_lines {
            paint_shape(painter, shape);
        }
        painter.end_group();
    }
    // hatch_stones: full opacity, bare `<g>` in the SVG envelope —
    // no `begin_group(1.0)` wrapper needed. Emit elements directly.
    for shape in hatch_stones {
        paint_shape(painter, shape);
    }
}

fn format_shape_svg(shape: &HatchShape) -> String {
    match *shape {
        HatchShape::TileFill { x, y } => format!(
            "<rect x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" \
             fill=\"{}\"/>",
            x, y, CELL as i64, CELL as i64, HATCH_UNDERLAY,
        ),
        HatchShape::HatchStone {
            cx,
            cy,
            rx,
            ry,
            angle_deg,
            sw,
        } => format!(
            "<ellipse cx=\"{cx:.1}\" cy=\"{cy:.1}\" \
             rx=\"{rx:.1}\" ry=\"{ry:.1}\" \
             transform=\"rotate({a:.0},{cx:.1},{cy:.1})\" \
             fill=\"{HATCH_UNDERLAY}\" stroke=\"{STONE_STROKE}\" \
             stroke-width=\"{sw:.1}\"/>",
            a = angle_deg,
        ),
        HatchShape::HatchLine { x1, y1, x2, y2, sw } => format!(
            "<line x1=\"{:.1}\" y1=\"{:.1}\" x2=\"{:.1}\" y2=\"{:.1}\" \
             stroke=\"{INK}\" stroke-width=\"{sw:.2}\" \
             stroke-linecap=\"round\"/>",
            x1, y1, x2, y2,
        ),
    }
}

fn paint_shape(painter: &mut dyn Painter, shape: &HatchShape) {
    match *shape {
        HatchShape::TileFill { x, y } => {
            let rect = crate::painter::Rect::new(
                x as f32,
                y as f32,
                CELL as f32,
                CELL as f32,
            );
            painter.fill_rect(rect, &paint_for_hex(HATCH_UNDERLAY));
        }
        HatchShape::HatchStone {
            cx,
            cy,
            rx,
            ry,
            angle_deg,
            sw,
        } => {
            let path = rotated_ellipse_path(cx, cy, rx, ry, angle_deg);
            painter.fill_path(
                &path,
                &paint_for_hex(HATCH_UNDERLAY),
                FillRule::Winding,
            );
            painter.stroke_path(
                &path,
                &paint_for_hex(STONE_STROKE),
                &Stroke {
                    width: sw as f32,
                    line_cap: LineCap::Butt,
                    line_join: LineJoin::Miter,
                },
            );
        }
        HatchShape::HatchLine { x1, y1, x2, y2, sw } => {
            let mut path = PathOps::new();
            path.move_to(Vec2::new(x1 as f32, y1 as f32));
            path.line_to(Vec2::new(x2 as f32, y2 as f32));
            painter.stroke_path(
                &path,
                &paint_for_hex(INK),
                &Stroke {
                    width: sw as f32,
                    line_cap: LineCap::Round,
                    line_join: LineJoin::Round,
                },
            );
        }
    }
}

/// Build a closed cubic-Bezier ellipse path centred at `(cx, cy)`
/// with radii `(rx, ry)`, rotated by `angle_deg` around `(cx, cy)`.
/// Mirrors the legacy `ellipse_path` helper in
/// `transform/png/hatch.rs` (same KAPPA approximation) but bakes
/// the rotation into the control-point coords so the path is
/// backend-agnostic. The Painter trait's `fill_ellipse` is
/// axis-aligned, so the rotated stones go through `fill_path` /
/// `stroke_path` instead.
fn rotated_ellipse_path(
    cx: f64,
    cy: f64,
    rx: f64,
    ry: f64,
    angle_deg: f64,
) -> PathOps {
    const KAPPA: f64 = 0.552_284_8;
    let ox = rx * KAPPA;
    let oy = ry * KAPPA;
    let theta = angle_deg.to_radians();
    let cos_t = theta.cos();
    let sin_t = theta.sin();
    // Rotate `(dx, dy)` (relative to centre) and translate back.
    let xform = |dx: f64, dy: f64| -> Vec2 {
        let rx = dx * cos_t - dy * sin_t;
        let ry = dx * sin_t + dy * cos_t;
        Vec2::new((cx + rx) as f32, (cy + ry) as f32)
    };
    let mut path = PathOps::new();
    path.move_to(xform(rx, 0.0));
    path.cubic_to(xform(rx, oy), xform(ox, ry), xform(0.0, ry));
    path.cubic_to(xform(-ox, ry), xform(-rx, oy), xform(-rx, 0.0));
    path.cubic_to(xform(-rx, -oy), xform(-ox, -ry), xform(0.0, -ry));
    path.cubic_to(xform(ox, -ry), xform(rx, -oy), xform(rx, 0.0));
    path.close();
    path
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

// ── Stone-count weighted distributions ───────────────────────
//
// Corridor: `rng.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])`.
// Room:     `rng.choices([0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15])`.

struct StoneDist {
    /// Cumulative weights, normalised to 1.0 at the last entry.
    cumulative: &'static [(u8, f64)],
}

const CORRIDOR_STONE_DIST: StoneDist = StoneDist {
    cumulative: &[(0, 0.5), (1, 0.85), (2, 1.0)],
};
const ROOM_STONE_DIST: StoneDist = StoneDist {
    cumulative: &[(0, 0.25), (1, 0.6), (2, 0.85), (3, 1.0)],
};

fn pick_stones(dist: &StoneDist, rng: &mut Pcg64Mcg) -> u8 {
    let r: f64 = rng.gen();
    for &(value, threshold) in dist.cumulative {
        if r < threshold {
            return value;
        }
    }
    dist.cumulative.last().map(|&(v, _)| v).unwrap_or(0)
}

// ── Per-tile shape generation ─────────────────────────────────

fn tile_shapes_into_buckets(
    gx: i32,
    gy: i32,
    stone_dist: &StoneDist,
    rng: &mut Pcg64Mcg,
    buckets: &mut ShapeBuckets,
) {
    let (ref mut tile_fills, ref mut hatch_lines, ref mut hatch_stones) =
        *buckets;

    // Grey underlay tile.
    let px = f64::from(gx) * CELL;
    let py = f64::from(gy) * CELL;
    tile_fills.push(HatchShape::TileFill {
        x: px as i64,
        y: py as i64,
    });

    // Stone scatter.
    let n_stones = pick_stones(stone_dist, rng);
    for _ in 0..n_stones {
        let sx = (f64::from(gx) + rng.gen_range(0.15..0.85)) * CELL;
        let sy = (f64::from(gy) + rng.gen_range(0.15..0.85)) * CELL;
        let rx: f64 = rng.gen_range(2.0..(CELL * 0.25));
        let ry: f64 = rng.gen_range(2.0..(CELL * 0.2));
        let angle: f64 = rng.gen_range(0.0..180.0);
        let sw: f64 = rng.gen_range(1.2..2.0);
        hatch_stones.push(HatchShape::HatchStone {
            cx: sx,
            cy: sy,
            rx,
            ry,
            angle_deg: angle,
            sw,
        });
    }

    // Perlin-displaced cluster anchor.
    let nr = CELL * 0.1;
    let adx = pnoise2(f64::from(gx) * 0.5, f64::from(gy) * 0.5, 1) * nr;
    let ady = pnoise2(f64::from(gx) * 0.5, f64::from(gy) * 0.5, 2) * nr;
    let anchor = (
        (f64::from(gx) + 0.5) * CELL + adx,
        (f64::from(gy) + 0.5) * CELL + ady,
    );

    // Tile corners in legacy iteration order: TL → TR → BR → BL.
    let corners = [
        (px, py),
        (px + CELL, py),
        (px + CELL, py + CELL),
        (px, py + CELL),
    ];

    // Pick 3 random perimeter points.
    let pts = pick_section_points(&corners, anchor, CELL, rng);
    let sections = build_sections(anchor, &pts, &corners);

    for (sec_i, section) in sections.iter().enumerate() {
        let area = polygon_area(section);
        if area < 1.0 {
            continue;
        }

        let seg_angle = if sec_i == 0 {
            (pts[1].1 - pts[0].1).atan2(pts[1].0 - pts[0].0)
        } else {
            rng.gen_range(0.0..std::f64::consts::PI)
        };

        let bbox = polygon_bounds(section);
        let diag = ((bbox.2 - bbox.0).powi(2)
            + (bbox.3 - bbox.1).powi(2))
        .sqrt();
        let spacing = CELL * 0.20;
        let n_lines = std::cmp::max(3, (diag / spacing) as i32);

        let centroid = polygon_centroid(section);
        let geo_section = section_to_geo(section);

        let cos_a = seg_angle.cos();
        let sin_a = seg_angle.sin();
        let perp_cos = (seg_angle + std::f64::consts::FRAC_PI_2).cos();
        let perp_sin = (seg_angle + std::f64::consts::FRAC_PI_2).sin();

        for j in 0..n_lines {
            let offset =
                (f64::from(j) - f64::from(n_lines - 1) / 2.0) * spacing;
            let px = centroid.0 + perp_cos * offset;
            let py = centroid.1 + perp_sin * offset;
            let p1 = (px - cos_a * diag, py - sin_a * diag);
            let p2 = (px + cos_a * diag, py + sin_a * diag);
            // Stroke width must be drawn even when the line is
            // clipped away — the legacy handler advances the RNG
            // unconditionally inside the inner loop, and the
            // structural-invariants gate cares about the count
            // surviving the clip.
            let sw: f64 = rng.gen_range(1.0..1.8);

            let Some((c1, c2)) = clip_line_to_polygon(&geo_section, p1, p2)
            else {
                continue;
            };

            // Perlin wobble on each endpoint.
            let wb = CELL * 0.03;
            let q1 = (
                c1.0 + pnoise2(c1.0 * 0.1, c1.1 * 0.1, 10) * wb,
                c1.1 + pnoise2(c1.0 * 0.1, c1.1 * 0.1, 11) * wb,
            );
            let q2 = (
                c2.0 + pnoise2(c2.0 * 0.1, c2.1 * 0.1, 12) * wb,
                c2.1 + pnoise2(c2.0 * 0.1, c2.1 * 0.1, 13) * wb,
            );

            hatch_lines.push(HatchShape::HatchLine {
                x1: q1.0,
                y1: q1.1,
                x2: q2.0,
                y2: q2.1,
                sw,
            });
        }
    }
}

// ── Section partitioning (legacy `_pick_section_points` /
//    `_build_sections` ports). Sections are convex by
//    construction (anchor inside the tile + 2 perimeter points +
//    a CW corner walk).

type Pt = (f64, f64);

fn pick_section_points(
    corners: &[Pt; 4],
    anchor: Pt,
    grid_size: f64,
    rng: &mut Pcg64Mcg,
) -> [Pt; 3] {
    let mut pts: [Pt; 3] = [(0.0, 0.0); 3];
    for slot in pts.iter_mut() {
        let edge: u8 = rng.gen_range(0..=3);
        let t: f64 = rng.gen_range(0.0..grid_size);
        *slot = perimeter_point(corners, edge, t);
    }
    // Sort by angle from anchor, matching legacy
    // `pts.sort(key=lambda p: math.atan2(...))`.
    pts.sort_by(|a, b| {
        let aa = (a.1 - anchor.1).atan2(a.0 - anchor.0);
        let ab = (b.1 - anchor.1).atan2(b.0 - anchor.0);
        aa.partial_cmp(&ab).unwrap_or(std::cmp::Ordering::Equal)
    });
    pts
}

fn perimeter_point(corners: &[Pt; 4], edge: u8, t: f64) -> Pt {
    match edge {
        0 => (corners[0].0 + t, corners[0].1),
        1 => (corners[1].0, corners[1].1 + t),
        2 => (corners[2].0 - t, corners[2].1),
        _ => (corners[3].0, corners[3].1 - t),
    }
}

fn edge_index(p: Pt, corners: &[Pt; 4], grid_size: f64) -> u8 {
    let gx_px = corners[0].0;
    let gy_px = corners[0].1;
    if (p.1 - gy_px).abs() < 1e-3 {
        return 0;
    }
    if (p.0 - (gx_px + grid_size)).abs() < 1e-3 {
        return 1;
    }
    if (p.1 - (gy_px + grid_size)).abs() < 1e-3 {
        return 2;
    }
    3
}

fn build_sections(
    anchor: Pt,
    pts: &[Pt; 3],
    corners: &[Pt; 4],
) -> Vec<Vec<Pt>> {
    let gs = corners[1].0 - corners[0].0;
    let mut sections: Vec<Vec<Pt>> = Vec::with_capacity(3);
    for i in 0..3 {
        let p1 = pts[i];
        let p2 = pts[(i + 1) % 3];
        let mut verts: Vec<Pt> = vec![anchor, p1];
        let idx1 = edge_index(p1, corners, gs);
        let idx2 = edge_index(p2, corners, gs);
        let mut j = idx1;
        while j != idx2 {
            verts.push(corners[((j + 1) % 4) as usize]);
            j = (j + 1) % 4;
        }
        verts.push(p2);
        sections.push(verts);
    }
    sections
}

// ── Convex-polygon helpers ───────────────────────────────────

fn polygon_area(poly: &[Pt]) -> f64 {
    if poly.len() < 3 {
        return 0.0;
    }
    let mut sum = 0.0;
    for i in 0..poly.len() {
        let (x0, y0) = poly[i];
        let (x1, y1) = poly[(i + 1) % poly.len()];
        sum += x0 * y1 - x1 * y0;
    }
    (sum * 0.5).abs()
}

fn polygon_bounds(poly: &[Pt]) -> (f64, f64, f64, f64) {
    let mut min_x = f64::INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut max_y = f64::NEG_INFINITY;
    for &(x, y) in poly {
        if x < min_x {
            min_x = x;
        }
        if x > max_x {
            max_x = x;
        }
        if y < min_y {
            min_y = y;
        }
        if y > max_y {
            max_y = y;
        }
    }
    (min_x, min_y, max_x, max_y)
}

fn polygon_centroid(poly: &[Pt]) -> Pt {
    // Shoelace-weighted centroid for a simple polygon.
    if poly.len() < 3 {
        // Degenerate fallback — bounding-box midpoint.
        let (lo_x, lo_y, hi_x, hi_y) = polygon_bounds(poly);
        return ((lo_x + hi_x) * 0.5, (lo_y + hi_y) * 0.5);
    }
    let mut a = 0.0;
    let mut cx = 0.0;
    let mut cy = 0.0;
    for i in 0..poly.len() {
        let (x0, y0) = poly[i];
        let (x1, y1) = poly[(i + 1) % poly.len()];
        let cross = x0 * y1 - x1 * y0;
        a += cross;
        cx += (x0 + x1) * cross;
        cy += (y0 + y1) * cross;
    }
    if a.abs() < 1e-12 {
        let (lo_x, lo_y, hi_x, hi_y) = polygon_bounds(poly);
        return ((lo_x + hi_x) * 0.5, (lo_y + hi_y) * 0.5);
    }
    (cx / (3.0 * a), cy / (3.0 * a))
}

fn section_to_geo(poly: &[Pt]) -> Polygon<f64> {
    let coords: Vec<Coord<f64>> =
        poly.iter().map(|&(x, y)| Coord { x, y }).collect();
    Polygon::new(LineString::new(coords), vec![])
}

fn clip_line_to_polygon(
    poly: &Polygon<f64>,
    p1: Pt,
    p2: Pt,
) -> Option<(Pt, Pt)> {
    let line = LineString::new(vec![
        Coord { x: p1.0, y: p1.1 },
        Coord { x: p2.0, y: p2.1 },
    ]);
    let mls = MultiLineString::new(vec![line]);
    let clipped = poly.clip(&mls, false);
    // Legacy contract: take only the single-segment intersection.
    // If the line crosses the polygon in two separate pieces (rare
    // for convex sections but defensively checked), pick the
    // longer segment so the dominant chord wins.
    let mut best: Option<(Pt, Pt, f64)> = None;
    for ls in clipped.0.iter() {
        let coords: Vec<&Coord<f64>> = ls.coords().collect();
        if coords.len() < 2 {
            continue;
        }
        let a = (coords[0].x, coords[0].y);
        let b = (coords[coords.len() - 1].x, coords[coords.len() - 1].y);
        let len = ((b.0 - a.0).powi(2) + (b.1 - a.1).powi(2)).sqrt();
        match best {
            Some((_, _, blen)) if blen >= len => {}
            _ => best = Some((a, b, len)),
        }
    }
    best.map(|(a, b, _)| (a, b))
}

#[cfg(test)]
mod tests {
    use super::{
        clip_line_to_polygon, draw_hatch_corridor, draw_hatch_room,
        paint_hatch_corridor, paint_hatch_room, section_to_geo,
        HATCH_LINES_OPACITY, TILE_FILLS_OPACITY,
    };
    use crate::painter::{
        FillRule, Paint, Painter, PathOps, Rect, Stroke, Vec2,
    };

    /// Records every Painter call. Mirrors the trait-level
    /// `MockPainter` in `painter::tests` but lives in this module
    /// so the assertions stay close to the primitive.
    #[derive(Debug, Default)]
    struct CaptureCalls {
        calls: Vec<Call>,
        group_depth: i32,
        max_group_depth: i32,
    }

    #[derive(Debug, PartialEq)]
    enum Call {
        FillRect,
        FillPath,
        StrokePath,
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, _: Rect, _: &Paint) {
            self.calls.push(Call::FillRect);
        }
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(
            &mut self,
            _: f32,
            _: f32,
            _: f32,
            _: f32,
            _: &Paint,
        ) {
        }
        fn fill_polygon(
            &mut self,
            _: &[Vec2],
            _: &Paint,
            _: FillRule,
        ) {
        }
        fn stroke_polyline(
            &mut self,
            _: &[Vec2],
            _: &Paint,
            _: &Stroke,
        ) {
        }
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {
            self.calls.push(Call::FillPath);
        }
        fn stroke_path(&mut self, _: &PathOps, _: &Paint, _: &Stroke) {
            self.calls.push(Call::StrokePath);
        }
        fn begin_group(&mut self, opacity: f32) {
            self.group_depth += 1;
            if self.group_depth > self.max_group_depth {
                self.max_group_depth = self.group_depth;
            }
            // Quantise opacity for stable equality comparisons —
            // the bucket constants are 0.3 and 0.5, both round
            // cleanly to integer hundredths.
            self.calls
                .push(Call::BeginGroup((opacity * 100.0).round() as u32));
        }
        fn end_group(&mut self) {
            self.group_depth -= 1;
            self.calls.push(Call::EndGroup);
        }
        fn push_clip(&mut self, _: &PathOps, _: FillRule) {}
        fn pop_clip(&mut self) {}
    }

    impl CaptureCalls {
        fn count(&self, target: &Call) -> usize {
            self.calls.iter().filter(|c| *c == target).count()
        }
        fn begin_group_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::BeginGroup(_)))
                .count()
        }
        fn end_group_count(&self) -> usize {
            self.count(&Call::EndGroup)
        }
    }

    #[test]
    fn corridor_empty_tiles_returns_empty_buckets() {
        let (a, b, c) = draw_hatch_corridor(&[], 0);
        assert!(a.is_empty() && b.is_empty() && c.is_empty());
    }

    #[test]
    fn room_empty_tiles_returns_empty_buckets() {
        let (a, b, c) = draw_hatch_room(&[], &[], 0);
        assert!(a.is_empty() && b.is_empty() && c.is_empty());
    }

    #[test]
    fn corridor_emits_one_underlay_per_tile() {
        let tiles = [(0_i32, 0_i32), (1, 2), (5, 5)];
        let (fills, _, _) = draw_hatch_corridor(&tiles, 42);
        assert_eq!(fills.len(), tiles.len());
        for f in &fills {
            assert!(f.starts_with("<rect"));
            assert!(f.contains("fill=\"#D0D0D0\""));
        }
    }

    #[test]
    fn corridor_is_deterministic() {
        let tiles = [(0_i32, 0_i32), (1, 2), (5, 5), (-1, 7)];
        let a = draw_hatch_corridor(&tiles, 42);
        let b = draw_hatch_corridor(&tiles, 42);
        assert_eq!(a, b);
    }

    #[test]
    fn room_outer_skip_consumes_one_rng_per_outer_tile() {
        // Same tile list, same seed, every-tile-outer flag flipped
        // off vs on: the on case can drop tiles via the 10 % skip
        // and is therefore a (non-strict) subset of the off case
        // by tile-fill count.
        let tiles: Vec<(i32, i32)> =
            (0..40).map(|i| (i, 0)).collect();
        let all_outer = vec![true; tiles.len()];
        let none_outer = vec![false; tiles.len()];
        let (fills_off, _, _) = draw_hatch_room(&tiles, &none_outer, 7);
        let (fills_on, _, _) = draw_hatch_room(&tiles, &all_outer, 7);
        assert!(fills_on.len() <= fills_off.len());
        // Different seeds give different RNG behaviour, so don't
        // assert strict equality on the "off" path — just
        // determinism.
        let (fills_off2, _, _) = draw_hatch_room(&tiles, &none_outer, 7);
        assert_eq!(fills_off, fills_off2);
    }

    #[test]
    fn clip_line_to_polygon_inside_returns_full_chord() {
        // Unit square; line fully inside.
        let poly = section_to_geo(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]);
        let clipped =
            clip_line_to_polygon(&poly, (1.0, 5.0), (9.0, 5.0));
        assert!(clipped.is_some());
        let (a, b) = clipped.unwrap();
        assert!((a.0 - 1.0).abs() < 1e-6 && (a.1 - 5.0).abs() < 1e-6);
        assert!((b.0 - 9.0).abs() < 1e-6 && (b.1 - 5.0).abs() < 1e-6);
    }

    #[test]
    fn clip_line_to_polygon_outside_returns_none() {
        let poly = section_to_geo(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]);
        let clipped =
            clip_line_to_polygon(&poly, (20.0, 20.0), (30.0, 30.0));
        assert!(clipped.is_none());
    }

    #[test]
    fn clip_line_to_polygon_crossing_returns_chord() {
        // Horizontal line crossing the unit square through the middle.
        let poly = section_to_geo(&[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]);
        let clipped =
            clip_line_to_polygon(&poly, (-5.0, 5.0), (15.0, 5.0));
        assert!(clipped.is_some());
        let (a, b) = clipped.unwrap();
        // Endpoints land on x=0 and x=10 with y=5.
        let xs = [a.0.min(b.0), a.0.max(b.0)];
        assert!((xs[0]).abs() < 1e-6);
        assert!((xs[1] - 10.0).abs() < 1e-6);
    }

    // ── Painter-path tests ─────────────────────────────────────

    /// Empty corridor → zero painter calls. Sanity check that no
    /// spurious begin_group / end_group fires on an empty bucket.
    #[test]
    fn paint_hatch_corridor_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_hatch_corridor(&mut painter, &[], 0);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// Empty room → zero painter calls. Symmetric to corridor.
    #[test]
    fn paint_hatch_room_empty_tiles_emits_no_calls() {
        let mut painter = CaptureCalls::default();
        paint_hatch_room(&mut painter, &[], &[], 0);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    /// One corridor tile → at minimum, the tile_fills group fires
    /// (every tile produces exactly one TileFill). The hatch_lines
    /// group fires too because every tile yields ≥ 9 hatch lines
    /// (3 sections × ≥ 3 lines each, gated by the area > 1.0 cull
    /// — for a non-degenerate tile, all three sections survive).
    /// The hatch_stones bucket has NO group wrapper (full opacity
    /// in the SVG envelope) so its fill/stroke calls land outside
    /// any group.
    #[test]
    fn paint_hatch_corridor_one_tile_wraps_buckets_in_groups() {
        let mut painter = CaptureCalls::default();
        paint_hatch_corridor(&mut painter, &[(0_i32, 0_i32)], 42);

        // Bucket structure: begin_group(0.3) → fill_rect+ →
        // end_group → begin_group(0.5) → stroke_path+ → end_group
        // → fill_path/stroke_path pairs (stones, no wrapper).
        assert!(
            painter.begin_group_count() == painter.end_group_count(),
            "begin/end groups must balance: {} begins vs {} ends",
            painter.begin_group_count(),
            painter.end_group_count(),
        );
        assert_eq!(
            painter.group_depth, 0,
            "group depth must end at 0"
        );
        assert!(
            painter.max_group_depth <= 1,
            "buckets are not nested — max depth must be ≤ 1, got {}",
            painter.max_group_depth,
        );

        // tile_fills at 0.3 group opacity is always emitted on a
        // non-empty tile list.
        assert!(
            painter
                .calls
                .iter()
                .any(|c| matches!(c, Call::BeginGroup(30))),
            "expected begin_group at 0.3 (TILE_FILLS_OPACITY = {}); got {:?}",
            TILE_FILLS_OPACITY,
            painter.calls,
        );
        // Exactly one fill_rect for the single tile_fill.
        assert_eq!(painter.count(&Call::FillRect), 1);
    }

    /// Group wrapper opacities match the documented bucket
    /// constants (0.3 tile_fills, 0.5 hatch_lines).
    #[test]
    fn paint_hatch_corridor_uses_documented_bucket_opacities() {
        let mut painter = CaptureCalls::default();
        paint_hatch_corridor(&mut painter, &[(0_i32, 0_i32)], 42);
        let opacities: Vec<u32> = painter
            .calls
            .iter()
            .filter_map(|c| match c {
                Call::BeginGroup(op) => Some(*op),
                _ => None,
            })
            .collect();
        // Two non-empty groups: tile_fills (0.3 → 30) then
        // hatch_lines (0.5 → 50). hatch_stones is unwrapped.
        assert_eq!(
            opacities,
            vec![
                (TILE_FILLS_OPACITY * 100.0).round() as u32,
                (HATCH_LINES_OPACITY * 100.0).round() as u32,
            ],
            "group opacities must be (TILE_FILLS_OPACITY, HATCH_LINES_OPACITY)",
        );
    }

    /// Room-path: same bucket / group contract as corridor, plus
    /// the `is_outer` 10 %-skip pathway must keep groups balanced
    /// even when some tiles are skipped.
    #[test]
    fn paint_hatch_room_outer_skip_keeps_groups_balanced() {
        let mut painter = CaptureCalls::default();
        let tiles: Vec<(i32, i32)> =
            (0..40).map(|i| (i, 0)).collect();
        let all_outer = vec![true; tiles.len()];
        paint_hatch_room(&mut painter, &tiles, &all_outer, 7);
        assert_eq!(
            painter.group_depth, 0,
            "group depth must end at 0 even when tiles skip"
        );
        assert_eq!(
            painter.begin_group_count(),
            painter.end_group_count(),
        );
    }

    /// Cross-check that the SVG-string emitter and the Painter
    /// emitter agree on bucket sizes for the same seed/tiles.
    /// Both consume the same shape stream, so the count of
    /// fill_rect calls (Painter) equals the count of tile_fills
    /// (SVG); the count of stroke_path calls (Painter, hatch lines
    /// only — stones contribute fill_path + stroke_path pairs)
    /// equals the count of hatch_lines (SVG); and hatch_stones
    /// pairs (fill_path + stroke_path) match the SVG count.
    #[test]
    fn paint_and_draw_agree_on_bucket_counts() {
        let tiles = [(0_i32, 0_i32), (1, 2), (5, 5), (-1, 7)];
        let seed = 42;

        let (svg_fills, svg_lines, svg_stones) =
            draw_hatch_corridor(&tiles, seed);

        let mut painter = CaptureCalls::default();
        paint_hatch_corridor(&mut painter, &tiles, seed);

        // Each TileFill → one fill_rect.
        assert_eq!(
            svg_fills.len(),
            painter.count(&Call::FillRect),
            "tile_fills count mismatch",
        );
        // Each HatchStone → one fill_path + one stroke_path.
        // Each HatchLine → one stroke_path. So
        // total stroke_path = stones + lines, fill_path = stones.
        assert_eq!(
            svg_stones.len(),
            painter.count(&Call::FillPath),
            "hatch_stones (fill_path) count mismatch",
        );
        assert_eq!(
            svg_lines.len() + svg_stones.len(),
            painter.count(&Call::StrokePath),
            "stroke_path total (lines + stones) mismatch",
        );
    }
}
