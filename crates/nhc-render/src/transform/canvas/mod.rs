//! IR → Canvas2D draw stream via the [`CanvasPainter`] backend.
//!
//! Phase 5.3 of `plans/nhc_pure_ir_v5_migration_plan.md`. Mirrors
//! the [`super::svg::floor_ir_to_svg`] / [`super::png::floor_ir_to_png`]
//! shape: parse a `FloorIR` FlatBuffer, walk the same `ops[]`
//! array through the shared [`super::png::dispatch_ops`], and
//! dispatch every op against a [`CanvasPainter`] driving the
//! caller-supplied [`Canvas2DCtx`] surface instead of a
//! [`SkiaPainter`] / [`SvgPainter`].
//!
//! The entry point is generic over [`Canvas2DCtx`] so this module
//! compiles without `web-sys`. The production
//! `web_sys::CanvasRenderingContext2d`-backed binding lives in the
//! `nhc-render-wasm` crate at `web_canvas.rs`; native unit tests
//! exercise the dispatch through the recording mock from
//! [`crate::painter::canvas`]'s test module by way of a
//! crate-private `RecCtx` alias.
//!
//! Coordinate setup mirrors the SVG entry point: paint a
//! background-coloured rectangle at the canvas's natural origin,
//! then push a single `translate(padding * scale) * scale(scale)`
//! transform so subsequent paints land in IR space (the same
//! contract the per-op handlers expect).

use crate::ir::{floor_ir_buffer_has_identifier, root_as_floor_ir};
use crate::painter::canvas::{Canvas2DCtx, CanvasPainter};
use crate::painter::{Painter, Transform};

use super::png::{
    dispatch_ops, resolve_layer_filter, BARE_SKIP_OPS, BG_B, BG_G, BG_R,
};

/// Errors the IR → Canvas2D path can surface. Mirrors
/// [`super::svg::SvgError`] minus the rasteriser-specific failure
/// modes.
#[derive(Debug)]
pub enum CanvasError {
    /// The buffer didn't parse as a `FloorIR` (missing identifier
    /// or schema mismatch).
    InvalidBuffer(String),
    /// `layer` argument didn't match any known IR layer name.
    UnknownLayer(String),
}

impl std::fmt::Display for CanvasError {
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

impl std::error::Error for CanvasError {}

/// Compute the canvas dimensions a [`floor_ir_to_canvas`] call
/// would produce for `(buf, scale)`.
///
/// JS dispatchers call this before sizing the destination
/// canvas (Canvas2D rendering clips to whatever size the
/// destination already has, so the canvas needs the right dims
/// up front). Returns `(width, height)` in CSS pixels.
pub fn canvas_dims(buf: &[u8], scale: f32) -> Result<(u32, u32), CanvasError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(CanvasError::InvalidBuffer(
            "buffer does not carry the NIR5 file_identifier".to_string(),
        ));
    }
    let fir = root_as_floor_ir(buf)
        .map_err(|e| CanvasError::InvalidBuffer(e.to_string()))?;
    let cell = fir.cell() as f32;
    let padding = fir.padding() as f32;
    let canvas_w = ((fir.width_tiles() as f32 * cell + 2.0 * padding) * scale)
        .round()
        .max(0.0) as u32;
    let canvas_h = ((fir.height_tiles() as f32 * cell + 2.0 * padding) * scale)
        .round()
        .max(0.0) as u32;
    Ok((canvas_w, canvas_h))
}

/// Render a `FloorIR` buffer onto a Canvas2D surface.
///
/// `scale` multiplies the canvas dimensions; `1.0` matches the
/// natural canvas. `layer` (if `Some`) filters dispatch to one
/// layer through the same [`super::png::resolve_layer_filter`]
/// the PNG / SVG entry points use. `bare` (when `true`) elides
/// the four decoration layers (`floor_detail`, `thematic_detail`,
/// `terrain_detail`, `surface_features`) — mirrors the SVG `bare`
/// flag for the web `/admin` debug visualisation.
///
/// The caller is responsible for sizing the destination canvas
/// to `(width_tiles * cell + 2 * padding) * scale` in CSS pixels
/// before invoking this function. The painter does not touch the
/// canvas dimensions; it only draws.
///
/// Returns the canvas dimensions in CSS pixels so the JS
/// dispatcher can confirm the destination matches.
pub fn floor_ir_to_canvas<C: Canvas2DCtx>(
    buf: &[u8],
    scale: f32,
    layer: Option<&str>,
    bare: bool,
    ctx: &C,
) -> Result<(u32, u32), CanvasError> {
    if buf.len() < 8 || !floor_ir_buffer_has_identifier(buf) {
        return Err(CanvasError::InvalidBuffer(
            "buffer does not carry the NIR5 file_identifier".to_string(),
        ));
    }
    let layer_filter =
        resolve_layer_filter(layer).map_err(CanvasError::UnknownLayer)?;
    let skip_filter = if bare { Some(BARE_SKIP_OPS) } else { None };

    let fir = root_as_floor_ir(buf)
        .map_err(|e| CanvasError::InvalidBuffer(e.to_string()))?;

    let cell = fir.cell() as f32;
    let padding = fir.padding() as f32;
    let canvas_w_f = (fir.width_tiles() as f32 * cell + 2.0 * padding) * scale;
    let canvas_h_f = (fir.height_tiles() as f32 * cell + 2.0 * padding) * scale;
    let canvas_w = canvas_w_f.round().max(0.0) as u32;
    let canvas_h = canvas_h_f.round().max(0.0) as u32;

    // Background fill — paint the parchment-tone rect at canvas
    // pixel (0, 0) BEFORE pushing the IR-space transform so the
    // background covers the full surface including the padding
    // band. Byte-equivalent to the SVG entry point's
    // `<rect width="100%" height="100%" fill="#F5EDE0"/>` and
    // `tiny_skia::Pixmap::fill(BG)` in `floor_ir_to_png`.
    ctx.set_fill_style(&format!("rgb({BG_R}, {BG_G}, {BG_B})"));
    ctx.fill_rect(0.0, 0.0, canvas_w_f as f64, canvas_h_f as f64);

    let mut painter = CanvasPainter::new(ctx, canvas_w, canvas_h);
    // Push the canvas-space transform so the per-op handlers can
    // emit raw IR coords without each one re-applying the
    // (padding * scale) offset / scale factor. The PNG entry
    // point bakes the same matrix into the SkiaPainter via
    // `with_transform`; the SVG entry point wraps the body in an
    // outer `<g transform="...">` envelope. Same contract.
    painter.push_transform(Transform {
        sx: scale,
        kx: 0.0,
        tx: padding * scale,
        ky: 0.0,
        sy: scale,
        ty: padding * scale,
    });
    dispatch_ops(&fir, layer_filter, skip_filter, &mut painter);
    painter.pop_transform();

    Ok((canvas_w, canvas_h))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::{finish_floor_ir_buffer, FloorIR, FloorIRArgs};
    use crate::painter::canvas::{
        Canvas2DCtx, CanvasLineCap, CanvasLineJoin,
    };
    use flatbuffers::FlatBufferBuilder;
    use std::cell::RefCell;
    use std::rc::Rc;

    /// Minimal Canvas2DCtx mock — records every call against a
    /// shared log so the entry-point tests can assert envelope /
    /// background / transform setup. Mirrors the recording mock
    /// in `painter::canvas::tests` but with a thinner op enum
    /// (we only assert on a handful of ops at the entry-point
    /// granularity).
    #[derive(Clone, Debug, PartialEq)]
    enum Op {
        Save,
        Restore,
        FillRect(f64, f64, f64, f64),
        SetFillStyle(String),
        Transform(f64, f64, f64, f64, f64, f64),
        SetTransform(f64, f64, f64, f64, f64, f64),
        SetGlobalAlpha(f64),
        Other,
    }

    #[derive(Debug)]
    struct RecCtx {
        next_id: Rc<RefCell<usize>>,
        log: Rc<RefCell<Vec<Op>>>,
    }

    impl RecCtx {
        fn new() -> Self {
            Self {
                next_id: Rc::new(RefCell::new(1)),
                log: Rc::new(RefCell::new(Vec::new())),
            }
        }
        fn ops(&self) -> Vec<Op> {
            self.log.borrow().clone()
        }
    }

    impl Canvas2DCtx for RecCtx {
        fn save(&self) {
            self.log.borrow_mut().push(Op::Save);
        }
        fn restore(&self) {
            self.log.borrow_mut().push(Op::Restore);
        }
        fn fill_rect(&self, x: f64, y: f64, w: f64, h: f64) {
            self.log.borrow_mut().push(Op::FillRect(x, y, w, h));
        }
        fn stroke_rect(&self, _: f64, _: f64, _: f64, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn begin_path(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn close_path(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn move_to(&self, _: f64, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn line_to(&self, _: f64, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn quadratic_curve_to(&self, _: f64, _: f64, _: f64, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn bezier_curve_to(
            &self,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
        ) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn arc(&self, _: f64, _: f64, _: f64, _: f64, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn ellipse(
            &self,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
            _: f64,
        ) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn fill(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn fill_even_odd(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn stroke(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn clip(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn clip_even_odd(&self) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn transform(&self, a: f64, b: f64, c: f64, d: f64, e: f64, f: f64) {
            self.log
                .borrow_mut()
                .push(Op::Transform(a, b, c, d, e, f));
        }
        fn set_transform(
            &self,
            a: f64,
            b: f64,
            c: f64,
            d: f64,
            e: f64,
            f: f64,
        ) {
            self.log
                .borrow_mut()
                .push(Op::SetTransform(a, b, c, d, e, f));
        }
        fn set_fill_style(&self, css: &str) {
            self.log
                .borrow_mut()
                .push(Op::SetFillStyle(css.to_string()));
        }
        fn set_stroke_style(&self, _: &str) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn set_line_width(&self, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn set_line_cap(&self, _: CanvasLineCap) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn set_line_join(&self, _: CanvasLineJoin) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn set_miter_limit(&self, _: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
        fn set_global_alpha(&self, alpha: f64) {
            self.log.borrow_mut().push(Op::SetGlobalAlpha(alpha));
        }
        fn create_offscreen(&self, _w: u32, _h: u32) -> Self {
            let mut next = self.next_id.borrow_mut();
            *next += 1;
            Self {
                next_id: Rc::clone(&self.next_id),
                log: Rc::clone(&self.log),
            }
        }
        fn draw_image_at(&self, _src: &Self, _x: f64, _y: f64) {
            self.log.borrow_mut().push(Op::Other);
        }
    }

    /// Minimal valid FloorIR buffer for shape-level smoke tests.
    fn build_minimal_buf(width_tiles: u32, height_tiles: u32) -> Vec<u8> {
        let mut fbb = FlatBufferBuilder::new();
        let fir = FloorIR::create(
            &mut fbb,
            &FloorIRArgs {
                major: 5,
                minor: 0,
                width_tiles,
                height_tiles,
                cell: 32,
                padding: 32,
                ..Default::default()
            },
        );
        finish_floor_ir_buffer(&mut fbb, fir);
        fbb.finished_data().to_vec()
    }

    #[test]
    fn empty_buffer_paints_background_and_returns_canvas_dims() {
        let buf = build_minimal_buf(2, 2);
        let ctx = RecCtx::new();
        // 2 × 2 tiles, cell=32, padding=32 → (2*32 + 64) = 128.
        let (w, h) = floor_ir_to_canvas(&buf, 1.0, None, false, &ctx)
            .expect("encode succeeds");
        assert_eq!((w, h), (128, 128));
        let ops = ctx.ops();
        assert!(matches!(
            &ops[0],
            Op::SetFillStyle(s) if s == "rgb(245, 237, 224)",
        ));
        assert_eq!(ops[1], Op::FillRect(0.0, 0.0, 128.0, 128.0));
    }

    #[test]
    fn pushes_canvas_space_transform_after_background() {
        let buf = build_minimal_buf(2, 2);
        let ctx = RecCtx::new();
        floor_ir_to_canvas(&buf, 2.0, None, false, &ctx).unwrap();
        let ops = ctx.ops();
        // Save (from push_transform's ctx.save) then Transform
        // matching translate(padding*scale, padding*scale) *
        // scale(scale, scale). Canvas2D arg order is
        // (sx, ky, kx, sy, tx, ty) — for scale=2.0, padding=32:
        // (2.0, 0.0, 0.0, 2.0, 64.0, 64.0).
        assert!(
            ops.contains(&Op::Save),
            "expected Save call from push_transform, got {ops:?}",
        );
        assert!(
            ops.contains(&Op::Transform(2.0, 0.0, 0.0, 2.0, 64.0, 64.0)),
            "expected canvas-space transform translate(64, 64) * \
             scale(2, 2), got {ops:?}",
        );
    }

    #[test]
    fn scale_multiplies_canvas_dims() {
        let buf = build_minimal_buf(4, 3);
        let ctx = RecCtx::new();
        let (w, h) = floor_ir_to_canvas(&buf, 2.0, None, false, &ctx).unwrap();
        // (4*32 + 64) * 2 = 384, (3*32 + 64) * 2 = 320.
        assert_eq!((w, h), (384, 320));
    }

    #[test]
    fn pop_transform_balances_push_for_clean_painter_drop() {
        let buf = build_minimal_buf(2, 2);
        let ctx = RecCtx::new();
        floor_ir_to_canvas(&buf, 1.0, None, false, &ctx).unwrap();
        let ops = ctx.ops();
        // The single push_transform / pop_transform pair surfaces
        // as exactly one Save + one Restore at the entry-point
        // level (no per-op handlers fired since the empty buffer
        // has no ops[]).
        let saves = ops.iter().filter(|o| matches!(o, Op::Save)).count();
        let restores = ops.iter().filter(|o| matches!(o, Op::Restore)).count();
        assert_eq!(saves, 1);
        assert_eq!(restores, 1);
    }

    #[test]
    fn canvas_dims_matches_render_dims() {
        // The pre-flight `canvas_dims` helper must agree with
        // the dims returned by `floor_ir_to_canvas` so JS
        // dispatchers can resize the destination once before
        // rendering. 4 × 3 tiles, cell=32, padding=32, scale=1.5
        // → canvas_w = (4*32 + 64) * 1.5 = 288, canvas_h = 240.
        let buf = build_minimal_buf(4, 3);
        let (dw, dh) = canvas_dims(&buf, 1.5).expect("dims succeed");
        let ctx = RecCtx::new();
        let (rw, rh) =
            floor_ir_to_canvas(&buf, 1.5, None, false, &ctx).unwrap();
        assert_eq!((dw, dh), (rw, rh));
        assert_eq!((dw, dh), (288, 240));
    }

    #[test]
    fn canvas_dims_rejects_invalid_buffer() {
        let err = canvas_dims(&[0u8; 16], 1.0).unwrap_err();
        assert!(matches!(err, CanvasError::InvalidBuffer(_)));
    }

    #[test]
    fn rejects_buffer_without_identifier() {
        let ctx = RecCtx::new();
        let err = floor_ir_to_canvas(&[0u8; 16], 1.0, None, false, &ctx)
            .unwrap_err();
        assert!(matches!(err, CanvasError::InvalidBuffer(_)));
    }

    #[test]
    fn unknown_layer_is_rejected() {
        let buf = build_minimal_buf(2, 2);
        let ctx = RecCtx::new();
        let err = floor_ir_to_canvas(
            &buf,
            1.0,
            Some("not-a-layer"),
            false,
            &ctx,
        )
        .unwrap_err();
        assert!(matches!(err, CanvasError::UnknownLayer(_)));
    }

    #[test]
    fn known_layer_names_are_accepted() {
        let buf = build_minimal_buf(2, 2);
        for layer in [
            "shadows",
            "hatching",
            "structural",
            "decorators",
            "fixtures",
        ] {
            let ctx = RecCtx::new();
            floor_ir_to_canvas(&buf, 1.0, Some(layer), false, &ctx)
                .unwrap_or_else(|e| panic!("layer {layer:?}: {e}"));
        }
    }
}
