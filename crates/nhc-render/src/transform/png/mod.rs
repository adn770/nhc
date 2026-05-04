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
use crate::painter::{Painter, SkiaPainter};

// Shared infrastructure consumed by per-primitive handlers.
// `path_parser` survives as `floor_op.rs::draw_polygon` still
// parses cave path-d strings via `parse_path_d_pathops`.
// `fragment` / `polygon_path` / `svg_attr` are retired in this
// commit — every op handler now drives the [`Painter`] trait
// directly, so the SVG-string fragment path is dead code.
mod path_parser;

// Per-primitive raster handlers — one module per Op kind.
mod building_exterior_wall;
mod bush;
mod corridor_wall_op;
mod decorator;
mod enclosure;
mod exterior_wall_op;
mod floor_detail;
mod floor_grid;
mod floor_op;
mod fountain;
mod hatch;
mod interior_wall_op;
mod roof;
mod shadow;
mod stairs;
mod terrain_detail;
mod terrain_tints;
mod thematic_detail;
mod tree;
mod well;

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

/// Op-handler signature. Phase 2.16 of `plans/nhc_pure_ir_plan.md`
/// lifted [`SkiaPainter`] construction up to [`floor_ir_to_png`]
/// and switched every handler from the legacy `RasterCtx` shim to
/// `&mut dyn Painter`. Both [`floor_ir_to_png`] and
/// [`super::svg::floor_ir_to_svg`] now drive the same handler map
/// — the only difference is which concrete `Painter` impl arrives
/// at the top of the dispatch loop.
pub type OpHandler = fn(&OpEntry<'_>, &FloorIR<'_>, &mut dyn Painter);

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
        m.insert(
            "structural",
            &[
                Op::FloorOp,
                Op::ExteriorWallOp,
                Op::InteriorWallOp,
                Op::CorridorWallOp,
                Op::RoofOp,
            ],
        );
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
        m.insert(Op::FloorOp.0, floor_op::draw);
        m.insert(Op::ExteriorWallOp.0, exterior_wall_op::draw);
        m.insert(Op::InteriorWallOp.0, interior_wall_op::draw);
        m.insert(Op::CorridorWallOp.0, corridor_wall_op::draw);
        m.insert(Op::TerrainTintOp.0, terrain_tints::draw);
        m.insert(Op::FloorGridOp.0, floor_grid::draw);
        m.insert(Op::StairsOp.0, stairs::draw);
        m.insert(Op::HatchOp.0, hatch::draw);
        m.insert(Op::FloorDetailOp.0, floor_detail::draw);
        m.insert(Op::ThematicDetailOp.0, thematic_detail::draw);
        m.insert(Op::DecoratorOp.0, decorator::draw);
        m.insert(Op::WellFeatureOp.0, well::draw);
        m.insert(Op::FountainFeatureOp.0, fountain::draw);
        m.insert(Op::TreeFeatureOp.0, tree::draw);
        m.insert(Op::BushFeatureOp.0, bush::draw);
        m.insert(Op::TerrainDetailOp.0, terrain_detail::draw);
        m.insert(Op::RoofOp.0, roof::draw);
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
            "buffer does not carry the NIR3 file_identifier".to_string(),
        ));
    }
    let layer_filter =
        resolve_layer_filter(layer).map_err(PngError::UnknownLayer)?;

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

    // Pre-bake the SVG → PNG-pixel transform (`translate(padding,
    // padding)` + user-supplied `scale`) onto the painter; every
    // op handler now drives the active surface through `&mut dyn
    // Painter`, so the painter holds the only copy of the base
    // transform.
    let transform = Transform::from_translate(padding, padding)
        .post_scale(scale, scale);
    let mut painter = SkiaPainter::with_transform(&mut pixmap, transform);

    dispatch_ops(&fir, layer_filter, None, &mut painter);

    drop(painter);
    pixmap
        .encode_png()
        .map_err(|e| PngError::EncodeFailed(e.to_string()))
}

/// Walk the IR's `ops[]` array once and dispatch each entry
/// against the shared [`op_handlers`] map. Used by both
/// [`floor_ir_to_png`] and [`super::svg::floor_ir_to_svg`] —
/// the only difference between the two transformer entry points
/// is which concrete `Painter` impl arrives here.
///
/// `layer_filter` (when `Some`) restricts dispatch to ops in the
/// listed tag set — this is the per-layer entry point used by the
/// parity harness. `skip_filter` (when `Some`) drops ops whose tag
/// matches — this is the inverse, used by the SVG entry point's
/// `bare` flag to elide decoration layers from /admin debug
/// renders.
pub(crate) fn dispatch_ops(
    fir: &FloorIR<'_>,
    layer_filter: Option<&'static [Op]>,
    skip_filter: Option<&'static [Op]>,
    painter: &mut dyn Painter,
) {
    let handlers = op_handlers();
    if let Some(ops) = fir.ops() {
        for entry in ops.iter() {
            let op_type = entry.op_type();
            if let Some(filter) = layer_filter {
                if !filter.contains(&op_type) {
                    continue;
                }
            }
            if let Some(skip) = skip_filter {
                if skip.contains(&op_type) {
                    continue;
                }
            }
            // Per-primitive commits register handlers for the op
            // tags they own; tags without a handler silently skip
            // (the parity harness catches the visual delta).
            if let Some(handler) = handlers.get(&op_type.0) {
                handler(&entry, fir, painter);
            }
        }
    }
}

/// Op tags belonging to the four "decoration" layers
/// (`floor_detail`, `thematic_detail`, `terrain_detail`,
/// `surface_features`) that the SVG entry point's `bare` flag
/// elides for /admin debug renders. Mirrors the legacy Python
/// `_BARE_SKIP_LAYERS` set in `nhc/rendering/ir_to_svg.py`.
pub(crate) const BARE_SKIP_OPS: &[Op] = &[
    Op::FloorDetailOp,
    Op::DecoratorOp,
    Op::ThematicDetailOp,
    Op::TerrainDetailOp,
    Op::WellFeatureOp,
    Op::FountainFeatureOp,
    Op::TreeFeatureOp,
    Op::BushFeatureOp,
];

/// Resolve a layer name through [`layer_ops`] for the SVG /
/// PNG entry points. Public to the crate so the SVG entry point
/// in `super::svg` can mirror the PNG layer-filter handling
/// without re-deriving the mapping.
pub(crate) fn resolve_layer_filter(
    layer: Option<&str>,
) -> Result<Option<&'static [Op]>, String> {
    let Some(name) = layer else {
        return Ok(None);
    };
    layer_ops()
        .get(name)
        .copied()
        .map(Some)
        .ok_or_else(|| name.to_string())
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
            "structural",
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
