//! RoofOp rasterisation — Phase 8.1c.2 of the IR migration plan,
//! ported to the Painter trait in Phase 2.15b of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors the Python reference at `_draw_roof_from_ir` in
//! `nhc/rendering/ir_to_svg.py`. Both rasterisers walk the same
//! splitmix64 stream seeded with `RoofOp.rng_seed` so shingle
//! widths and shade picks agree value-for-value. The synthetic-IR
//! PSNR gate at `tests/unit/test_ir_png_parity.py` exercises this
//! handler against a tiny-skia-rendered `reference.png` at
//! PSNR ≥ 35 dB.
//!
//! Roof is handler-only (no `primitives/roof.rs`). The Python side
//! has its own `_draw_roof_from_ir` SVG emitter that does NOT call
//! the Rust FFI, so this commit REPLACES the legacy direct
//! tiny-skia calls with `SkiaPainter` calls outright — no dual
//! path needed. The region clip becomes a `push_clip(EvenOdd)` /
//! `pop_clip` envelope around all the helpers, mirroring the
//! handler-only ports of `terrain_detail` (Phase 2.12) and the
//! wood-floor branch of `floor_detail` (Phase 2.15a).

use crate::ir::{FloorIR, OpEntry, Region, RoofOp, RoofStyle, RoofTilePattern};
use crate::painter::{
    Color, FillRule, LineCap, Paint, Painter, PathOps, Rect as PRect,
    Stroke, Transform, Vec2,
};
use crate::rng::SplitMix64;


// ── Constants ───────────────────────────────────────────────────
// Mirror nhc/rendering/ir_to_svg.py's _ROOF_* constants
// value-for-value. A drift here would visibly skew the synthetic-
// IR PSNR gate; values are pinned by the parity test.

const SHADOW_FACTOR: f32 = 0.5;
const SHINGLE_WIDTH: f32 = 14.0;
const SHINGLE_HEIGHT: f32 = 5.0;
const SHINGLE_JITTER: f32 = 2.0;
const RIDGE_WIDTH: f32 = 1.5;
const SHINGLE_STROKE_OPACITY: f32 = 0.2;
const SHINGLE_STROKE_WIDTH: f32 = 0.3;
// Thin black outline per fishscale scallop so the scale pattern
// stays legible against its own palette fill.
const FISHSCALE_STROKE_WIDTH: f32 = 0.5;


// ── Splitmix64 helper layer matching the Python RNG surface ────


struct RoofRng {
    inner: SplitMix64,
}

impl RoofRng {
    fn new(seed: u64) -> Self {
        Self { inner: SplitMix64::from_seed(seed) }
    }

    fn uniform(&mut self, lo: f32, hi: f32) -> f32 {
        // Match Python's `next_u64() / 2**64` → [0, 1) mapping
        // exactly: 64-bit u64 cast to f64 (lossy at the top end,
        // but the Python side has the same loss), divide by 2^64.
        let u = self.inner.next_u64();
        let unit = (u as f64) / 18446744073709551616.0_f64;
        lo + (hi - lo) * (unit as f32)
    }

    fn choice<'a, T>(&mut self, seq: &'a [T]) -> &'a T {
        let u = self.inner.next_u64();
        &seq[(u as usize) % seq.len()]
    }
}


// ── Hex parsing + shade palette ────────────────────────────────


fn parse_hex(hx: &str) -> Option<(u8, u8, u8)> {
    let s = hx.strip_prefix('#').unwrap_or(hx);
    if s.len() < 6 {
        return None;
    }
    let r = u8::from_str_radix(&s[0..2], 16).ok()?;
    let g = u8::from_str_radix(&s[2..4], 16).ok()?;
    let b = u8::from_str_radix(&s[4..6], 16).ok()?;
    Some((r, g, b))
}

fn scale_rgb(rgb: (u8, u8, u8), factor: f32) -> (u8, u8, u8) {
    let s = |c: u8| -> u8 {
        (c as f32 * factor).clamp(0.0, 255.0) as u8
    };
    (s(rgb.0), s(rgb.1), s(rgb.2))
}

fn shade_palette(tint: &str, sunlit: bool) -> [(u8, u8, u8); 3] {
    let base = parse_hex(tint).unwrap_or((0x8A, 0x7A, 0x5A));
    let factors: [f32; 3] = if sunlit {
        [1.15, 1.00, 0.88]
    } else {
        let c = SHADOW_FACTOR;
        [c * 1.15, c, c * 0.88]
    };
    [
        scale_rgb(base, factors[0]),
        scale_rgb(base, factors[1]),
        scale_rgb(base, factors[2]),
    ]
}


// ── Geometry mode picker ───────────────────────────────────────


/// Drawing mode dispatched from `RoofStyle`. The emit pipeline
/// (`nhc/rendering/emit/roof.py`) picks the style per-shape so
/// that the production roof rendering stays byte-identical to
/// the legacy shape-driven dispatch — square / octagon / circle
/// footprints get `Pyramid`, wide rect / L-shape get `Gable`.
/// `Simple`, `Dome`, `WitchHat` are catalog-only styles today.
#[derive(Clone, Copy)]
enum Mode {
    Simple,
    Pyramid,
    Gable,
    Dome,
    WitchHat,
}

fn mode_for_style(style: RoofStyle) -> Mode {
    match style {
        RoofStyle::Pyramid => Mode::Pyramid,
        RoofStyle::Gable => Mode::Gable,
        RoofStyle::Dome => Mode::Dome,
        RoofStyle::WitchHat => Mode::WitchHat,
        // Simple + any unknown trailing variant fall through to
        // the flat-tint fallback.
        _ => Mode::Simple,
    }
}


// ── Paint helpers ──────────────────────────────────────────────


fn rgb_paint(rgb: (u8, u8, u8), alpha: f32) -> Paint {
    Paint::solid(Color::rgba(rgb.0, rgb.1, rgb.2, alpha))
}

/// A closed circle as four cubic Béziers (kappa ≈ 0.5523), for
/// strokeable outlines — the `Painter` trait has `fill_circle`
/// but no circle stroke primitive.
fn circle_path(cx: f32, cy: f32, r: f32) -> PathOps {
    const K: f32 = 0.552_284_8;
    let kr = K * r;
    let mut p = PathOps::new();
    p.move_to(Vec2::new(cx + r, cy));
    p.cubic_to(
        Vec2::new(cx + r, cy + kr),
        Vec2::new(cx + kr, cy + r),
        Vec2::new(cx, cy + r),
    );
    p.cubic_to(
        Vec2::new(cx - kr, cy + r),
        Vec2::new(cx - r, cy + kr),
        Vec2::new(cx - r, cy),
    );
    p.cubic_to(
        Vec2::new(cx - r, cy - kr),
        Vec2::new(cx - kr, cy - r),
        Vec2::new(cx, cy - r),
    );
    p.cubic_to(
        Vec2::new(cx + kr, cy - r),
        Vec2::new(cx + r, cy - kr),
        Vec2::new(cx + r, cy),
    );
    p.close();
    p
}

fn fishscale_stroke() -> Stroke {
    Stroke {
        width: FISHSCALE_STROKE_WIDTH,
        line_cap: LineCap::Butt,
        ..Stroke::default()
    }
}

fn ridge_stroke() -> Stroke {
    Stroke {
        width: RIDGE_WIDTH,
        line_cap: LineCap::Butt,
        ..Stroke::default()
    }
}

fn shingle_stroke() -> Stroke {
    Stroke {
        width: SHINGLE_STROKE_WIDTH,
        line_cap: LineCap::Butt,
        ..Stroke::default()
    }
}

/// Axis-aligned rectangle as a closed path — used for the
/// per-gable-half clip windows.
fn rect_path(x: f32, y: f32, w: f32, h: f32) -> PathOps {
    let mut p = PathOps::new();
    p.move_to(Vec2::new(x, y));
    p.line_to(Vec2::new(x + w, y));
    p.line_to(Vec2::new(x + w, y + h));
    p.line_to(Vec2::new(x, y + h));
    p.close();
    p
}

/// Reflection across the vertical line `x = mid`
/// (`(x, y) → (2·mid − x, y)`).
fn reflect_x(mid: f32) -> Transform {
    Transform { sx: -1.0, kx: 0.0, tx: 2.0 * mid, ky: 0.0, sy: 1.0, ty: 0.0 }
}

/// Reflection across the horizontal line `y = mid`
/// (`(x, y) → (x, 2·mid − y)`).
fn reflect_y(mid: f32) -> Transform {
    Transform { sx: 1.0, kx: 0.0, tx: 0.0, ky: 0.0, sy: -1.0, ty: 2.0 * mid }
}

/// Smooth lit fraction in `[0, 1]` for a facet pointing
/// `(dx, dy)` out from the centroid: `1` = fully sunlit, `0` =
/// full shadow. The light is fixed toward screen lower-right
/// (`+x, +y`, the same quadrant `draw_pyramid_sides`' binary
/// rule lit), but here it varies *continuously* with the facet's
/// angle so a pyramid / cone reads as a smooth radial gradient
/// instead of hard sun/shadow wedges.
fn facet_tone(dx: f32, dy: f32) -> f32 {
    let len = (dx * dx + dy * dy).sqrt();
    if len < 1e-6 {
        return 0.5;
    }
    // Light unit vector toward lower-right.
    const INV_SQRT2: f32 = 0.707_106_77;
    let d = (dx * INV_SQRT2 + dy * INV_SQRT2) / len;
    // Map cos∈[-1,1] → [0,1] but keep a floor/ceiling so the
    // darkest facet still carries texture and the brightest does
    // not blow out.
    (0.5 + 0.5 * d).clamp(0.12, 0.95)
}

fn lerp_u8(a: u8, b: u8, t: f32) -> u8 {
    (a as f32 + (b as f32 - a as f32) * t).round().clamp(0.0, 255.0) as u8
}

/// Per-entry blend of the `shadow` and `sunlit` palettes at lit
/// fraction `t` — gives each facet / ring band its own tone on a
/// continuous gradient rather than one of two fixed palettes.
fn lerp_palette(
    shadow: &[(u8, u8, u8); 3],
    sunlit: &[(u8, u8, u8); 3],
    t: f32,
) -> [(u8, u8, u8); 3] {
    let mut out = [(0u8, 0u8, 0u8); 3];
    for i in 0..3 {
        out[i] = (
            lerp_u8(shadow[i].0, sunlit[i].0, t),
            lerp_u8(shadow[i].1, sunlit[i].1, t),
            lerp_u8(shadow[i].2, sunlit[i].2, t),
        );
    }
    out
}


// ── Tile-pattern overlays (RoofTilePattern axis) ───────────────
//
// Each `paint_<pattern>` paints a tile texture across the
// polygon's bbox. The caller pushes the polygon clip envelope
// before calling; anything painted outside the outline is
// clipped automatically. The geometry's per-side / per-half
// shading paints first, so the pattern reads as a textured
// overlay on top of the building's silhouette.


/// `Fishscale` — overlapping half-discs (scallops) in offset
/// rows. Each tile is a full circle; adjacent rows offset by
/// half-tile horizontally and the rows tile tightly enough that
/// only the lower curve of each scale stays visible.
fn paint_fishscale(
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, w, h) = bbox;
    let pitch_x: f32 = 12.0;
    let pitch_y: f32 = 8.0;
    let radius: f32 = 7.0;
    let mut row: i32 = 0;
    let mut cy = min_y - radius;
    while cy < min_y + h + radius {
        let off = if row & 1 == 0 { 0.0 } else { pitch_x / 2.0 };
        let mut cx = min_x - radius + off;
        while cx < min_x + w + radius {
            let shade = *rng.choice(palette);
            painter.fill_circle(cx, cy, radius, &rgb_paint(shade, 1.0));
            painter.stroke_path(
                &circle_path(cx, cy, radius),
                &rgb_paint((0, 0, 0), 1.0),
                &fishscale_stroke(),
            );
            cx += pitch_x;
        }
        cy += pitch_y;
        row += 1;
    }
}

/// `Thatch` — short randomised vertical strands. Many thin
/// strokes with horizontal jitter and per-strand tone variance
/// read as straw. The strands stop short of the bbox so the
/// underlying geometry's silhouette stays visible at the edges.
fn paint_thatch(
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, w, h) = bbox;
    let stroke = Stroke {
        width: 0.5,
        line_cap: LineCap::Butt,
        ..Stroke::default()
    };
    let row_pitch: f32 = 3.0;
    let strand_pitch: f32 = 1.6;
    let mut y = min_y;
    while y < min_y + h {
        let mut x = min_x;
        while x < min_x + w {
            let len = 3.0 + rng.uniform(0.0, 4.0);
            let jx = rng.uniform(-1.5, 1.5);
            let shade = *rng.choice(palette);
            let mut path = PathOps::new();
            path.move_to(Vec2::new(x + jx, y));
            path.line_to(Vec2::new(x + jx, y + len));
            painter.stroke_path(&path, &rgb_paint(shade, 0.85), &stroke);
            x += strand_pitch + rng.uniform(-0.4, 0.4);
        }
        y += row_pitch;
    }
}

/// `Pantile` — wavy horizontal bands suggesting Mediterranean
/// S-curve tiles. Each row paints a sinusoidal band alternating
/// between palette tones; the wave amplitude is small relative
/// to band height so the bands read as ridge-and-valley tiles.
fn paint_pantile(
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    _rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, w, h) = bbox;
    let band_h: f32 = 8.0;
    let amp: f32 = 1.6;
    let waves_per_band: f32 = 6.0;
    let segments: i32 = 32;
    let mut row: i32 = 0;
    let mut top = min_y;
    while top < min_y + h {
        let shade = if row & 1 == 0 { palette[0] } else { palette[1] };
        let mut path = PathOps::new();
        for i in 0..=segments {
            let t = i as f32 / segments as f32;
            let x = min_x + t * w;
            let y = top + ((t * waves_per_band)
                * std::f32::consts::PI).sin() * amp;
            let p = Vec2::new(x, y);
            if i == 0 {
                path.move_to(p);
            } else {
                path.line_to(p);
            }
        }
        for i in (0..=segments).rev() {
            let t = i as f32 / segments as f32;
            let x = min_x + t * w;
            let y = top + ((t * waves_per_band)
                * std::f32::consts::PI).sin() * amp + band_h;
            path.line_to(Vec2::new(x, y));
        }
        path.close();
        painter.fill_path(&path, &rgb_paint(shade, 1.0), FillRule::Winding);
        top += band_h;
        row += 1;
    }
}

/// `Slate` — small rectangular tiles in a tight running-bond
/// with a hand-laid pass: a *light* per-tile size / row jitter
/// and a faint edge stroke. Smaller than `draw_shingle_region`'s
/// shingles (8 × 6 vs 14 × 5) and far more regular than Shingle's
/// heavy jitter, so it reads as a crisp slate counterpoint —
/// distinguished by scale + regularity, not by being flat
/// (`design/roof_patterns.md`).
fn paint_slate(
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, w, h) = bbox;
    let tile_w: f32 = 8.0;
    let tile_h: f32 = 6.0;
    let stroke = shingle_stroke();
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    let mut row: i32 = 0;
    let mut cy = min_y;
    while cy < min_y + h {
        let off = if row & 1 == 0 { 0.0 } else { tile_w / 2.0 };
        let mut x = min_x - tile_w + off;
        while x < min_x + w + tile_w {
            let shade = *rng.choice(palette);
            // Light jitter — keeps the grid crisp, just enough to
            // read as laid by hand rather than printed.
            let tw = (tile_w - 0.6 + rng.uniform(-0.6, 0.6)).max(1.0);
            let th = tile_h - 0.6;
            let ty = cy + rng.uniform(-0.4, 0.4);
            painter.fill_rect(
                PRect::new(x, ty, tw, th),
                &rgb_paint(shade, 1.0),
            );
            let mut edge = PathOps::new();
            edge.move_to(Vec2::new(x, ty));
            edge.line_to(Vec2::new(x + tw, ty));
            edge.line_to(Vec2::new(x + tw, ty + th));
            edge.line_to(Vec2::new(x, ty + th));
            edge.close();
            painter.stroke_path(&edge, &stroke_paint, &stroke);
            x += tile_w;
        }
        cy += tile_h;
        row += 1;
    }
}


/// `Shingle` — organic running-bond shingles over the bbox: size
/// jitter, per-tile random shade, a faint black edge. This is the
/// hand-laid look geometry's gable path draws today, promoted to
/// a first-class pattern usable on every style. Orientation
/// (mirroring across the ridge / per-facet rotation) is Phase 4;
/// for now it tiles the bbox in screen-axis running bond, clipped
/// to the silhouette by the active envelope.
fn paint_shingle(
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, w, h) = bbox;
    draw_shingle_region(min_x, min_y, w, h, palette, rng, painter, false);
}


// ── Shingle running-bond + gable + pyramid ─────────────────────


fn draw_shingle_region(
    x: f32, y: f32, w: f32, h: f32,
    shades: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
    vertical_courses: bool,
) {
    let stroke = shingle_stroke();
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    if vertical_courses {
        // Transposed layout — columns instead of rows; long axis
        // vertical. Used for horizontal-ridge gables so the
        // courses run perpendicular to the ridge. Mirror of the
        // Python ``_roof_shingle_region(vertical_courses=True)``
        // branch.
        let mut col = 0;
        let mut cx = x;
        while cx < x + w {
            let mut sy = if col % 2 == 1 { y - SHINGLE_WIDTH / 2.0 } else { y };
            while sy < y + h {
                let sw_j = SHINGLE_WIDTH + rng.uniform(-SHINGLE_JITTER, SHINGLE_JITTER);
                let shade = *rng.choice(shades);
                let vy = sy.max(y);
                let vb = (sy + sw_j).min(y + h);
                let vh = vb - vy;
                if vh > 0.0 {
                    let fill = rgb_paint(shade, 1.0);
                    painter.fill_rect(
                        PRect::new(cx, vy, SHINGLE_HEIGHT, vh),
                        &fill,
                    );
                    let mut path = PathOps::new();
                    path.move_to(Vec2::new(cx, vy));
                    path.line_to(Vec2::new(cx + SHINGLE_HEIGHT, vy));
                    path.line_to(Vec2::new(cx + SHINGLE_HEIGHT, vy + vh));
                    path.line_to(Vec2::new(cx, vy + vh));
                    path.close();
                    painter.stroke_path(&path, &stroke_paint, &stroke);
                }
                sy += sw_j;
            }
            cx += SHINGLE_HEIGHT;
            col += 1;
        }
        return;
    }
    let mut row = 0;
    let mut cy = y;
    while cy < y + h {
        let mut sx = if row % 2 == 1 { x - SHINGLE_WIDTH / 2.0 } else { x };
        while sx < x + w {
            let sw_j = SHINGLE_WIDTH + rng.uniform(-SHINGLE_JITTER, SHINGLE_JITTER);
            let shade = *rng.choice(shades);
            // Clamp the shingle's drawn rect to the region bbox so
            // it never bleeds past a vertical ridge into the
            // opposite-shaded side of a gable. Mirror of the
            // Python ``_roof_shingle_region`` clamp.
            let vx = sx.max(x);
            let vr = (sx + sw_j).min(x + w);
            let vw = vr - vx;
            if vw > 0.0 {
                let fill = rgb_paint(shade, 1.0);
                painter.fill_rect(
                    PRect::new(vx, cy, vw, SHINGLE_HEIGHT),
                    &fill,
                );
                let mut path = PathOps::new();
                path.move_to(Vec2::new(vx, cy));
                path.line_to(Vec2::new(vx + vw, cy));
                path.line_to(Vec2::new(vx + vw, cy + SHINGLE_HEIGHT));
                path.line_to(Vec2::new(vx, cy + SHINGLE_HEIGHT));
                path.close();
                painter.stroke_path(&path, &stroke_paint, &stroke);
            }
            sx += sw_j;
        }
        cy += SHINGLE_HEIGHT;
        row += 1;
    }
}

/// `Mode::Gable` — two flat shaded half-planes split on the long
/// axis with a single ridge line along the split. Geometry owns
/// only the silhouette / planes / shading / ridge; the surface
/// texture (the organic shingles this used to bake) is now the
/// `Shingle` overlay pattern, painted on top by the dispatcher.
/// The shadow half uses the shadow palette mid-tone, the sunlit
/// half the sunlit mid-tone — the same two tints the old shingle
/// fill averaged to.
fn draw_gable_sides(
    px: f32, py: f32, pw: f32, ph: f32,
    horizontal: bool,
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    _rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let ridge_paint = rgb_paint((0, 0, 0), 1.0);
    let stroke = ridge_stroke();
    let shadow_fill = rgb_paint(shadow[1], 1.0);
    let sunlit_fill = rgb_paint(sunlit[1], 1.0);
    let fill_quad = |painter: &mut dyn Painter,
                     x: f32, y: f32, w: f32, h: f32,
                     paint: &Paint| {
        let mut path = PathOps::new();
        path.move_to(Vec2::new(x, y));
        path.line_to(Vec2::new(x + w, y));
        path.line_to(Vec2::new(x + w, y + h));
        path.line_to(Vec2::new(x, y + h));
        path.close();
        painter.fill_path(&path, paint, FillRule::Winding);
    };
    if horizontal {
        // Horizontal ridge — shadow top half, sunlit bottom half.
        fill_quad(painter, px, py, pw, ph / 2.0, &shadow_fill);
        fill_quad(painter, px, py + ph / 2.0, pw, ph / 2.0, &sunlit_fill);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(px, py + ph / 2.0));
        path.line_to(Vec2::new(px + pw, py + ph / 2.0));
        painter.stroke_path(&path, &ridge_paint, &stroke);
    } else {
        // Vertical ridge — shadow left half, sunlit right half.
        fill_quad(painter, px, py, pw / 2.0, ph, &shadow_fill);
        fill_quad(painter, px + pw / 2.0, py, pw / 2.0, ph, &sunlit_fill);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(px + pw / 2.0, py));
        path.line_to(Vec2::new(px + pw / 2.0, py + ph));
        painter.stroke_path(&path, &ridge_paint, &stroke);
    }
}

/// `Mode::Simple` — flat single-tint fill matching the design
/// doc's "flat tint over the building footprint (default)" entry.
/// One closed `fill_path` over the polygon, no shingle rows, no
/// ridge spokes. Production roofs never go through this path
/// (the emit layer picks Pyramid / Gable per shape); it's the
/// default fallback for unknown styles and the shape that the
/// catalog `synthetic/roofs/styles_seed7.png` Simple column
/// renders.
fn draw_simple_flat(
    polygon: &[(f32, f32)],
    sunlit: &[(u8, u8, u8); 3],
    painter: &mut dyn Painter,
) {
    if polygon.len() < 3 {
        return;
    }
    let mut path = PathOps::new();
    for (i, &(x, y)) in polygon.iter().enumerate() {
        let p = Vec2::new(x, y);
        if i == 0 {
            path.move_to(p);
        } else {
            path.line_to(p);
        }
    }
    path.close();
    // Mid-tone of the sunlit palette — same colour the gable /
    // pyramid algos use for the brighter side. Reads as a clean
    // "single-tint roof tile" against the parchment background.
    let fill = rgb_paint(sunlit[1], 1.0);
    painter.fill_path(&path, &fill, FillRule::Winding);
}

/// `Mode::Dome` — concentric tonal rings reading as a top-down
/// hemisphere. No spokes; each successive ring shrinks toward the
/// centroid and brightens to suggest a lit-from-above curvature.
fn draw_dome_rings(
    polygon: &[(f32, f32)],
    bbox: (f32, f32, f32, f32),
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, pw, ph) = bbox;
    let cx = min_x + pw / 2.0;
    let cy = min_y + ph / 2.0;
    // Outer-to-inner: dark → bright. Using shadow[1], shadow[0],
    // sunlit[0], sunlit[2] gives a 4-stop gradient with the
    // brightest highlight at the top of the dome (centre).
    let stops: [(f32, (u8, u8, u8)); 4] = [
        (1.00, shadow[1]),
        (0.78, shadow[0]),
        (0.55, sunlit[0]),
        (0.30, sunlit[2]),
    ];
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    let stroke = shingle_stroke();
    for (scale, shade) in stops {
        let mut path = PathOps::new();
        for (i, &(x, y)) in polygon.iter().enumerate() {
            let p = Vec2::new(
                cx + (x - cx) * scale,
                cy + (y - cy) * scale,
            );
            if i == 0 {
                path.move_to(p);
            } else {
                path.line_to(p);
            }
        }
        path.close();
        let fill = rgb_paint(shade, 1.0);
        painter.fill_path(&path, &fill, FillRule::Winding);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
}

/// `Mode::WitchHat` — tall narrow conical hat. Same radial-side
/// layout as `Pyramid`, but the apex is shifted upward by 30 % of
/// the bbox height so the silhouette reads as an asymmetric cone.
/// A small bright disc at the apex stands in for the tip
/// poking up through the top-down view.
fn draw_witch_hat_sides(
    polygon: &[(f32, f32)],
    bbox: (f32, f32, f32, f32),
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let n = polygon.len();
    if n == 0 {
        return;
    }
    let (_, _, pw, ph) = bbox;
    let avg_x = polygon.iter().map(|p| p.0).sum::<f32>() / n as f32;
    let avg_y = polygon.iter().map(|p| p.1).sum::<f32>() / n as f32;
    let apex_x = avg_x;
    // Apex sits 30 % of the bbox height above the polygon
    // centroid — gives the cone a tall, leaning-up silhouette
    // distinct from `Pyramid`'s centroid-aligned spine.
    let apex_y = avg_y - ph * 0.30;
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    let stroke = shingle_stroke();
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let mx = (a.0 + b.0) / 2.0;
        let my = (a.1 + b.1) / 2.0;
        let is_shadow = my < avg_y - 1e-3
            || (mx < avg_x - 1e-3 && my < avg_y + 1e-3);
        let palette = if is_shadow { shadow } else { sunlit };
        let fill_rgb = *rng.choice(palette);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(a.0, a.1));
        path.line_to(Vec2::new(b.0, b.1));
        path.line_to(Vec2::new(apex_x, apex_y));
        path.close();
        let fill = rgb_paint(fill_rgb, 1.0);
        painter.fill_path(&path, &fill, FillRule::Winding);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
    // Spokes from each vertex to the offset apex.
    let ridge_paint = rgb_paint((0, 0, 0), 1.0);
    let ridge_stroke_def = ridge_stroke();
    let mut path = PathOps::new();
    for &(vx, vy) in polygon {
        path.move_to(Vec2::new(apex_x, apex_y));
        path.line_to(Vec2::new(vx, vy));
    }
    painter.stroke_path(&path, &ridge_paint, &ridge_stroke_def);
    // Bright apex disc — radius is 8 % of the smaller bbox
    // dimension so it stays proportional across cell sizes.
    let disc_r = pw.min(ph) * 0.08;
    let bright = sunlit[2];
    let disc_paint = rgb_paint(bright, 1.0);
    painter.fill_circle(apex_x, apex_y, disc_r, &disc_paint);
}

fn draw_pyramid_sides(
    polygon: &[(f32, f32)],
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let n = polygon.len();
    if n == 0 {
        return;
    }
    let cx = polygon.iter().map(|p| p.0).sum::<f32>() / n as f32;
    let cy = polygon.iter().map(|p| p.1).sum::<f32>() / n as f32;
    let stroke_paint = rgb_paint((0, 0, 0), SHINGLE_STROKE_OPACITY);
    let stroke = shingle_stroke();
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let mx = (a.0 + b.0) / 2.0;
        let my = (a.1 + b.1) / 2.0;
        let is_shadow = my < cy - 1e-3 || (mx < cx - 1e-3 && my < cy + 1e-3);
        let palette = if is_shadow { shadow } else { sunlit };
        let fill_rgb = *rng.choice(palette);
        let mut path = PathOps::new();
        path.move_to(Vec2::new(a.0, a.1));
        path.line_to(Vec2::new(b.0, b.1));
        path.line_to(Vec2::new(cx, cy));
        path.close();
        let fill = rgb_paint(fill_rgb, 1.0);
        painter.fill_path(&path, &fill, FillRule::Winding);
        painter.stroke_path(&path, &stroke_paint, &stroke);
    }
    // Ridge spokes from centre to each polygon vertex.
    let ridge_paint = rgb_paint((0, 0, 0), 1.0);
    let ridge_stroke_def = ridge_stroke();
    let mut path = PathOps::new();
    for &(vx, vy) in polygon {
        path.move_to(Vec2::new(cx, cy));
        path.line_to(Vec2::new(vx, vy));
    }
    painter.stroke_path(&path, &ridge_paint, &ridge_stroke_def);
}


// ── Region lookup + dispatch entry ─────────────────────────────


fn find_region<'a>(
    fir: &FloorIR<'a>,
    region_ref: &str,
) -> Option<Region<'a>> {
    let regions = fir.regions()?;
    regions.iter().find(|r| r.id() == region_ref)
}

fn polygon_coords(region: &Region<'_>) -> Vec<(f32, f32)> {
    let outline = match region.outline() {
        Some(o) => o,
        None => return Vec::new(),
    };
    let verts = match outline.vertices() {
        Some(v) => v,
        None => return Vec::new(),
    };
    verts.iter().map(|v| (v.x(), v.y())).collect()
}

/// Walk the roof region's outline into a `PathOps` clip path.
/// Mirrors the legacy `build_clip_mask` (which built a tiny-skia
/// `Mask` from the same outline) — the SkiaPainter intersects the
/// clip via `Mask::fill_path`/`intersect_path` internally so the
/// pixel-level clipping semantics are preserved. Returns `None`
/// when the region has no outline; the caller drops the clip and
/// paints unclipped.
fn build_clip_pathops(region: &Region<'_>) -> Option<PathOps> {
    let outline = region.outline()?;
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

/// Dispatch one tile pattern over `bbox`, tiling in screen axis.
/// An unknown trailing `RoofTilePattern` byte is the geometry-
/// only no-op (the test-suite baseline).
fn paint_pattern(
    sub_pattern: RoofTilePattern,
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    match sub_pattern {
        RoofTilePattern::Fishscale => paint_fishscale(bbox, palette, rng, painter),
        RoofTilePattern::Thatch => paint_thatch(bbox, palette, rng, painter),
        RoofTilePattern::Pantile => paint_pantile(bbox, palette, rng, painter),
        RoofTilePattern::Slate => paint_slate(bbox, palette, rng, painter),
        RoofTilePattern::Shingle => paint_shingle(bbox, palette, rng, painter),
        _ => {}
    }
}

/// Whether a `RoofTilePattern` byte names a real texture (the
/// five patterns) versus the geometry-only no-op fallback.
fn is_textured(sub_pattern: RoofTilePattern) -> bool {
    matches!(
        sub_pattern,
        RoofTilePattern::Fishscale
            | RoofTilePattern::Thatch
            | RoofTilePattern::Pantile
            | RoofTilePattern::Slate
            | RoofTilePattern::Shingle
    )
}

/// Phase 4 — gable plane-relative orientation (top-down). The
/// ridge is a divider: the pattern on one half is the mirror
/// image of the other across the ridge line. Each half is
/// painted into its own screen-space clip window; the second
/// half draws the *same* pattern (re-seeded identically) under a
/// reflection transform so the two textures meet symmetrically
/// at the ridge with no foreshortening. A vertical ridge
/// (`!horizontal`) mirrors left↔right; a horizontal ridge mirrors
/// top↔bottom.
///
/// Half A (the top / left side) takes the `shadow` palette and
/// half B (bottom / right) the `sunlit` one — the same split
/// `draw_gable_sides` shades the geometry with, so the opaque
/// pattern carries the roof's volume instead of flattening it.
fn paint_gable_pattern(
    sub_pattern: RoofTilePattern,
    min_x: f32,
    min_y: f32,
    pw: f32,
    ph: f32,
    horizontal: bool,
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    seed: u64,
    painter: &mut dyn Painter,
) {
    let (half_bbox, a_rect, b_rect, mirror) = if horizontal {
        let mid = min_y + ph / 2.0;
        (
            (min_x, min_y, pw, ph / 2.0),
            (min_x, min_y, pw, ph / 2.0),
            (min_x, mid, pw, ph / 2.0),
            reflect_y(mid),
        )
    } else {
        let mid = min_x + pw / 2.0;
        (
            (min_x, min_y, pw / 2.0, ph),
            (min_x, min_y, pw / 2.0, ph),
            (mid, min_y, pw / 2.0, ph),
            reflect_x(mid),
        )
    };
    // Half A — natural orientation, clipped to its half.
    painter.push_clip(
        &rect_path(a_rect.0, a_rect.1, a_rect.2, a_rect.3),
        FillRule::Winding,
    );
    let mut rng_a = RoofRng::new(seed);
    paint_pattern(sub_pattern, half_bbox, shadow, &mut rng_a, painter);
    painter.pop_clip();
    // Half B — the mirror of A. Clip in screen space first (so the
    // window is the true opposite half), then reflect the drawing.
    painter.push_clip(
        &rect_path(b_rect.0, b_rect.1, b_rect.2, b_rect.3),
        FillRule::Winding,
    );
    painter.push_transform(mirror);
    let mut rng_b = RoofRng::new(seed);
    paint_pattern(sub_pattern, half_bbox, sunlit, &mut rng_b, painter);
    painter.pop_transform();
    painter.pop_clip();
}

/// Phase 4 — faceted plane-relative orientation (top-down) for
/// `Pyramid` / `WitchHat`. Each facet is the triangle
/// `(polygon[i], polygon[i+1], apex)`. The pattern is rotated
/// into that facet's local frame: local `x` runs along the outer
/// (eave) edge `a → b`, local `y` runs from the eave toward the
/// apex. The pattern is re-seeded identically per facet so the
/// texture rotates face-by-face with radial consistency, clipped
/// to the facet triangle. No foreshortening (uniform affine).
///
/// Each facet takes the `shadow` or `sunlit` palette by the same
/// midpoint-vs-centroid test `draw_pyramid_sides` shades the
/// geometry with (`facet_is_shadow`), so the opaque pattern keeps
/// the roof's volume instead of flattening every face to one tint.
fn paint_faceted_pattern(
    sub_pattern: RoofTilePattern,
    polygon: &[(f32, f32)],
    apex: (f32, f32),
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    seed: u64,
    painter: &mut dyn Painter,
) {
    let n = polygon.len();
    for i in 0..n {
        let a = polygon[i];
        let b = polygon[(i + 1) % n];
        let ex = b.0 - a.0;
        let ey = b.1 - a.1;
        let eave_len = (ex * ex + ey * ey).sqrt();
        if eave_len < 1e-3 {
            continue;
        }
        let ux = ex / eave_len;
        let uy = ey / eave_len;
        // Eave-normal, oriented toward the apex.
        let mut nx = -uy;
        let mut ny = ux;
        let wx = apex.0 - a.0;
        let wy = apex.1 - a.1;
        let mut facet_h = wx * nx + wy * ny;
        if facet_h < 0.0 {
            nx = -nx;
            ny = -ny;
            facet_h = -facet_h;
        }
        if facet_h < 1e-3 {
            continue;
        }
        // Per-facet tone on a continuous gradient: blend the
        // shadow → sunlit palettes by the facet's angle around
        // the centroid. Adjacent facets differ only slightly, so
        // the roof reads as a smooth radial gradient and the
        // small clip overlap at seams is invisible.
        let mx = (a.0 + b.0) / 2.0;
        let my = (a.1 + b.1) / 2.0;
        let tone = facet_tone(mx - apex.0, my - apex.1);
        let facet_palette = lerp_palette(shadow, sunlit, tone);
        // local (x, y) → screen: a + x·û + y·n̂.
        let frame = Transform {
            sx: ux,
            kx: nx,
            tx: a.0,
            ky: uy,
            sy: ny,
            ty: a.1,
        };
        // Clip to the facet triangle, with the eave corners
        // pushed outward *from the apex* (the apex vertex stays
        // pinned). This widens the facet enough that adjacent
        // facets meet cleanly along the shared spoke while the
        // apex is NOT extended past itself — inflating about the
        // triangle centroid used to overshoot the true apex,
        // producing a pinwheel of mis-shaped wedges right at the
        // convergence point. The outer silhouette envelope still
        // bounds the eave overflow; the frame is unchanged so
        // orientation stays exact.
        const FACET_CLIP_INFLATE: f32 = 1.06;
        let infl = |p: (f32, f32)| -> Vec2 {
            Vec2::new(
                apex.0 + (p.0 - apex.0) * FACET_CLIP_INFLATE,
                apex.1 + (p.1 - apex.1) * FACET_CLIP_INFLATE,
            )
        };
        let mut tri = PathOps::new();
        tri.move_to(infl(a));
        tri.line_to(infl(b));
        tri.line_to(Vec2::new(apex.0, apex.1));
        tri.close();
        painter.push_clip(&tri, FillRule::Winding);
        painter.push_transform(frame);
        let mut rng = RoofRng::new(seed);
        // Paint an oversized blanket, not just the exact
        // eave_len × facet_h rectangle: the facet triangle tapers
        // to a point at the apex, so tiles laid only to facet_h
        // leave thin radial slivers along the converging spokes.
        // Overshooting past the apex (and a little past both eave
        // ends) lets the inflated triangle clip carve a fully
        // covered facet, so the geometry's bold ridge spokes stay
        // hidden. Clip + outer envelope bound the overflow.
        const PAD: f32 = 0.15;
        const APEX_OVERSHOOT: f32 = 1.6;
        paint_pattern(
            sub_pattern,
            (
                -eave_len * PAD,
                -facet_h * PAD,
                eave_len * (1.0 + 2.0 * PAD),
                facet_h * APEX_OVERSHOOT,
            ),
            &facet_palette,
            &mut rng,
            painter,
        );
        painter.pop_transform();
        painter.pop_clip();
    }
}

/// Concentric ring scales for the dome — must match the tonal
/// stops `draw_dome_rings` insets the geometry at, so the pattern
/// bands line up with the shaded rings.
const DOME_RING_SCALES: [f32; 4] = [1.00, 0.78, 0.55, 0.30];

/// Scale a polygon toward `(cx, cy)` by `s` (s = 1 keeps it,
/// s → 0 collapses it to the centre).
fn scaled_polygon(
    polygon: &[(f32, f32)],
    cx: f32,
    cy: f32,
    s: f32,
) -> Vec<(f32, f32)> {
    polygon
        .iter()
        .map(|&(x, y)| (cx + (x - cx) * s, cy + (y - cy) * s))
        .collect()
}

fn append_ring(path: &mut PathOps, ring: &[(f32, f32)]) {
    for (i, &(x, y)) in ring.iter().enumerate() {
        let p = Vec2::new(x, y);
        if i == 0 {
            path.move_to(p);
        } else {
            path.line_to(p);
        }
    }
    path.close();
}

/// Phase 4 — dome concentric-ring orientation (top-down). The
/// pattern follows the dome's tonal rings: it is banded into the
/// same concentric annuli `draw_dome_rings` shades (one EvenOdd
/// outer-minus-inner clip per band), and within each band the
/// faceted frame lays the texture tangent to the rim so it
/// curves around the dome instead of tiling a straight grid.
///
/// Volume comes from the band gradient: the two outer bands take
/// the `shadow` palette and the two inner ones the `sunlit`
/// palette, echoing the dark-rim → bright-centre tonal stops
/// `draw_dome_rings` shades the geometry with.
fn paint_dome_pattern(
    sub_pattern: RoofTilePattern,
    polygon: &[(f32, f32)],
    bbox: (f32, f32, f32, f32),
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    seed: u64,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, pw, ph) = bbox;
    let cx = min_x + pw / 2.0;
    let cy = min_y + ph / 2.0;
    // Band boundaries: each tonal ring scale, plus the centre.
    let mut bounds: Vec<f32> = DOME_RING_SCALES.to_vec();
    bounds.push(0.0);
    for w in 0..bounds.len() - 1 {
        let s_out = bounds[w];
        let s_in = bounds[w + 1];
        let outer = scaled_polygon(polygon, cx, cy, s_out);
        // Annular clip window: outer ring minus inner ring under
        // the EvenOdd rule (the innermost band's inner ring
        // collapses to the centre, leaving a full disc).
        let mut clip = PathOps::new();
        append_ring(&mut clip, &outer);
        if s_in > 0.0 {
            let inner = scaled_polygon(polygon, cx, cy, s_in);
            append_ring(&mut clip, &inner);
        }
        // Continuous dark-rim → bright-centre gradient: blend the
        // shadow → sunlit palettes by the band's depth so each
        // ring steps smoothly toward the lit centre. Both palette
        // args are the band tone, so the per-facet split inside
        // stays a uniform ring (the volume here is concentric, not
        // radial).
        let n_bands = (bounds.len() - 1) as f32;
        let t = w as f32 / (n_bands - 1.0).max(1.0);
        let band = lerp_palette(shadow, sunlit, t);
        painter.push_clip(&clip, FillRule::EvenOdd);
        paint_faceted_pattern(
            sub_pattern, &outer, (cx, cy), &band, &band, seed, painter,
        );
        painter.pop_clip();
    }
}

/// Polygon-driven inner roof painter — invoked by the canonical
/// RoofOp dispatch (`super::roof_op::draw`). The caller looks the
/// region up in `regions`, extracts the polygon + shape_tag +
/// style + sub_pattern + tint + seed, builds a clip path, and
/// calls here.
///
/// `style` selects the per-style geometry. The emit pipeline
/// picks `Pyramid` for square / octagon / circle and `Gable` for
/// wide-rect / L-shape footprints, matching the legacy
/// shape-driven dispatch byte-for-byte. `Simple` / `Dome` /
/// `WitchHat` are catalog-only styles for now — generators have
/// to opt into them explicitly.
///
/// `sub_pattern` is the `RoofTilePattern` texture overlay. The
/// five patterns (Shingle — the default organic running-bond —
/// plus Fishscale / Thatch / Pantile / Slate) paint a tile
/// texture on top of the geometry's base, sharing the same
/// polygon clip envelope. An unknown trailing byte falls through
/// to a geometry-only render.
pub(super) fn draw_roof_polygon(
    painter: &mut dyn Painter,
    polygon: &[(f32, f32)],
    style: RoofStyle,
    sub_pattern: RoofTilePattern,
    tint: &str,
    seed: u64,
    clip: Option<&PathOps>,
) {
    if polygon.len() < 3 {
        return;
    }
    let mut rng = RoofRng::new(seed);
    let sunlit = shade_palette(tint, true);
    let shadow = shade_palette(tint, false);
    let mode = mode_for_style(style);
    let (mut min_x, mut max_x) = (f32::INFINITY, f32::NEG_INFINITY);
    let (mut min_y, mut max_y) = (f32::INFINITY, f32::NEG_INFINITY);
    for &(x, y) in polygon {
        if x < min_x { min_x = x; }
        if x > max_x { max_x = x; }
        if y < min_y { min_y = y; }
        if y > max_y { max_y = y; }
    }
    let pw = max_x - min_x;
    let ph = max_y - min_y;
    let bbox = (min_x, min_y, pw, ph);

    let pushed = if let Some(clip_path) = clip {
        painter.push_clip(clip_path, FillRule::EvenOdd);
        true
    } else {
        false
    };
    match mode {
        Mode::Simple => draw_simple_flat(polygon, &sunlit, painter),
        Mode::Pyramid => draw_pyramid_sides(
            polygon, &sunlit, &shadow, &mut rng, painter,
        ),
        Mode::Gable => draw_gable_sides(
            min_x, min_y, pw, ph, pw >= ph,
            &sunlit, &shadow, &mut rng, painter,
        ),
        Mode::Dome => draw_dome_rings(
            polygon, bbox, &sunlit, &shadow, painter,
        ),
        Mode::WitchHat => draw_witch_hat_sides(
            polygon, bbox, &sunlit, &shadow, &mut rng, painter,
        ),
    }
    // Tile-pattern overlay — the five patterns paint over the
    // geometry (clipped to the outline by the active push_clip
    // envelope). Shingle is the production default; an unknown
    // byte is the geometry-only no-op. Gable is plane-relative:
    // the pattern mirrors across the ridge (Phase 4, top-down).
    // Every other style still tiles the bbox in screen axis.
    if is_textured(sub_pattern) {
        match mode {
            Mode::Gable => paint_gable_pattern(
                sub_pattern, min_x, min_y, pw, ph, pw >= ph,
                &sunlit, &shadow, seed, painter,
            ),
            // Pyramid and WitchHat both fan the pattern from the
            // polygon centroid. A centroid is interior, so the
            // facet triangles partition the whole footprint and
            // every facet is healthy — the pattern fully covers
            // the geometry (including WitchHat's bold ridge
            // spokes). WitchHat deliberately does NOT reuse its
            // geometry's *offset* apex here: an apex pushed up by
            // 0.30·ph leaves the near-apex facets degenerate, so
            // those spokes punched through as a dark "sea-urchin".
            // The witch-hat silhouette + spokes + apex disc still
            // come from the geometry; the pattern just needs a
            // clean even fan to blanket it.
            Mode::Pyramid | Mode::WitchHat => {
                let n = polygon.len() as f32;
                let cx = polygon.iter().map(|p| p.0).sum::<f32>() / n;
                let cy = polygon.iter().map(|p| p.1).sum::<f32>() / n;
                paint_faceted_pattern(
                    sub_pattern, polygon, (cx, cy),
                    &sunlit, &shadow, seed, painter,
                );
            }
            Mode::Dome => paint_dome_pattern(
                sub_pattern, polygon, bbox, &sunlit, &shadow, seed, painter,
            ),
            _ => paint_pattern(sub_pattern, bbox, &sunlit, &mut rng, painter),
        }
    }
    if pushed {
        painter.pop_clip();
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_hex_handles_short_strings() {
        assert_eq!(parse_hex("#8A7A5A"), Some((0x8A, 0x7A, 0x5A)));
        assert_eq!(parse_hex("8A7A5A"), Some((0x8A, 0x7A, 0x5A)));
        assert_eq!(parse_hex("#"), None);
    }

    #[test]
    fn shade_palette_brackets_tint() {
        let p = shade_palette("#808080", true);
        // Sunlit factors are 1.15, 1.00, 0.88 — middle entry is
        // exactly the input tint.
        assert_eq!(p[1], (0x80, 0x80, 0x80));
        // Shadow side is darker — middle entry maps to 50% of input.
        let s = shade_palette("#808080", false);
        assert_eq!(s[1], (0x40, 0x40, 0x40));
    }

    #[test]
    fn facet_tone_is_a_smooth_lower_right_gradient() {
        // Light points to screen lower-right (+x, +y), so a facet
        // facing that way is brightest, the opposite darkest, and
        // the sides land in between — monotonic, not a 2-way step.
        let br = facet_tone(1.0, 1.0);
        let tl = facet_tone(-1.0, -1.0);
        let right = facet_tone(1.0, 0.0);
        let top = facet_tone(0.0, -1.0);
        assert!(br > right && right > tl, "monotone br > side > tl");
        assert!(top < right, "upper facet darker than the right one");
        // Clamped so neither extreme blows out / loses texture.
        assert!((0.12..=0.95).contains(&br));
        assert!((0.12..=0.95).contains(&tl));
        // Degenerate direction is neutral mid-tone.
        assert_eq!(facet_tone(0.0, 0.0), 0.5);
    }

    #[test]
    fn lerp_palette_blends_endpoints() {
        let sh = [(0, 0, 0); 3];
        let su = [(200, 100, 50); 3];
        assert_eq!(lerp_palette(&sh, &su, 0.0), sh);
        assert_eq!(lerp_palette(&sh, &su, 1.0), su);
        assert_eq!(lerp_palette(&sh, &su, 0.5)[0], (100, 50, 25));
    }

    #[test]
    fn mode_for_style_dispatches_per_roof_style() {
        assert!(matches!(mode_for_style(RoofStyle::Simple), Mode::Simple));
        assert!(matches!(mode_for_style(RoofStyle::Pyramid), Mode::Pyramid));
        assert!(matches!(mode_for_style(RoofStyle::Gable), Mode::Gable));
        assert!(matches!(mode_for_style(RoofStyle::Dome), Mode::Dome));
        assert!(matches!(mode_for_style(RoofStyle::WitchHat), Mode::WitchHat));
    }

    #[test]
    fn roof_rng_matches_python_first_call() {
        // Sentinel: SplitMix64::from_seed(123).next_u64() must
        // match Python's _SplitMix64(123).next_u64() in
        // ir_to_svg.py — both compute mix(123 + GOLDEN_GAMMA).
        let mut rng = RoofRng::new(123);
        let u = rng.inner.next_u64();
        // Reference value cross-checked against the Python helper.
        assert_eq!(u, 0xb4dc9bd462de412b);
    }

    #[test]
    fn shingle_stroke_uses_documented_width_and_cap() {
        let s = shingle_stroke();
        assert_eq!(s.width, SHINGLE_STROKE_WIDTH);
        assert_eq!(s.line_cap, LineCap::Butt);
    }

    #[test]
    fn ridge_stroke_uses_documented_width_and_cap() {
        let s = ridge_stroke();
        assert_eq!(s.width, RIDGE_WIDTH);
        assert_eq!(s.line_cap, LineCap::Butt);
    }
}
