//! Wood-floor parquet painter — Phase 9.2c port of
//! `nhc/rendering/_floor_detail._render_wood_floor`, ported to the
//! Painter trait in Phase 2.15a of `plans/nhc_pure_ir_plan.md`.
//!
//! Reproduces the per-room overlay rect, the per-room grain
//! streaks (light + dark) and the per-room parquet seam grid
//! against a `Painter`. The handler at
//! `transform/png/floor_detail.rs` constructs a `SkiaPainter` and
//! routes this primitive through `push_clip(building_polygon ∩
//! dungeon_outline)` so grain + seam strokes don't bleed past the
//! chamfered corners of octagon / circle / L-shape buildings.
//!
//! Unlike floor_detail (Phase 2.10) and thematic_detail (Phase
//! 2.11), the wood_floor primitive has **no FFI export** — only
//! `transform/png/floor_detail.rs` consumes it (the wood-floor
//! short-circuit branch). So Phase 2.15a REPLACES the legacy
//! `draw_wood_floor` SVG-string emitter with the new
//! `paint_wood_floor` Painter-trait emitter outright; no dual
//! path is required. Python SVG output has its own
//! `nhc.rendering._floor_detail` module.
//!
//! ## Group-opacity contract (v4e §7)
//!
//! The legacy SVG output wraps:
//!
//! - The per-room overlay rects in `<g>` with no `opacity` attr —
//!   no offscreen-buffer composite needed; the Painter port emits
//!   `fill_rect` calls directly.
//! - Each grain bucket in
//!   `<g fill="none" stroke="…" stroke-width="0.4" opacity="0.35">`
//!   — wraps in `begin_group(WOOD_GRAIN_OPACITY) /
//!   end_group()` so the offscreen-buffer composite handles the
//!   0.35 envelope.
//! - Each seam bucket in
//!   `<g fill="none" stroke="…" stroke-width="0.8">` — no
//!   `opacity` attr; the Painter port emits `stroke_path` calls
//!   directly.
//!
//! **Parity contract (relaxed gate, plan §9.2):** byte-equal-with-
//! legacy is *not* required. The Rust port uses one `Pcg64Mcg`
//! stream over (rooms × strips × grain lines) followed by
//! (rooms × strips × plank lengths) — the same draw-order shape
//! as the legacy `random.Random(seed + 99)` walk, with a different
//! algorithm that produces PSNR-equivalent pixels.

use rand::{Rng, SeedableRng};
use rand_pcg::Pcg64Mcg;

use crate::painter::{
    Color, LineCap, LineJoin, Paint, Painter, PathOps, Rect, Stroke, Vec2,
};

const CELL: f64 = 32.0;

const WOOD_SEAM_WIDTH: f64 = 0.8;
const WOOD_PLANK_WIDTH_PX: f64 = CELL / 4.0;
const WOOD_PLANK_LENGTH_MIN: f64 = CELL * 0.5;
const WOOD_PLANK_LENGTH_MAX: f64 = CELL * 2.5;
const WOOD_GRAIN_STROKE_WIDTH: f64 = 0.4;
/// Group-opacity envelope for grain strokes — lifts the legacy
/// `<g opacity="0.35">` wrapper.
pub const WOOD_GRAIN_OPACITY: f32 = 0.35;
const WOOD_GRAIN_LINES_PER_STRIP: u32 = 2;

/// Per-tone palette: (fill, grain_light, grain_dark, seam).
type WoodTone = (&'static str, &'static str, &'static str, &'static str);
/// Per-species palette: (light, medium, dark) tones.
type WoodSpecies = [WoodTone; 3];

/// 5 wood species × 3 tones each. Mirrors the
/// ``_WOOD_SPECIES`` table in
/// ``nhc/rendering/_floor_detail.py`` byte-for-byte so a building's
/// tone choice is identical between Python and Rust renders.
const WOOD_SPECIES: [WoodSpecies; 5] = [
    // Oak — warm tan, the species closest to the legacy palette.
    [
        ("#C4A076", "#D4B690", "#A88058", "#8A5A2A"),
        ("#B58B5A", "#C4A076", "#8F6540", "#8A5A2A"),
        ("#9B7548", "#AC8A60", "#7A5530", "#683E1E"),
    ],
    // Walnut — deep cocoa, redder hue.
    [
        ("#8C6440", "#A07A55", "#684A2C", "#553820"),
        ("#6E4F32", "#8B6446", "#523820", "#3F2818"),
        ("#553820", "#6E4F32", "#3F2818", "#2A1A10"),
    ],
    // Cherry — reddish brown, slight orange.
    [
        ("#B07A55", "#C49075", "#8E5C3A", "#683C20"),
        ("#9B6442", "#B07A55", "#7A4D2E", "#553820"),
        ("#7E4F32", "#955F44", "#5F3820", "#42261A"),
    ],
    // Pine — pale honey, the lightest species.
    [
        ("#D8B888", "#E6CDA8", "#B8966C", "#9A7A50"),
        ("#C4A176", "#D8B888", "#A48458", "#856A40"),
        ("#A88556", "#BFA070", "#88683C", "#6A5028"),
    ],
    // Weathered grey — silvered teak / driftwood.
    [
        ("#8A8478", "#A09A8E", "#6E695F", "#544F46"),
        ("#6E695F", "#8A8478", "#544F46", "#3D3932"),
        ("#544F46", "#6E695F", "#3D3932", "#2A2723"),
    ],
];

/// FNV-1a 32-bit hash of a UTF-8 byte string. Must match the
/// Python implementation in ``_wood_palette_for_room`` so the
/// species + tone pick stays in sync across rasterisers.
fn fnv1a_32(bytes: &[u8]) -> u32 {
    let mut h: u32 = 2_166_136_261;
    for b in bytes {
        h ^= u32::from(*b);
        h = h.wrapping_mul(16_777_619);
    }
    h
}

/// Resolve ``(fill, grain_light, grain_dark, seam)`` for one wood
/// room. ``building_seed`` picks the species; ``region_ref`` (the
/// room id) picks the tone within that species. Mirror of the
/// Python ``_wood_palette_for_room``.
fn wood_palette_for_room(
    building_seed: u64, region_ref: &str,
) -> WoodTone {
    let species_idx = (building_seed as usize) % WOOD_SPECIES.len();
    let species = &WOOD_SPECIES[species_idx];
    if region_ref.is_empty() {
        return species[1]; // medium
    }
    let h = fnv1a_32(region_ref.as_bytes());
    species[(h as usize) % 3]
}

/// Wood-floor pattern variant. Mirrors
/// ``WOOD_PATTERN_PLANK`` / ``WOOD_PATTERN_BASKET`` in
/// ``_floor_detail.py``.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum WoodPattern {
    Plank,
    Basket,
}

/// Pick the wood layout pattern for a room. Salt the hash with
/// ``"pattern:"`` so the bucket is statistically independent
/// from the palette tone bucket. Mirror of the Python
/// ``_wood_pattern_for_room``.
fn wood_pattern_for_room(region_ref: &str) -> WoodPattern {
    if region_ref.is_empty() {
        return WoodPattern::Plank;
    }
    let salted = format!("pattern:{region_ref}");
    let h = fnv1a_32(salted.as_bytes());
    if h % 3 == 0 { WoodPattern::Basket } else { WoodPattern::Plank }
}

/// One room's parquet rect in tile coordinates (matches the
/// `RectRoom` FB struct shape). ``region_ref`` is the room id;
/// it picks the tone variant within the building's species.
#[derive(Clone, Debug)]
pub struct WoodRoom {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    pub region_ref: String,
}

/// Building-polygon outer outline in pixel coordinates (matches
/// the `Vec2` FB struct shape). Kept for backwards compatibility
/// with the IR shape; the polygon-driven clip mask now lives in
/// the PNG handler at `transform/png/floor_detail.rs` (built into
/// `PathOps` and pushed onto the painter's clip stack before
/// dispatching this primitive).
#[derive(Clone, Copy, Debug)]
pub struct PolyVertex {
    pub x: f64,
    pub y: f64,
}

/// Wood-floor painter entry point — Painter-trait port of
/// `_render_wood_floor`.
///
/// Per design/map_ir.md §6.1, the wood **base fill** is now
/// emitted by `WallsAndFloorsOp` (structural layer), so the
/// per-tile / per-polygon fill rect that used to live here is
/// gone. This handler only emits the per-room overlay rects (the
/// species' tone fill paints over the building-wide WoodFloor
/// base), the per-room grain streaks (group-opacity 0.35) and
/// the parquet plank seams.
///
/// `tiles` and `polygon` are kept on the call signature for
/// backwards compatibility with the IR shape; both are unused
/// inside this primitive — the polygon-driven clip is applied by
/// the caller via `push_clip` before dispatching here.
///
/// `rooms`: per-room rects driving the overlay rect, the grain
/// streak generator and the parquet seam grid.
pub fn paint_wood_floor(
    painter: &mut dyn Painter,
    _tiles: &[(i32, i32)],
    _polygon: &[PolyVertex],
    rooms: &[WoodRoom],
    seed: u64,
) {
    if rooms.is_empty() {
        return;
    }

    let mut rng = Pcg64Mcg::seed_from_u64(seed);

    // Resolve each room's palette ONCE, then route the per-room
    // overlay rect, the grain streaks, and the seam strokes
    // through the matching palette colours. Mirror of the Python
    // ``_draw_wood_floor_from_ir`` Phase 1.26h refactor.
    let palettes: Vec<WoodTone> = rooms
        .iter()
        .map(|r| wood_palette_for_room(seed, &r.region_ref))
        .collect();
    let patterns: Vec<WoodPattern> = rooms
        .iter()
        .map(|r| wood_pattern_for_room(&r.region_ref))
        .collect();

    // Per-room overlay rects. The legacy SVG wraps these in a
    // `<g>` with no `opacity` attr — emit fill_rect calls
    // directly, no group needed.
    for (room, palette) in rooms.iter().zip(palettes.iter()) {
        let fill = palette.0;
        let rx = f64::from(room.x) * CELL;
        let ry = f64::from(room.y) * CELL;
        let rw = f64::from(room.w) * CELL;
        let rh = f64::from(room.h) * CELL;
        painter.fill_rect(
            Rect::new(
                round_legacy_1(rx),
                round_legacy_1(ry),
                round_legacy_1(rw),
                round_legacy_1(rh),
            ),
            &paint_for_hex(fill),
        );
    }

    // Grain — bucket per (light, dark) palette pair. Build the
    // line streams in lock-step with the legacy RNG walk, then
    // emit each non-empty bucket inside one
    // begin_group(WOOD_GRAIN_OPACITY) / end_group() pair —
    // matching the legacy `<g … opacity="0.35">` envelope.
    type GrainBucket = (Vec<GrainLine>, Vec<GrainLine>);
    let mut grain_buckets: Vec<((&str, &str), GrainBucket)> = Vec::new();
    for ((room, palette), pattern) in
        rooms.iter().zip(palettes.iter()).zip(patterns.iter())
    {
        let key = (palette.1, palette.2);
        let bucket = match grain_buckets.iter_mut().find(|(k, _)| *k == key) {
            Some((_, b)) => b,
            None => {
                grain_buckets.push((key, (Vec::new(), Vec::new())));
                &mut grain_buckets.last_mut().unwrap().1
            }
        };
        emit_room_grain(
            room, &mut rng, *pattern, &mut bucket.0, &mut bucket.1,
        );
    }
    for ((light, dark), (light_lines, dark_lines)) in &grain_buckets {
        if !light_lines.is_empty() {
            painter.begin_group(WOOD_GRAIN_OPACITY);
            let stroke = grain_stroke();
            let paint = paint_for_hex(light);
            for line in light_lines {
                stroke_line(painter, line, &paint, &stroke);
            }
            painter.end_group();
        }
        if !dark_lines.is_empty() {
            painter.begin_group(WOOD_GRAIN_OPACITY);
            let stroke = grain_stroke();
            let paint = paint_for_hex(dark);
            for line in dark_lines {
                stroke_line(painter, line, &paint, &stroke);
            }
            painter.end_group();
        }
    }

    // Seams — bucket per palette seam colour. The legacy SVG
    // wraps each bucket in `<g … stroke-width="0.8">` with NO
    // `opacity` attr — emit stroke_path calls directly, no group
    // needed.
    let mut seam_buckets: Vec<(&str, Vec<GrainLine>)> = Vec::new();
    for ((room, palette), pattern) in
        rooms.iter().zip(palettes.iter()).zip(patterns.iter())
    {
        let seam = palette.3;
        let bucket = match seam_buckets.iter_mut().find(|(k, _)| *k == seam) {
            Some((_, b)) => b,
            None => {
                seam_buckets.push((seam, Vec::new()));
                &mut seam_buckets.last_mut().unwrap().1
            }
        };
        emit_room_seams(room, &mut rng, *pattern, bucket);
    }
    for (seam, seam_lines) in &seam_buckets {
        if seam_lines.is_empty() {
            continue;
        }
        let stroke = seam_stroke();
        let paint = paint_for_hex(seam);
        for line in seam_lines {
            stroke_line(painter, line, &paint, &stroke);
        }
    }
}

/// One grain / seam line — endpoints in pixel coords. Carried as
/// `f64` through the per-room emitters so the legacy SVG-string
/// `{:.1}` truncation can land at the same f32 the legacy
/// `parse_path_d` round-trip would have arrived at.
#[derive(Clone, Copy, Debug)]
struct GrainLine {
    x1: f64,
    y1: f64,
    x2: f64,
    y2: f64,
}

fn stroke_line(
    painter: &mut dyn Painter,
    line: &GrainLine,
    paint: &Paint,
    stroke: &Stroke,
) {
    let mut path = PathOps::new();
    path.move_to(Vec2::new(round_legacy_1(line.x1), round_legacy_1(line.y1)));
    path.line_to(Vec2::new(round_legacy_1(line.x2), round_legacy_1(line.y2)));
    painter.stroke_path(&path, paint, stroke);
}

fn grain_stroke() -> Stroke {
    Stroke {
        width: WOOD_GRAIN_STROKE_WIDTH as f32,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}

fn seam_stroke() -> Stroke {
    Stroke {
        width: WOOD_SEAM_WIDTH as f32,
        line_cap: LineCap::Butt,
        line_join: LineJoin::Miter,
    }
}

fn emit_room_grain(
    room: &WoodRoom, rng: &mut Pcg64Mcg,
    pattern: WoodPattern,
    light: &mut Vec<GrainLine>, dark: &mut Vec<GrainLine>,
) {
    if pattern == WoodPattern::Basket {
        emit_room_grain_basket(room, rng, light, dark);
        return;
    }
    let x0 = f64::from(room.x) * CELL;
    let y0 = f64::from(room.y) * CELL;
    let x1 = f64::from(room.x + room.w) * CELL;
    let y1 = f64::from(room.y + room.h) * CELL;
    let horizontal = room.w >= room.h;
    let width = WOOD_PLANK_WIDTH_PX;

    if horizontal {
        let mut y = y0;
        while y < y1 {
            let strip_bot = (y + width).min(y1);
            let span = strip_bot - y;
            if span <= 0.5 {
                y += width;
                continue;
            }
            for i in 0..WOOD_GRAIN_LINES_PER_STRIP {
                let gy = rng.gen_range((y + span * 0.15)..(strip_bot - span * 0.15));
                let dest = if i % 2 == 0 { &mut *light } else { &mut *dark };
                dest.push(GrainLine { x1: x0, y1: gy, x2: x1, y2: gy });
            }
            y += width;
        }
    } else {
        let mut x = x0;
        while x < x1 {
            let strip_right = (x + width).min(x1);
            let span = strip_right - x;
            if span <= 0.5 {
                x += width;
                continue;
            }
            for i in 0..WOOD_GRAIN_LINES_PER_STRIP {
                let gx = rng.gen_range((x + span * 0.15)..(strip_right - span * 0.15));
                let dest = if i % 2 == 0 { &mut *light } else { &mut *dark };
                dest.push(GrainLine { x1: gx, y1: y0, x2: gx, y2: y1 });
            }
            x += width;
        }
    }
}

fn emit_room_seams(
    room: &WoodRoom, rng: &mut Pcg64Mcg,
    pattern: WoodPattern,
    seams: &mut Vec<GrainLine>,
) {
    if pattern == WoodPattern::Basket {
        emit_room_seams_basket(room, seams);
        return;
    }
    let x0 = f64::from(room.x) * CELL;
    let y0 = f64::from(room.y) * CELL;
    let x1 = f64::from(room.x + room.w) * CELL;
    let y1 = f64::from(room.y + room.h) * CELL;
    let horizontal = room.w >= room.h;
    let width = WOOD_PLANK_WIDTH_PX;

    if horizontal {
        let mut y = y0;
        while y < y1 {
            let strip_bot = (y + width).min(y1);
            let mut x_end = x0
                + rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            while x_end < x1 {
                seams.push(GrainLine {
                    x1: x_end, y1: y, x2: x_end, y2: strip_bot,
                });
                x_end +=
                    rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            }
            y += width;
            if y < y1 {
                seams.push(GrainLine {
                    x1: x0, y1: y, x2: x1, y2: y,
                });
            }
        }
    } else {
        let mut x = x0;
        while x < x1 {
            let strip_right = (x + width).min(x1);
            let mut y_end = y0
                + rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            while y_end < y1 {
                seams.push(GrainLine {
                    x1: x, y1: y_end, x2: strip_right, y2: y_end,
                });
                y_end +=
                    rng.gen_range(WOOD_PLANK_LENGTH_MIN..WOOD_PLANK_LENGTH_MAX);
            }
            x += width;
            if x < x1 {
                seams.push(GrainLine {
                    x1: x, y1: y0, x2: x, y2: y1,
                });
            }
        }
    }
}

/// Basket-weave grain — 1-tile cells with planks alternating
/// horizontal / vertical orientation. Mirror of the Python
/// basket-weave branch in ``_draw_wood_floor_from_ir``.
fn emit_room_grain_basket(
    room: &WoodRoom, rng: &mut Pcg64Mcg,
    light: &mut Vec<GrainLine>, dark: &mut Vec<GrainLine>,
) {
    let rx = f64::from(room.x) * CELL;
    let ry = f64::from(room.y) * CELL;
    let width = WOOD_PLANK_WIDTH_PX;
    for cy in 0..room.h {
        for cx in 0..room.w {
            let cell_x = rx + f64::from(cx) * CELL;
            let cell_y = ry + f64::from(cy) * CELL;
            let cell_horizontal = (cx + cy) % 2 == 0;
            if cell_horizontal {
                let mut y = cell_y;
                while y < cell_y + CELL {
                    let strip_bot = (y + width).min(cell_y + CELL);
                    let span = strip_bot - y;
                    if span <= 0.5 {
                        y += width;
                        continue;
                    }
                    for i in 0..WOOD_GRAIN_LINES_PER_STRIP {
                        let gy = rng.gen_range(
                            (y + span * 0.15)..(strip_bot - span * 0.15),
                        );
                        let dest = if i % 2 == 0 { &mut *light } else { &mut *dark };
                        dest.push(GrainLine {
                            x1: cell_x, y1: gy,
                            x2: cell_x + CELL, y2: gy,
                        });
                    }
                    y += width;
                }
            } else {
                let mut x = cell_x;
                while x < cell_x + CELL {
                    let strip_right = (x + width).min(cell_x + CELL);
                    let span = strip_right - x;
                    if span <= 0.5 {
                        x += width;
                        continue;
                    }
                    for i in 0..WOOD_GRAIN_LINES_PER_STRIP {
                        let gx = rng.gen_range(
                            (x + span * 0.15)..(strip_right - span * 0.15),
                        );
                        let dest = if i % 2 == 0 { &mut *light } else { &mut *dark };
                        dest.push(GrainLine {
                            x1: gx, y1: cell_y,
                            x2: gx, y2: cell_y + CELL,
                        });
                    }
                    x += width;
                }
            }
        }
    }
}

/// Basket-weave seams — 3 internal seams + cell boundary seams
/// per cell. Mirror of ``_basket_weave_seams_from_room_ir`` in
/// the Python consumer.
fn emit_room_seams_basket(room: &WoodRoom, seams: &mut Vec<GrainLine>) {
    let rx = f64::from(room.x) * CELL;
    let ry = f64::from(room.y) * CELL;
    let width = WOOD_PLANK_WIDTH_PX;
    for cy in 0..room.h {
        for cx in 0..room.w {
            let cell_x = rx + f64::from(cx) * CELL;
            let cell_y = ry + f64::from(cy) * CELL;
            let cell_horizontal = (cx + cy) % 2 == 0;
            if cell_horizontal {
                let mut k = 1.0_f64;
                while k * width < CELL {
                    let sy = cell_y + k * width;
                    seams.push(GrainLine {
                        x1: cell_x, y1: sy,
                        x2: cell_x + CELL, y2: sy,
                    });
                    k += 1.0;
                }
                seams.push(GrainLine {
                    x1: cell_x, y1: cell_y,
                    x2: cell_x, y2: cell_y + CELL,
                });
                seams.push(GrainLine {
                    x1: cell_x + CELL, y1: cell_y,
                    x2: cell_x + CELL, y2: cell_y + CELL,
                });
            } else {
                let mut k = 1.0_f64;
                while k * width < CELL {
                    let sx = cell_x + k * width;
                    seams.push(GrainLine {
                        x1: sx, y1: cell_y,
                        x2: sx, y2: cell_y + CELL,
                    });
                    k += 1.0;
                }
                seams.push(GrainLine {
                    x1: cell_x, y1: cell_y,
                    x2: cell_x + CELL, y2: cell_y,
                });
                seams.push(GrainLine {
                    x1: cell_x, y1: cell_y + CELL,
                    x2: cell_x + CELL, y2: cell_y + CELL,
                });
            }
        }
    }
}

/// Mirror the legacy SVG-string path's `{:.1}` truncation +
/// reparse. Rust's `{:.1}` uses banker's rounding, matching
/// Python's `f"{v:.1f}"` — so the round-trip lands at the same
/// f32 value the SVG-string path would have arrived at via
/// `format` → `parse_path_d`.
fn round_legacy_1(v: f64) -> f32 {
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

    fn rooms(rs: &[(i32, i32, i32, i32)]) -> Vec<WoodRoom> {
        rs.iter()
            .enumerate()
            .map(|(i, &(x, y, w, h))| WoodRoom {
                x, y, w, h,
                region_ref: format!("r{i}"),
            })
            .collect()
    }

    fn tiles(n: i32) -> Vec<(i32, i32)> {
        (0..n).flat_map(|y| (0..n).map(move |x| (x, y))).collect()
    }

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
        FillRect(Rect, Paint),
        StrokePath(Paint, Stroke),
        BeginGroup(u32),
        EndGroup,
    }

    impl Painter for CaptureCalls {
        fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
            self.calls.push(Call::FillRect(rect, *paint));
        }
        fn stroke_rect(&mut self, _: Rect, _: &Paint, _: &Stroke) {}
        fn fill_circle(&mut self, _: f32, _: f32, _: f32, _: &Paint) {}
        fn fill_ellipse(
            &mut self, _: f32, _: f32, _: f32, _: f32, _: &Paint,
        ) {
        }
        fn fill_polygon(&mut self, _: &[Vec2], _: &Paint, _: FillRule) {}
        fn stroke_polyline(&mut self, _: &[Vec2], _: &Paint, _: &Stroke) {}
        fn fill_path(&mut self, _: &PathOps, _: &Paint, _: FillRule) {}
        fn stroke_path(&mut self, _: &PathOps, paint: &Paint, stroke: &Stroke) {
            self.calls.push(Call::StrokePath(*paint, *stroke));
        }
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
    }

    impl CaptureCalls {
        fn fill_rect_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::FillRect(_, _)))
                .count()
        }
        fn stroke_path_count(&self) -> usize {
            self.calls
                .iter()
                .filter(|c| matches!(c, Call::StrokePath(_, _)))
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
    }

    // ── Empty-input contract ──────────────────────────────────

    #[test]
    fn empty_rooms_emit_no_painter_calls() {
        let mut painter = CaptureCalls::default();
        paint_wood_floor(&mut painter, &[], &[], &[], 99);
        assert!(painter.calls.is_empty());
        assert_eq!(painter.group_depth, 0);
    }

    // ── Group balance ─────────────────────────────────────────

    #[test]
    fn paint_emits_balanced_groups() {
        let mut painter = CaptureCalls::default();
        let r = rooms(&[(0, 0, 5, 5)]);
        paint_wood_floor(&mut painter, &[], &[], &r, 99);
        assert_eq!(painter.begin_group_count(), painter.end_group_count());
        assert_eq!(painter.group_depth, 0);
        assert!(painter.max_group_depth <= 1);
    }

    // ── Documented bucket opacity ─────────────────────────────

    #[test]
    fn grain_groups_use_documented_opacity() {
        let mut painter = CaptureCalls::default();
        let r = rooms(&[(0, 0, 5, 5)]);
        paint_wood_floor(&mut painter, &[], &[], &r, 99);
        // Every begin_group call is a grain bucket — must carry
        // WOOD_GRAIN_OPACITY (0.35).
        let expected = (WOOD_GRAIN_OPACITY * 100.0).round() as u32;
        let ops = painter.opacities();
        assert!(!ops.is_empty(), "expected at least one grain group");
        for op in ops {
            assert_eq!(op, expected);
        }
    }

    // ── Per-room overlay rect ─────────────────────────────────

    #[test]
    fn paint_emits_one_overlay_rect_per_room() {
        let mut painter = CaptureCalls::default();
        let r = rooms(&[(0, 0, 4, 4), (5, 0, 3, 3), (0, 5, 6, 2)]);
        paint_wood_floor(&mut painter, &[], &[], &r, 99);
        assert_eq!(painter.fill_rect_count(), r.len());
    }

    #[test]
    fn overlay_rect_carries_species_palette_fill() {
        // seed=99 → species_idx 99 % 5 == 4 (weathered grey).
        let mut painter = CaptureCalls::default();
        let r = rooms(&[(0, 0, 5, 5)]);
        paint_wood_floor(&mut painter, &[], &[], &r, 99);
        let rect_paints: Vec<Paint> = painter
            .calls
            .iter()
            .filter_map(|c| match c {
                Call::FillRect(_, p) => Some(*p),
                _ => None,
            })
            .collect();
        assert_eq!(rect_paints.len(), 1);
        let species = &WOOD_SPECIES[99 % WOOD_SPECIES.len()];
        let valid_fills: Vec<(u8, u8, u8)> = species
            .iter()
            .map(|tone| parse_hex_rgb(tone.0))
            .collect();
        let p = rect_paints[0];
        let actual = (p.color.r, p.color.g, p.color.b);
        assert!(
            valid_fills.contains(&actual),
            "rect fill {:?} not in species palette {:?}",
            actual, valid_fills,
        );
    }

    // ── Stroke colours ────────────────────────────────────────

    #[test]
    fn grain_and_seam_strokes_carry_species_palette_colours() {
        let mut painter = CaptureCalls::default();
        let r = rooms(&[(0, 0, 5, 5)]);
        paint_wood_floor(&mut painter, &[], &[], &r, 99);
        let stroke_paints: Vec<Paint> = painter
            .calls
            .iter()
            .filter_map(|c| match c {
                Call::StrokePath(p, _) => Some(*p),
                _ => None,
            })
            .collect();
        assert!(!stroke_paints.is_empty());
        let species = &WOOD_SPECIES[99 % WOOD_SPECIES.len()];
        let valid: Vec<(u8, u8, u8)> = species
            .iter()
            .flat_map(|tone| {
                vec![
                    parse_hex_rgb(tone.1),
                    parse_hex_rgb(tone.2),
                    parse_hex_rgb(tone.3),
                ]
            })
            .collect();
        for paint in stroke_paints {
            let actual = (paint.color.r, paint.color.g, paint.color.b);
            assert!(
                valid.contains(&actual),
                "stroke {:?} not in species palette {:?}",
                actual, valid,
            );
        }
    }

    #[test]
    fn grain_and_seam_strokes_use_documented_widths() {
        let mut painter = CaptureCalls::default();
        let r = rooms(&[(0, 0, 5, 5)]);
        paint_wood_floor(&mut painter, &[], &[], &r, 99);
        let strokes: Vec<Stroke> = painter
            .calls
            .iter()
            .filter_map(|c| match c {
                Call::StrokePath(_, s) => Some(*s),
                _ => None,
            })
            .collect();
        // Every stroke is either a grain stroke (0.4) or a seam
        // stroke (0.8) — no other widths.
        let grain_w = WOOD_GRAIN_STROKE_WIDTH as f32;
        let seam_w = WOOD_SEAM_WIDTH as f32;
        for s in strokes {
            assert!(
                (s.width - grain_w).abs() < 1e-6
                    || (s.width - seam_w).abs() < 1e-6,
                "unexpected stroke width: {}", s.width,
            );
        }
    }

    // ── Determinism / divergence ──────────────────────────────

    #[test]
    fn deterministic_for_same_seed() {
        let t = tiles(5);
        let r = rooms(&[(0, 0, 5, 5)]);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_wood_floor(&mut a, &t, &[], &r, 99);
        paint_wood_floor(&mut b, &t, &[], &r, 99);
        assert_eq!(a.calls.len(), b.calls.len());
        assert_eq!(a.fill_rect_count(), b.fill_rect_count());
        assert_eq!(a.stroke_path_count(), b.stroke_path_count());
    }

    #[test]
    fn different_seeds_diverge() {
        let t = tiles(5);
        let r = rooms(&[(0, 0, 5, 5)]);
        let mut a = CaptureCalls::default();
        let mut b = CaptureCalls::default();
        paint_wood_floor(&mut a, &t, &[], &r, 99);
        paint_wood_floor(&mut b, &t, &[], &r, 7);
        // Different seeds → palette differs, so rect fill differs;
        // RNG stream differs, so stroke colours / counts differ.
        // Compare the full call sequences.
        assert_ne!(a.calls, b.calls);
    }

    // ── Hash table parity ─────────────────────────────────────

    #[test]
    fn fnv1a_matches_python_implementation() {
        // Spot-check the FNV-1a hash against a couple of known
        // Python outputs (computed via the reference function).
        // Stability across implementations is the contract.
        assert_eq!(fnv1a_32(b""), 2_166_136_261);
        assert_eq!(fnv1a_32(b"r1"), 0x0C53FDAC);
        assert_eq!(fnv1a_32(b"room.0"), 0x4D7D60E4);
    }
}
