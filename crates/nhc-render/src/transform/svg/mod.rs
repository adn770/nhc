//! IR → SVG via the [`SvgPainter`] backend. Phase 2.16 of
//! `plans/nhc_pure_ir_plan.md`.
//!
//! Mirrors [`super::png::floor_ir_to_png`] shape: parse a
//! `FloorIR` FlatBuffer, walk the same `ops[]` array through the
//! same shared [`super::png::dispatch_ops`], dispatch every op
//! against an [`SvgPainter`] instance instead of the
//! [`SkiaPainter`]. The painter accumulates SVG elements into a
//! body string and `<clipPath>` defs into a defs string; this
//! entry point wraps both in the canonical `<svg>` envelope.
//!
//! The SVG body coordinates are in raw IR pixel space (no
//! `translate(padding) + scale` baked in). The outer
//! `<g transform="translate(...) scale(...)">` envelope encodes
//! the same SVG → output-pixel transform that
//! `floor_ir_to_png`'s `SkiaPainter::with_transform` pre-bakes
//! into the rasteriser. This keeps the painter's coordinate
//! contract uniform across both backends — handlers emit raw IR
//! coordinates, the entry point applies the canvas transform.
//!
//! `floor_ir_to_svg` is the Rust entry point for the PyO3
//! `nhc_render.ir_to_svg` export added in Phase 2.17, which
//! retires the legacy `nhc/rendering/ir_to_svg.py` Python emitter
//! in Phase 2.18.

use std::fmt::Write as _;

use crate::ir::{floor_ir_buffer_has_identifier, root_as_floor_ir};
use crate::painter::SvgPainter;

use super::png::{
    dispatch_ops, dispatch_v5_ops, resolve_layer_filter, BARE_SKIP_OPS, BG_B,
    BG_G, BG_R,
};

// Cross-rasteriser parity helper — used by the test harness
// (`tests/unit/test_ir_png_parity.py`) to PSNR-compare an SVG
// payload against the tiny-skia output. Re-exported here so the
// PyO3 export keeps its `transform::svg::svg_to_png` import path
// stable across the Phase 2.16 directory restructure.
pub mod raster;
pub use raster::{svg_to_png, SvgError as SvgRasterError};

/// Errors the IR → SVG path can surface. Mirrors
/// [`super::png::PngError`] minus the rasteriser-specific
/// failure modes (canvas allocation, PNG encoding).
#[derive(Debug)]
pub enum SvgError {
    /// The buffer didn't parse as a `FloorIR` (missing identifier
    /// or schema mismatch).
    InvalidBuffer(String),
    /// `layer` argument didn't match any known IR layer name.
    UnknownLayer(String),
}

impl std::fmt::Display for SvgError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidBuffer(msg) => {
                write!(f, "invalid FloorIR buffer: {msg}")
            }
            Self::UnknownLayer(name) => {
                write!(f, "unknown layer: {name:?}")
            }
        }
    }
}

impl std::error::Error for SvgError {}

/// Render a `FloorIR` buffer to a complete SVG document string.
///
/// `scale` multiplies the SVG canvas dimensions; `1.0` matches
/// the legacy emitter's natural canvas. `layer` (if `Some`)
/// filters dispatch to one layer through the same
/// [`super::png::layer_ops`] map the PNG entry point uses.
/// `bare` (when `true`) elides the four decoration layers
/// (`floor_detail`, `thematic_detail`, `terrain_detail`,
/// `surface_features`) for the web `/admin` debug visualisation;
/// mirrors the legacy Python `_BARE_SKIP_LAYERS` set retired with
/// `nhc/rendering/ir_to_svg.py` in Phase 2.19.
pub fn floor_ir_to_svg(
    buf: &[u8],
    scale: f32,
    layer: Option<&str>,
    bare: bool,
) -> Result<String, SvgError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(SvgError::InvalidBuffer(
            "buffer does not carry the NIR3 file_identifier".to_string(),
        ));
    }
    let layer_filter =
        resolve_layer_filter(layer).map_err(SvgError::UnknownLayer)?;
    let skip_filter = if bare { Some(BARE_SKIP_OPS) } else { None };

    let fir = root_as_floor_ir(buf)
        .map_err(|e| SvgError::InvalidBuffer(e.to_string()))?;

    let cell = fir.cell() as f32;
    let padding = fir.padding() as f32;
    let svg_w = fir.width_tiles() as f32 * cell + 2.0 * padding;
    let svg_h = fir.height_tiles() as f32 * cell + 2.0 * padding;
    let pw = (svg_w * scale).max(0.0);
    let ph = (svg_h * scale).max(0.0);

    let mut painter = SvgPainter::new();
    dispatch_ops(&fir, layer_filter, skip_filter, &mut painter);
    let (defs, body) = painter.into_parts();

    Ok(assemble_envelope(pw, ph, padding, scale, &defs, &body))
}

/// Render a `FloorIR` buffer to an SVG document by walking the v5
/// op array (`v5_ops` / `v5_regions`) instead of the canonical v4
/// op array. Phase 4.2a of `plans/nhc_pure_ir_v5_migration_plan.md`
/// — the dual SVG entry point lets the cross-rasteriser parity gate
/// in `tests/unit/test_ir_png_parity.py` switch to v5 ahead of the
/// atomic schema cut at Phase 4.3.
///
/// Op coverage matches [`super::png::floor_ir_to_png_v5`]; both
/// entry points share [`dispatch_v5_ops`] internally and only the
/// concrete `Painter` differs ([`SvgPainter`] here vs. `SkiaPainter`
/// there). See the PNG entry's documentation for the per-op-kind
/// dispatch arms and layer-filter mapping.
///
/// `bare` is currently reserved: the v5 op union doesn't carry the
/// v4 layer split that `BARE_SKIP_OPS` keys off, so the flag is
/// accepted for API parity with [`floor_ir_to_svg`] but no decoration
/// elision happens. Bare-mode v5 semantics land as polish post-cut.
pub fn floor_ir_to_svg_v5(
    buf: &[u8],
    scale: f32,
    layer: Option<&str>,
) -> Result<String, SvgError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(SvgError::InvalidBuffer(
            "buffer does not carry the NIR3 file_identifier".to_string(),
        ));
    }
    let layer_filter =
        resolve_layer_filter(layer).map_err(SvgError::UnknownLayer)?;

    let fir = root_as_floor_ir(buf)
        .map_err(|e| SvgError::InvalidBuffer(e.to_string()))?;

    let cell = fir.cell() as f32;
    let padding = fir.padding() as f32;
    let svg_w = fir.width_tiles() as f32 * cell + 2.0 * padding;
    let svg_h = fir.height_tiles() as f32 * cell + 2.0 * padding;
    let pw = (svg_w * scale).max(0.0);
    let ph = (svg_h * scale).max(0.0);

    let mut painter = SvgPainter::new();
    dispatch_v5_ops(&fir, layer_filter, &mut painter);
    let (defs, body) = painter.into_parts();

    Ok(assemble_envelope(pw, ph, padding, scale, &defs, &body))
}

/// Wrap the painter's accumulated body + defs into the canonical
/// `<svg>` envelope. Body coordinates are in raw IR pixel space;
/// the outer `<g transform="...">` applies
/// `translate(padding, padding) scale(scale, scale)` to match the
/// PNG entry point's canvas transform.
fn assemble_envelope(
    pw: f32,
    ph: f32,
    padding: f32,
    scale: f32,
    defs: &str,
    body: &str,
) -> String {
    // Pre-allocate a roomy buffer — the body is the dominant
    // contributor on real fixtures. Empty fixtures still hit the
    // small constant-size envelope wrappers.
    let mut out = String::with_capacity(body.len() + defs.len() + 256);
    out.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>");
    let _ = write!(
        out,
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{w}\" \
         height=\"{h}\" viewBox=\"0 0 {w} {h}\">",
        w = fmt_dim(pw),
        h = fmt_dim(ph),
    );
    if !defs.is_empty() {
        let _ = write!(out, "<defs>{defs}</defs>");
    }
    // Parchment-tone background rect, byte-equivalent to the Python
    // emitter's `<rect width="100%" height="100%" fill="#F5EDE0"/>`
    // and to `tiny-skia`'s `pixmap.fill(BG)` in `floor_ir_to_png`.
    // resvg-renders the SVG against a transparent canvas otherwise,
    // which surfaces as a black background and tanks the cross-
    // rasteriser PSNR gate in `tests/unit/test_ir_png_parity.py`.
    let _ = write!(
        out,
        "<rect width=\"100%\" height=\"100%\" fill=\"#{r:02X}{g:02X}{b:02X}\"/>",
        r = BG_R, g = BG_G, b = BG_B,
    );
    let _ = write!(
        out,
        "<g transform=\"translate({tx} {ty}) scale({sx} {sy})\">",
        tx = fmt_num(padding * scale),
        ty = fmt_num(padding * scale),
        sx = fmt_num(scale),
        sy = fmt_num(scale),
    );
    out.push_str(body);
    out.push_str("</g></svg>");
    out
}

fn fmt_dim(v: f32) -> String {
    fmt_num(v)
}

fn fmt_num(v: f32) -> String {
    if v.is_finite() && v == v.trunc() {
        format!("{}", v as i64)
    } else {
        format!("{v}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::{finish_floor_ir_buffer, FloorIR, FloorIRArgs};
    use flatbuffers::FlatBufferBuilder;

    /// Minimal valid FloorIR buffer for shape-level smoke tests.
    fn build_minimal_buf(width_tiles: u32, height_tiles: u32) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let theme = fbb.create_string("dungeon");
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 2,
                minor: 0,
                width_tiles,
                height_tiles,
                cell: 32,
                padding: 32,
                theme: Some(theme),
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn empty_buffer_emits_well_formed_envelope() {
        let buf = build_minimal_buf(2, 2);
        let svg = floor_ir_to_svg(&buf, 1.0, None, false).expect("encode succeeds");
        assert!(svg.starts_with("<?xml version=\"1.0\""), "missing xml prolog: {svg}");
        assert!(svg.contains("<svg "), "missing svg open: {svg}");
        assert!(svg.ends_with("</svg>"), "missing svg close: {svg}");
    }

    /// Canvas dims follow the same SVG sizing rule as the PNG
    /// path. 4 × 3 tiles with default cell=32, padding=32 →
    /// (4*32 + 2*32) × (3*32 + 2*32) = 192 × 160.
    #[test]
    fn canvas_matches_svg_sizing_rule() {
        let buf = build_minimal_buf(4, 3);
        let svg = floor_ir_to_svg(&buf, 1.0, None, false).expect("encode succeeds");
        assert!(
            svg.contains("width=\"192\""),
            "missing 192 width: {svg}"
        );
        assert!(
            svg.contains("height=\"160\""),
            "missing 160 height: {svg}"
        );
        assert!(
            svg.contains("viewBox=\"0 0 192 160\""),
            "missing viewBox: {svg}"
        );
    }

    /// `scale = 2.0` doubles both dimensions — the body
    /// coordinates stay in IR space, but the outer transform
    /// scales the rendered output.
    #[test]
    fn scale_factor_multiplies_canvas() {
        let buf = build_minimal_buf(4, 3);
        let svg = floor_ir_to_svg(&buf, 2.0, None, false).expect("encode succeeds");
        assert!(svg.contains("width=\"384\""));
        assert!(svg.contains("height=\"320\""));
        // Outer transform encodes scale 2 + translate(64, 64) in
        // output-pixel space.
        assert!(
            svg.contains("scale(2 2)"),
            "missing scaled outer g: {svg}"
        );
        assert!(
            svg.contains("translate(64 64)"),
            "missing translated outer g: {svg}"
        );
    }

    #[test]
    fn rejects_buffer_without_identifier() {
        let err = floor_ir_to_svg(&[0u8; 16], 1.0, None, false).unwrap_err();
        assert!(matches!(err, SvgError::InvalidBuffer(_)));
    }

    /// Every layer name from the PNG entry point's table accepts
    /// without error here too — both transformers share the same
    /// `layer_ops()` map.
    #[test]
    fn known_layer_names_are_accepted() {
        let buf = build_minimal_buf(2, 2);
        for layer in [
            "shadows",
            "hatching",
            "structural",
            "terrain_tints",
            "floor_grid",
            "floor_detail",
            "thematic_detail",
            "terrain_detail",
            "stairs",
            "surface_features",
        ] {
            floor_ir_to_svg(&buf, 1.0, Some(layer), false)
                .unwrap_or_else(|e| panic!("layer {layer:?}: {e}"));
        }
    }

    #[test]
    fn unknown_layer_is_rejected() {
        let buf = build_minimal_buf(2, 2);
        let err =
            floor_ir_to_svg(&buf, 1.0, Some("not-a-layer"), false).unwrap_err();
        assert!(matches!(err, SvgError::UnknownLayer(_)));
    }

    /// Outer transform always wraps the body, even when the body
    /// is empty (no ops in the buffer). Phase 2.17 / 2.18 callers
    /// rely on this for stable structural sanity checks.
    #[test]
    fn empty_body_still_wraps_in_outer_g() {
        let buf = build_minimal_buf(2, 2);
        let svg = floor_ir_to_svg(&buf, 1.0, None, false).expect("encode succeeds");
        assert!(
            svg.contains("<g transform=\"translate(32 32) scale(1 1)\">"),
            "missing outer g envelope: {svg}"
        );
    }

    /// Three real-floor fixtures from `tests/fixtures/floor_ir/`
    /// — one synthetic roof, one wood-floor building, one full
    /// dungeon. Each must round-trip through `floor_ir_to_svg`
    /// without erroring AND emit at least one element from the
    /// expected set (`<rect>`, `<path>`, `<polygon>`, `<g>`).
    /// Catches regressions where a handler returns early under
    /// the SVG painter even though the PNG path emits geometry.
    #[test]
    fn fixture_smoke_emits_expected_element_types() {
        let fixtures: &[(&str, &[u8])] = &[
            (
                "synthetic_roof_octagon",
                include_bytes!(
                    "../../../../../tests/fixtures/floor_ir/\
                     synthetic_roof_octagon/floor.nir"
                ),
            ),
            (
                "seed7_brick_building_floor0",
                include_bytes!(
                    "../../../../../tests/fixtures/floor_ir/\
                     seed7_brick_building_floor0/floor.nir"
                ),
            ),
            (
                "seed42_rect_dungeon_dungeon",
                include_bytes!(
                    "../../../../../tests/fixtures/floor_ir/\
                     seed42_rect_dungeon_dungeon/floor.nir"
                ),
            ),
        ];

        for (name, buf) in fixtures {
            let svg = floor_ir_to_svg(buf, 1.0, None, false)
                .unwrap_or_else(|e| panic!("fixture {name}: {e}"));
            assert!(
                svg.starts_with("<?xml"),
                "fixture {name}: missing xml prolog"
            );
            assert!(
                svg.ends_with("</svg>"),
                "fixture {name}: missing svg close"
            );
            // Every fixture has at least one painted op, so at
            // least one of these element types must appear.
            let has_geometry = svg.contains("<rect")
                || svg.contains("<path")
                || svg.contains("<polygon")
                || svg.contains("<polyline")
                || svg.contains("<circle")
                || svg.contains("<ellipse");
            assert!(
                has_geometry,
                "fixture {name}: no geometry elements emitted"
            );
        }
    }

    /// `bare = true` elides the four decoration layers
    /// (`floor_detail`, `thematic_detail`, `terrain_detail`,
    /// `surface_features`) — the resulting SVG body is strictly
    /// shorter than the full composite for any fixture that has
    /// at least one decoration op. Mirrors the legacy Python
    /// `_BARE_SKIP_LAYERS` contract retired with `ir_to_svg.py`
    /// in Phase 2.19; the `/admin?bare=1` debug route depends on
    /// this filtering shape.
    #[test]
    fn bare_flag_shortens_dungeon_fixture() {
        let buf: &[u8] = include_bytes!(
            "../../../../../tests/fixtures/floor_ir/\
             seed42_rect_dungeon_dungeon/floor.nir"
        );
        let full = floor_ir_to_svg(buf, 1.0, None, false)
            .expect("full encode succeeds");
        let bare = floor_ir_to_svg(buf, 1.0, None, true)
            .expect("bare encode succeeds");
        assert!(
            bare.len() < full.len(),
            "bare={} not shorter than full={}",
            bare.len(),
            full.len(),
        );
        // Both must remain well-formed SVG documents.
        assert!(bare.starts_with("<?xml"));
        assert!(bare.ends_with("</svg>"));
    }

    // ── v5 SVG entry point (Phase 4.2a) ─────────────────────────

    /// Empty buffer round-trips through `floor_ir_to_svg_v5`,
    /// emitting the same canonical envelope the v4 path does
    /// (xml prolog, single `<svg>` root, viewBox, background rect,
    /// outer `<g>` with translate+scale, body, closing `</svg>`).
    /// Catches binding regressions independent of any v5 op
    /// dispatch.
    #[test]
    fn v5_empty_buffer_emits_well_formed_envelope() {
        let buf = build_minimal_buf(2, 2);
        let svg =
            floor_ir_to_svg_v5(&buf, 1.0, None).expect("v5 encode succeeds");
        assert!(svg.starts_with("<?xml version=\"1.0\""));
        assert!(svg.contains("<svg "));
        assert!(svg.contains("viewBox=\"0 0 128 128\""));
        assert!(svg.ends_with("</svg>"));
    }

    /// `floor_ir_to_svg_v5` rejects a buffer that doesn't carry the
    /// FloorIR file_identifier — same defensive check `floor_ir_to_svg`
    /// uses. Catches accidental zero-byte inputs from the FFI layer.
    #[test]
    fn v5_rejects_buffer_without_identifier() {
        let err = floor_ir_to_svg_v5(&[0u8; 16], 1.0, None).unwrap_err();
        assert!(matches!(err, SvgError::InvalidBuffer(_)));
    }

    /// Real fixtures round-trip through `floor_ir_to_svg_v5` and
    /// emit at least one geometry element. Mirrors the v4 smoke
    /// test above so a v5 dispatcher regression (silently skipped
    /// op kind, broken Painter wiring) surfaces here rather than
    /// only in the parity gate.
    #[test]
    fn v5_fixture_smoke_emits_expected_element_types() {
        let fixtures: &[(&str, &[u8])] = &[
            (
                "synthetic_roof_octagon",
                include_bytes!(
                    "../../../../../tests/fixtures/floor_ir/\
                     synthetic_roof_octagon/floor.nir"
                ),
            ),
            (
                "seed7_brick_building_floor0",
                include_bytes!(
                    "../../../../../tests/fixtures/floor_ir/\
                     seed7_brick_building_floor0/floor.nir"
                ),
            ),
            (
                "seed42_rect_dungeon_dungeon",
                include_bytes!(
                    "../../../../../tests/fixtures/floor_ir/\
                     seed42_rect_dungeon_dungeon/floor.nir"
                ),
            ),
        ];

        for (name, buf) in fixtures {
            let svg = floor_ir_to_svg_v5(buf, 1.0, None)
                .unwrap_or_else(|e| panic!("fixture {name}: {e}"));
            assert!(
                svg.starts_with("<?xml"),
                "fixture {name}: missing xml prolog"
            );
            assert!(
                svg.ends_with("</svg>"),
                "fixture {name}: missing svg close"
            );
            let has_geometry = svg.contains("<rect")
                || svg.contains("<path")
                || svg.contains("<polygon")
                || svg.contains("<polyline")
                || svg.contains("<circle")
                || svg.contains("<ellipse");
            assert!(
                has_geometry,
                "fixture {name}: no geometry elements emitted"
            );
        }
    }

    /// Layer-filter gating mirrors the v5 PNG entry point: a
    /// `Some("structural")` filter still produces a well-formed SVG
    /// (envelope + outer `<g>`) even though it narrows the dispatch
    /// to V5PaintOp/V5StrokeOp/V5RoofOp.
    #[test]
    fn v5_known_layer_names_are_accepted() {
        let buf = build_minimal_buf(2, 2);
        for layer in [
            "shadows", "hatching", "structural", "floor_detail",
            "thematic_detail", "terrain_detail", "surface_features",
        ] {
            floor_ir_to_svg_v5(&buf, 1.0, Some(layer))
                .unwrap_or_else(|e| panic!("layer {layer:?}: {e}"));
        }
    }

    #[test]
    fn v5_unknown_layer_is_rejected() {
        let buf = build_minimal_buf(2, 2);
        let err = floor_ir_to_svg_v5(&buf, 1.0, Some("not-a-layer"))
            .unwrap_err();
        assert!(matches!(err, SvgError::UnknownLayer(_)));
    }
}
