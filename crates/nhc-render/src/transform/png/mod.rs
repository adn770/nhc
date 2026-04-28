//! IR → PNG via `tiny-skia`. Phase 5 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Reads a `FloorIR` FlatBuffer, computes the same canvas
//! dimensions the legacy SVG path uses
//! (`width_tiles * cell + 2 * padding`, same for height), and
//! rasterises into a `tiny-skia::Pixmap`.
//!
//! **5.1** locked the FFI shape (`ir_to_png(ir_bytes,
//! scale=1.0, layer=None) -> bytes`); **5.1.1** added the BG
//! envelope + parity harness; per-primitive 5.2 / 5.3 / 5.4
//! commits register handlers in `op_handlers()` one at a time.
//!
//! Live handlers: `ShadowOp` (5.2.1).

use std::collections::HashMap;
use std::sync::OnceLock;

use tiny_skia::{Color, Pixmap, Transform};

use crate::ir::{
    floor_ir_buffer_has_identifier, root_as_floor_ir, FloorIR, Op, OpEntry,
};

// Shared infrastructure consumed by per-primitive handlers.
mod path_parser;
mod polygon_path;
mod svg_attr;

// Per-primitive raster handlers — one module per Op kind.
mod floor_grid;
mod hatch;
mod shadow;
mod stairs;
mod terrain_tints;
mod walls_and_floors;

/// Background fill — matches `nhc/rendering/_svg_helpers.py:BG`
/// (`#F5EDE0`, parchment). Both the resvg-py baseline and the
/// tiny-skia path paint this first; per-primitive commits paint
/// on top of it.
pub const BG_R: u8 = 0xF5;
pub const BG_G: u8 = 0xED;
pub const BG_B: u8 = 0xE0;

/// Errors the IR → PNG path can surface.
#[derive(Debug)]
pub enum PngError {
    /// The buffer didn't parse as a `FloorIR` (missing identifier
    /// or schema mismatch).
    InvalidBuffer(String),
    /// The pixmap allocator returned `None` — the canvas size
    /// resolved to 0×0 or overflowed `u32`.
    InvalidCanvas { width: u32, height: u32 },
    /// `tiny-skia`'s PNG encoder rejected the pixmap.
    EncodeFailed(String),
    /// `layer` argument didn't match any known IR layer name.
    UnknownLayer(String),
}

impl std::fmt::Display for PngError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidBuffer(msg) => {
                write!(f, "invalid FloorIR buffer: {msg}")
            }
            Self::InvalidCanvas { width, height } => {
                write!(f, "invalid canvas size: {width}×{height}")
            }
            Self::EncodeFailed(msg) => {
                write!(f, "PNG encode failed: {msg}")
            }
            Self::UnknownLayer(name) => {
                write!(f, "unknown layer: {name:?}")
            }
        }
    }
}

impl std::error::Error for PngError {}

/// Drawing surface every per-primitive handler composes against.
///
/// `transform` is the accumulated SVG → PNG-pixel transform —
/// the `translate(padding, padding)` from `ir_to_svg`'s outer
/// `<g>` plus the user-supplied `scale`. Per-primitive handlers
/// either pass it straight through to `Pixmap::fill_path` /
/// `stroke_path`, or pre-compose their own per-op transform and
/// pass the combined result.
pub struct RasterCtx<'a> {
    pub pixmap: &'a mut Pixmap,
    pub transform: Transform,
    pub scale: f32,
}

/// Op-handler signature. Phase 5.2 / 5.3 / 5.4 commits each
/// register exactly one such function.
pub type OpHandler = fn(&OpEntry<'_>, &FloorIR<'_>, &mut RasterCtx<'_>);

/// Layer-name → op-tag-set mapping. Mirrors `_LAYER_OPS` in
/// `nhc/rendering/ir_to_svg.py`; the per-layer parity harness in
/// `tests/unit/test_ir_png_parity.py` walks both sides through
/// the same dictionary.
fn layer_ops() -> &'static HashMap<&'static str, &'static [Op]> {
    static MAP: OnceLock<HashMap<&'static str, &'static [Op]>> =
        OnceLock::new();
    MAP.get_or_init(|| {
        let mut m: HashMap<&'static str, &'static [Op]> = HashMap::new();
        m.insert("shadows", &[Op::ShadowOp]);
        m.insert("hatching", &[Op::HatchOp]);
        m.insert("walls_and_floors", &[Op::WallsAndFloorsOp]);
        m.insert("terrain_tints", &[Op::TerrainTintOp]);
        m.insert("floor_grid", &[Op::FloorGridOp]);
        m.insert("floor_detail", &[Op::FloorDetailOp, Op::DecoratorOp]);
        m.insert("thematic_detail", &[Op::ThematicDetailOp]);
        m.insert("terrain_detail", &[Op::TerrainDetailOp]);
        m.insert("stairs", &[Op::StairsOp]);
        m.insert(
            "surface_features",
            &[
                Op::WellFeatureOp,
                Op::FountainFeatureOp,
                Op::TreeFeatureOp,
                Op::BushFeatureOp,
                Op::GenericProceduralOp,
            ],
        );
        m
    })
}

/// Op tag → handler. Phase 5.1.1 starts empty; per-primitive
/// commits append entries.
fn op_handlers() -> &'static HashMap<u8, OpHandler> {
    static HANDLERS: OnceLock<HashMap<u8, OpHandler>> = OnceLock::new();
    HANDLERS.get_or_init(|| {
        let mut m: HashMap<u8, OpHandler> = HashMap::new();
        m.insert(Op::ShadowOp.0, shadow::draw);
        m.insert(Op::WallsAndFloorsOp.0, walls_and_floors::draw);
        m.insert(Op::TerrainTintOp.0, terrain_tints::draw);
        m.insert(Op::FloorGridOp.0, floor_grid::draw);
        m.insert(Op::StairsOp.0, stairs::draw);
        m.insert(Op::HatchOp.0, hatch::draw);
        m
    })
}

/// Render a `FloorIR` buffer to a PNG byte stream.
///
/// `scale` multiplies the SVG-equivalent canvas size; `1.0`
/// matches the legacy `resvg-py` rendering at the SVG's natural
/// dpi. `layer` (if `Some`) filters dispatch to a single layer
/// — the parity harness uses this to gate per-primitive commits
/// one layer at a time.
pub fn floor_ir_to_png(
    buf: &[u8],
    scale: f32,
    layer: Option<&str>,
) -> Result<Vec<u8>, PngError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(PngError::InvalidBuffer(
            "buffer does not carry the NIRF file_identifier".to_string(),
        ));
    }
    let layer_filter = if let Some(name) = layer {
        match layer_ops().get(name) {
            Some(set) => Some(*set),
            None => return Err(PngError::UnknownLayer(name.to_string())),
        }
    } else {
        None
    };

    let fir = root_as_floor_ir(buf)
        .map_err(|e| PngError::InvalidBuffer(e.to_string()))?;

    let cell = fir.cell() as f32;
    let padding = fir.padding() as f32;
    let svg_w = fir.width_tiles() as f32 * cell + 2.0 * padding;
    let svg_h = fir.height_tiles() as f32 * cell + 2.0 * padding;
    let pw = (svg_w * scale).round().max(0.0) as u32;
    let ph = (svg_h * scale).round().max(0.0) as u32;
    let mut pixmap = Pixmap::new(pw, ph)
        .ok_or(PngError::InvalidCanvas { width: pw, height: ph })?;

    pixmap.fill(Color::from_rgba8(BG_R, BG_G, BG_B, 0xFF));

    let transform = Transform::from_translate(padding, padding)
        .post_scale(scale, scale);
    let mut ctx = RasterCtx {
        pixmap: &mut pixmap,
        transform,
        scale,
    };

    let handlers = op_handlers();
    if let Some(ops) = fir.ops() {
        for entry in ops.iter() {
            let op_type = entry.op_type();
            if let Some(filter) = layer_filter {
                if !filter.contains(&op_type) {
                    continue;
                }
            }
            // Per-primitive commits register handlers for the op
            // tags they own; tags without a handler silently skip
            // (the parity harness catches the visual delta).
            if let Some(handler) = handlers.get(&op_type.0) {
                handler(&entry, &fir, &mut ctx);
            }
        }
    }

    pixmap
        .encode_png()
        .map_err(|e| PngError::EncodeFailed(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::{finish_floor_ir_buffer, FloorIRArgs};
    use flatbuffers::FlatBufferBuilder;

    /// Minimal valid FloorIR buffer for FFI-shape tests.
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

    /// PNG signature: 137 80 78 71 13 10 26 10 = "\x89PNG\r\n\x1a\n".
    const PNG_SIG: &[u8; 8] = b"\x89PNG\r\n\x1a\n";

    #[test]
    fn empty_pixmap_encodes_as_png() {
        let buf = build_minimal_buf(2, 2);
        let png =
            floor_ir_to_png(&buf, 1.0, None).expect("encode succeeds");
        assert_eq!(&png[..8], PNG_SIG, "PNG signature missing");
    }

    /// Canvas dims follow the legacy SVG sizing rule.
    /// 4 × 3 tiles with default cell=32, padding=32 →
    /// (4*32 + 2*32) × (3*32 + 2*32) = 192 × 160. PNG IHDR carries
    /// width/height as big-endian u32 at byte offsets 16..24.
    #[test]
    fn canvas_matches_svg_sizing_rule() {
        let buf = build_minimal_buf(4, 3);
        let png =
            floor_ir_to_png(&buf, 1.0, None).expect("encode succeeds");
        let w = u32::from_be_bytes([png[16], png[17], png[18], png[19]]);
        let h = u32::from_be_bytes([png[20], png[21], png[22], png[23]]);
        assert_eq!(w, 192);
        assert_eq!(h, 160);
    }

    /// `scale = 2.0` doubles both dimensions.
    #[test]
    fn scale_factor_multiplies_canvas() {
        let buf = build_minimal_buf(4, 3);
        let png =
            floor_ir_to_png(&buf, 2.0, None).expect("encode succeeds");
        let w = u32::from_be_bytes([png[16], png[17], png[18], png[19]]);
        let h = u32::from_be_bytes([png[20], png[21], png[22], png[23]]);
        assert_eq!(w, 384);
        assert_eq!(h, 320);
    }

    #[test]
    fn rejects_buffer_without_identifier() {
        let err =
            floor_ir_to_png(&[0u8; 16], 1.0, None).unwrap_err();
        assert!(matches!(err, PngError::InvalidBuffer(_)));
    }

    /// All layer names from `_LAYER_OPS` (Python side) accept
    /// without error. Catches drift between the Rust mirror and
    /// the Python source.
    #[test]
    fn known_layer_names_are_accepted() {
        let buf = build_minimal_buf(2, 2);
        for layer in [
            "shadows",
            "hatching",
            "walls_and_floors",
            "terrain_tints",
            "floor_grid",
            "floor_detail",
            "thematic_detail",
            "terrain_detail",
            "stairs",
            "surface_features",
        ] {
            floor_ir_to_png(&buf, 1.0, Some(layer))
                .unwrap_or_else(|e| panic!("layer {layer:?}: {e}"));
        }
    }

    #[test]
    fn unknown_layer_is_rejected() {
        let buf = build_minimal_buf(2, 2);
        let err =
            floor_ir_to_png(&buf, 1.0, Some("not-a-layer")).unwrap_err();
        assert!(matches!(err, PngError::UnknownLayer(_)));
    }

    /// BG-only pixmap: every pixel matches the parchment tone.
    /// The Phase 5.1.1 contract — no primitives ported, so the
    /// pixmap is BG everywhere.
    #[test]
    fn bg_fills_full_canvas() {
        let buf = build_minimal_buf(2, 2);
        let png =
            floor_ir_to_png(&buf, 1.0, None).expect("encode succeeds");
        // Decode the PNG back via tiny-skia's loader and check a
        // sample pixel.
        let pixmap = Pixmap::decode_png(&png).expect("decode");
        let pixels = pixmap.pixels();
        // Pick the middle pixel — bytes are premultiplied RGBA;
        // alpha=255 means RGB are stored at full intensity.
        let p = pixels[pixels.len() / 2];
        assert_eq!(p.red(), BG_R);
        assert_eq!(p.green(), BG_G);
        assert_eq!(p.blue(), BG_B);
        assert_eq!(p.alpha(), 0xFF);
    }
}
