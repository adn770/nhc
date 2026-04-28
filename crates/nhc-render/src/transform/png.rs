//! IR → PNG via `tiny-skia`. Phase 5 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Reads a `FloorIR` FlatBuffer, computes the same canvas
//! dimensions the legacy SVG path uses
//! (`width_tiles * cell + 2 * padding`, same for height), and
//! rasterises into a `tiny-skia::Pixmap`.
//!
//! **Phase 5.1 ships a stub.** The function returns an empty
//! (transparent) pixmap encoded as PNG — enough to lock the FFI
//! shape (`nhc_render.ir_to_png(ir_bytes, scale=1.0) -> bytes`)
//! in one commit. The deterministic primitives land in 5.2,
//! the RNG-heavy ones in 5.3, the structured decorators +
//! surface features in 5.4, and the SVG passthroughs in 5.5;
//! each later commit fills in this function further while
//! keeping the signature stable.

use tiny_skia::Pixmap;

use crate::ir::{floor_ir_buffer_has_identifier, root_as_floor_ir};

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
        }
    }
}

impl std::error::Error for PngError {}

/// Render a `FloorIR` buffer to a PNG byte stream.
///
/// `scale` multiplies the SVG-equivalent canvas size; `1.0`
/// matches the legacy `resvg-py` rendering at the SVG's natural
/// dpi. The current implementation is a Phase 5.1 stub — the
/// pixmap is sized correctly but left transparent until later
/// sub-phases populate it.
pub fn floor_ir_to_png(buf: &[u8], scale: f32) -> Result<Vec<u8>, PngError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(PngError::InvalidBuffer(
            "buffer does not carry the NIRF file_identifier".to_string(),
        ));
    }
    let fir = root_as_floor_ir(buf)
        .map_err(|e| PngError::InvalidBuffer(e.to_string()))?;
    let cell = fir.cell() as f32;
    let padding = fir.padding() as f32;
    let svg_w = fir.width_tiles() as f32 * cell + 2.0 * padding;
    let svg_h = fir.height_tiles() as f32 * cell + 2.0 * padding;
    let pw = (svg_w * scale).round().max(0.0) as u32;
    let ph = (svg_h * scale).round().max(0.0) as u32;
    let pixmap = Pixmap::new(pw, ph)
        .ok_or(PngError::InvalidCanvas { width: pw, height: ph })?;
    pixmap
        .encode_png()
        .map_err(|e| PngError::EncodeFailed(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::{finish_floor_ir_buffer, FloorIR, FloorIRArgs};
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
        let png = floor_ir_to_png(&buf, 1.0).expect("encode succeeds");
        assert_eq!(&png[..8], PNG_SIG, "PNG signature missing");
    }

    /// Canvas dims follow the legacy SVG sizing rule.
    /// 4 × 3 tiles with default cell=32, padding=32 →
    /// (4*32 + 2*32) × (3*32 + 2*32) = 192 × 160. PNG IHDR carries
    /// width/height as big-endian u32 at byte offsets 16..24.
    #[test]
    fn canvas_matches_svg_sizing_rule() {
        let buf = build_minimal_buf(4, 3);
        let png = floor_ir_to_png(&buf, 1.0).expect("encode succeeds");
        let w = u32::from_be_bytes([png[16], png[17], png[18], png[19]]);
        let h = u32::from_be_bytes([png[20], png[21], png[22], png[23]]);
        assert_eq!(w, 192);
        assert_eq!(h, 160);
    }

    /// `scale = 2.0` doubles both dimensions.
    #[test]
    fn scale_factor_multiplies_canvas() {
        let buf = build_minimal_buf(4, 3);
        let png = floor_ir_to_png(&buf, 2.0).expect("encode succeeds");
        let w = u32::from_be_bytes([png[16], png[17], png[18], png[19]]);
        let h = u32::from_be_bytes([png[20], png[21], png[22], png[23]]);
        assert_eq!(w, 384);
        assert_eq!(h, 320);
    }

    #[test]
    fn rejects_buffer_without_identifier() {
        let err = floor_ir_to_png(&[0u8; 16], 1.0).unwrap_err();
        assert!(matches!(err, PngError::InvalidBuffer(_)));
    }
}
