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
    Stroke, Vec2,
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

/// `Slate` — small rectangular tiles in a tight running-bond.
/// Smaller than `draw_shingle_region`'s default shingles
/// (8 × 6 instead of 14 × 5) so the texture reads visibly
/// distinct from a Plain Gable when overlaid.
fn paint_slate(
    bbox: (f32, f32, f32, f32),
    palette: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let (min_x, min_y, w, h) = bbox;
    let tile_w: f32 = 8.0;
    let tile_h: f32 = 6.0;
    let mut row: i32 = 0;
    let mut cy = min_y;
    while cy < min_y + h {
        let off = if row & 1 == 0 { 0.0 } else { tile_w / 2.0 };
        let mut x = min_x - tile_w + off;
        while x < min_x + w + tile_w {
            let shade = *rng.choice(palette);
            painter.fill_rect(
                PRect::new(x, cy, tile_w - 0.6, tile_h - 0.6),
                &rgb_paint(shade, 1.0),
            );
            x += tile_w;
        }
        cy += tile_h;
        row += 1;
    }
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

fn draw_gable_sides(
    px: f32, py: f32, pw: f32, ph: f32,
    horizontal: bool,
    sunlit: &[(u8, u8, u8); 3],
    shadow: &[(u8, u8, u8); 3],
    rng: &mut RoofRng,
    painter: &mut dyn Painter,
) {
    let ridge_paint = rgb_paint((0, 0, 0), 1.0);
    let stroke = ridge_stroke();
    if horizontal {
        // Horizontal ridge — vertical courses (long axis runs
        // perpendicular to the ridge).
        draw_shingle_region(px, py, pw, ph / 2.0, shadow, rng, painter, true);
        draw_shingle_region(
            px, py + ph / 2.0, pw, ph / 2.0, sunlit, rng, painter, true,
        );
        let mut path = PathOps::new();
        path.move_to(Vec2::new(px, py + ph / 2.0));
        path.line_to(Vec2::new(px + pw, py + ph / 2.0));
        painter.stroke_path(&path, &ridge_paint, &stroke);
    } else {
        // Vertical ridge — horizontal courses (default).
        draw_shingle_region(px, py, pw / 2.0, ph, shadow, rng, painter, false);
        draw_shingle_region(
            px + pw / 2.0, py, pw / 2.0, ph, sunlit, rng, painter, false,
        );
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
/// `sub_pattern` is the optional `RoofTilePattern` overlay.
/// `Plain` (default) is byte-identical to the legacy output —
/// no overlay paints. The four non-Plain patterns (Fishscale /
/// Thatch / Pantile / Slate) paint a tile texture on top of the
/// geometry's base, sharing the same polygon clip envelope.
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
    // Tile-pattern overlay — Plain is the no-op default; the
    // four non-Plain patterns paint over the polygon's bbox
    // (clipped to the outline by the active push_clip envelope).
    match sub_pattern {
        RoofTilePattern::Fishscale => {
            paint_fishscale(bbox, &sunlit, &mut rng, painter);
        }
        RoofTilePattern::Thatch => {
            paint_thatch(bbox, &sunlit, &mut rng, painter);
        }
        RoofTilePattern::Pantile => {
            paint_pantile(bbox, &sunlit, &mut rng, painter);
        }
        RoofTilePattern::Slate => {
            paint_slate(bbox, &sunlit, &mut rng, painter);
        }
        // Plain + any unknown trailing variant leave the geometry
        // untouched.
        _ => {}
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
