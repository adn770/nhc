//! IR → PNG via `tiny-skia`.
//!
//! Reads a `FloorIR` FlatBuffer (NIR5), computes the same canvas
//! dimensions the SVG path uses (`width_tiles * cell + 2 * padding`,
//! same for height), and rasterises into a `tiny-skia::Pixmap`.
//!
//! Per-op handlers live in sibling modules under
//! `transform::png::{paint_op, stamp_op, path_op, fixture_op,
//! stroke_op, hatch_op, roof_op, shadow}`. The dispatch loop walks
//! `fir.ops()` once and routes each entry through `dispatch_ops`.

use std::collections::HashMap;
use std::sync::OnceLock;

use tiny_skia::{Color, Pixmap, Transform};

use crate::ir::{
    floor_ir_buffer_has_identifier, root_as_floor_ir, FloorIR, Material,
    MaterialFamily, Op, Region,
};
use crate::painter::material::{Family, Material as PodMaterial};
use crate::painter::{Painter, SkiaPainter};

// Per-op raster handlers — one module per Op kind.
pub mod fixture_op;
pub mod hatch_op;
pub mod paint_op;
pub mod path_op;
pub mod region_path;
mod roof;
pub mod roof_op;
mod shadow;
pub mod stamp_op;
pub mod stroke_op;

/// Background fill — matches `nhc/rendering/_svg_helpers.py:BG`
/// (`#F5EDE0`, parchment).
pub const BG_R: u8 = 0xF5;
pub const BG_G: u8 = 0xED;
pub const BG_B: u8 = 0xE0;

/// Errors the IR → PNG path can surface.
#[derive(Debug)]
pub enum PngError {
    InvalidBuffer(String),
    InvalidCanvas { width: u32, height: u32 },
    EncodeFailed(String),
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

/// Layer-name → op-tag-set mapping. Mirrors `_LAYER_OPS` in
/// `nhc/rendering/ir_to_svg_v5.py`; the per-layer parity harness in
/// `tests/unit/test_ir_png_parity.py` walks both sides through the
/// same dictionary.
fn layer_ops() -> &'static HashMap<&'static str, &'static [Op]> {
    static MAP: OnceLock<HashMap<&'static str, &'static [Op]>> =
        OnceLock::new();
    MAP.get_or_init(|| {
        let mut m: HashMap<&'static str, &'static [Op]> = HashMap::new();
        m.insert("shadows", &[Op::ShadowOp]);
        m.insert("hatching", &[Op::HatchOp]);
        m.insert("structural", &[Op::PaintOp, Op::StrokeOp, Op::RoofOp]);
        m.insert("decorators", &[Op::StampOp, Op::PathOp]);
        m.insert("fixtures", &[Op::FixtureOp]);
        m
    })
}

/// Op tags that the SVG entry point's `bare` flag elides for /admin
/// debug renders (decorator overlays + fixtures).
pub(crate) const BARE_SKIP_OPS: &[Op] =
    &[Op::StampOp, Op::PathOp, Op::FixtureOp];

/// Render a `FloorIR` buffer to a PNG byte stream.
///
/// `scale` multiplies the SVG-equivalent canvas size; `1.0`
/// matches the SVG natural dpi. `layer` (if `Some`) filters
/// dispatch to a single layer.
pub fn floor_ir_to_png(
    buf: &[u8],
    scale: f32,
    layer: Option<&str>,
) -> Result<Vec<u8>, PngError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(PngError::InvalidBuffer(
            "buffer does not carry the NIR5 file_identifier".to_string(),
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

    let transform = Transform::from_translate(padding, padding)
        .post_scale(scale, scale);
    let mut painter = SkiaPainter::with_transform(&mut pixmap, transform);

    dispatch_ops(&fir, layer_filter, None, &mut painter);

    drop(painter);
    pixmap
        .encode_png()
        .map_err(|e| PngError::EncodeFailed(e.to_string()))
}

/// Walk the IR's `ops[]` array once and dispatch each entry through
/// the per-op handlers under `transform::png::*`. Used by both
/// [`floor_ir_to_png`] and [`super::svg::floor_ir_to_svg`] — the
/// only difference between the two transformer entry points is
/// which concrete `Painter` impl arrives here.
///
/// `layer_filter` (when `Some`) restricts dispatch to ops in the
/// listed tag set. `skip_filter` (when `Some`) drops ops whose tag
/// matches — used by the SVG entry point's `bare` flag.
pub(crate) fn dispatch_ops(
    fir: &FloorIR<'_>,
    layer_filter: Option<&'static [Op]>,
    skip_filter: Option<&'static [Op]>,
    painter: &mut dyn Painter,
) {
    let regions = match fir.regions() {
        Some(r) => r,
        None => return,
    };
    let ops = match fir.ops() {
        Some(o) => o,
        None => return,
    };
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
        match op_type {
            Op::PaintOp => {
                if let Some(op) = entry.op_as_paint_op() {
                    paint_op::draw(op, regions, painter);
                }
            }
            Op::StampOp => {
                if let Some(op) = entry.op_as_stamp_op() {
                    stamp_op::draw(op, fir, regions, painter);
                }
            }
            Op::PathOp => {
                if let Some(op) = entry.op_as_path_op() {
                    path_op::draw(op, regions, painter);
                }
            }
            Op::FixtureOp => {
                if let Some(op) = entry.op_as_fixture_op() {
                    fixture_op::draw(op, regions, painter);
                }
            }
            Op::StrokeOp => {
                if let Some(op) = entry.op_as_stroke_op() {
                    stroke_op::draw(op, regions, painter);
                }
            }
            Op::ShadowOp => {
                if let Some(op) = entry.op_as_shadow_op() {
                    shadow::draw_shadow_op(&op, fir, painter);
                }
            }
            Op::HatchOp => {
                if let Some(op) = entry.op_as_hatch_op() {
                    hatch_op::draw(op, regions, painter);
                }
            }
            Op::RoofOp => {
                if let Some(op) = entry.op_as_roof_op() {
                    roof_op::draw(op, regions, painter);
                }
            }
            _ => {}
        }
    }
}

/// Resolve a layer name through [`layer_ops`] for the SVG / PNG
/// entry points. Public to the crate so the SVG entry point in
/// `super::svg` can mirror the PNG layer-filter handling without
/// re-deriving the mapping.
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

/// Bridge from a `Material` FB reader to the painter's POD
/// `Material`. The op handlers run this once per op; the painter
/// dispatches off the POD without re-reading the buffer.
pub fn material_from_fb(m: Material<'_>) -> PodMaterial {
    let family = match m.family() {
        MaterialFamily::Cave => Family::Cave,
        MaterialFamily::Wood => Family::Wood,
        MaterialFamily::Stone => Family::Stone,
        MaterialFamily::Earth => Family::Earth,
        MaterialFamily::Liquid => Family::Liquid,
        MaterialFamily::Special => Family::Special,
        // Plain (default) and any unknown trailing variant fall
        // through to Plain. The schema rejects unknown enum values
        // at the FB layer, so the catch-all is defensive only.
        _ => Family::Plain,
    };
    PodMaterial::new(
        family, m.style(), m.sub_pattern(), m.tone(), m.seed(),
    )
}

/// Linear scan a regions vector for the entry whose id matches
/// `needle`. Mirrors the per-op handler's region lookup; small
/// fixtures don't need a hash map.
pub fn find_region<'a>(
    regions: ::flatbuffers::Vector<
        'a,
        ::flatbuffers::ForwardsUOffset<Region<'a>>,
    >,
    needle: &str,
) -> Option<Region<'a>> {
    if needle.is_empty() {
        return None;
    }
    for i in 0..regions.len() {
        let r = regions.get(i);
        if r.id() == needle {
            return Some(r);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use flatbuffers::FlatBufferBuilder;

    use crate::ir::{Material, MaterialArgs, MaterialFamily};

    fn build_material(family: MaterialFamily, style: u8) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let m = Material::create(
            &mut fbb,
            &MaterialArgs {
                family,
                style,
                sub_pattern: 0,
                tone: 0,
                seed: 0xCAFE,
            },
        );
        fbb.finish_minimal(m);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn material_from_fb_maps_family_one_for_one() {
        for (fam_fb, fam_pod) in [
            (MaterialFamily::Plain, Family::Plain),
            (MaterialFamily::Cave, Family::Cave),
            (MaterialFamily::Wood, Family::Wood),
            (MaterialFamily::Stone, Family::Stone),
            (MaterialFamily::Earth, Family::Earth),
            (MaterialFamily::Liquid, Family::Liquid),
            (MaterialFamily::Special, Family::Special),
        ] {
            let buf = build_material(fam_fb, 0);
            let m = flatbuffers::root::<Material>(&buf).expect("parse");
            let pod = material_from_fb(m);
            assert_eq!(pod.family, fam_pod, "mismatch for {fam_fb:?}");
            assert_eq!(pod.seed, 0xCAFE);
        }
    }
}
