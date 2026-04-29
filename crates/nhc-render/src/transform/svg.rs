//! SVG → PNG rasteriser — Phase 10.4 of
//! `plans/nhc_ir_migration_plan.md`.
//!
//! Wraps the `resvg` + `usvg` crates so the cross-rasteriser
//! parity harness in `tests/unit/test_ir_png_parity.py` can
//! compare `ir_to_svg(buf)` -> PNG against the tiny-skia
//! rasterisation of the same buffer without depending on the
//! `resvg-py` Python wheel. Production never reaches this path
//! — the `.png` web endpoint goes straight through
//! `transform/png/` from the IR.

use tiny_skia::{Pixmap, Transform};

/// Errors the cross-rasteriser path can raise. All currently
/// flow through to a single `PyValueError` on the FFI side.
#[derive(Debug)]
pub enum SvgError {
    Parse(String),
    Pixmap(String),
    Encode(String),
}

impl std::fmt::Display for SvgError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SvgError::Parse(m) => write!(f, "svg parse: {m}"),
            SvgError::Pixmap(m) => write!(f, "svg pixmap: {m}"),
            SvgError::Encode(m) => write!(f, "svg encode: {m}"),
        }
    }
}

/// Rasterise an SVG string to a PNG byte stream at the SVG's
/// natural canvas size. Mirrors the legacy
/// `resvg_py.svg_to_bytes(svg_string=svg)` shape the parity
/// harness used to call.
pub fn svg_to_png(svg: &str) -> Result<Vec<u8>, SvgError> {
    let opt = usvg::Options::default();
    let tree = usvg::Tree::from_str(svg, &opt)
        .map_err(|e| SvgError::Parse(e.to_string()))?;
    let size = tree.size().to_int_size();
    let mut pixmap = Pixmap::new(size.width(), size.height())
        .ok_or_else(|| SvgError::Pixmap(format!(
            "could not allocate {}x{} pixmap",
            size.width(), size.height(),
        )))?;
    resvg::render(&tree, Transform::default(), &mut pixmap.as_mut());
    pixmap
        .encode_png()
        .map_err(|e| SvgError::Encode(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rasterises_minimal_svg_to_png_bytes() {
        let svg = concat!(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" ",
            "width=\"4\" height=\"4\">",
            "<rect width=\"4\" height=\"4\" fill=\"#F5EDE0\"/>",
            "</svg>",
        );
        let png = svg_to_png(svg).expect("valid svg");
        assert!(png.len() > 8, "expected PNG bytes, got {}", png.len());
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
    }

    #[test]
    fn parse_error_surfaces_as_svg_error() {
        let err = svg_to_png("not svg").unwrap_err();
        match err {
            SvgError::Parse(_) => {}
            other => panic!("expected Parse, got {other:?}"),
        }
    }
}
