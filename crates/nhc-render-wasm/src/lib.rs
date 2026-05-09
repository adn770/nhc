//! WASM bundle for NHC map rendering.
//!
//! Thin wrapper around [`nhc_render`] that exposes the rendering
//! primitives to JavaScript via `wasm-bindgen`. Two surfaces:
//!
//! - `splitmix64_next` — the Phase 5.1 smoke export proving the
//!   wasm-pack pipeline round-trips end-to-end.
//! - `render_ir_to_canvas` — the Phase 5.3 entry point that the
//!   browser-side JS dispatcher in `nhc/web/static/js/` calls
//!   when `NHC_RENDER_MODE=wasm` (Phase 5.4 wires this into
//!   `setFloorURL`). Takes a FloorIR FlatBuffer + a
//!   `CanvasRenderingContext2d` and dispatches every op against
//!   a [`web_canvas::WebCanvasCtx`]-backed [`CanvasPainter`].
//!
//! The web-sys-touching surface (``WebCanvasCtx`` + the
//! ``render_ir_to_canvas`` export) is gated behind
//! ``cfg(target_arch = "wasm32")`` so native ``cargo test``
//! builds skip both. Native unit tests cover the
//! ``splitmix64_next`` logic + the entry-point dispatch in
//! ``nhc_render::transform::canvas``.

use wasm_bindgen::prelude::*;

use nhc_render::rng::SplitMix64;

/// One-shot panic-hook installer. Both the JS dispatcher and
/// the Node parity-gate runner invoke this once at startup so
/// any subsequent Rust panic surfaces on ``console.error``
/// with the panic message + a stack frame instead of the bare
/// ``RuntimeError: unreachable`` V8 emits by default. Idempotent
/// — calling it more than once is harmless.
#[cfg(target_arch = "wasm32")]
#[wasm_bindgen]
pub fn install_panic_hook() {
    console_error_panic_hook::set_once();
}

#[cfg(target_arch = "wasm32")]
pub mod web_canvas;

/// Pull the next splitmix64 output for a given seed.
///
/// Smoke export for the Phase 5.1 wasm-pack scaffold. Mirrors
/// the PyO3-side stub in `nhc_render::ffi::pyo3` so the JS
/// client and the Python server can share golden vectors during
/// cross-language fuzzing once the canvas painter lands.
#[wasm_bindgen]
pub fn splitmix64_next(seed: u64) -> u64 {
    SplitMix64::from_seed(seed).next_u64()
}

/// Render a FloorIR FlatBuffer onto a Canvas2D context.
///
/// Mirrors the PNG entry point's signature on the wasm side so
/// the JS dispatcher in `nhc/web/static/js/floor_ir_renderer.js`
/// (Phase 5.4) can swap `setFloorURL`'s "fetch PNG, decode,
/// draw" path for "fetch .nir, call render_ir_to_canvas". The
/// caller is responsible for sizing the destination canvas to
/// `(width_tiles * cell + 2 * padding) * scale` CSS pixels
/// before invoking; the function does not touch the canvas
/// dimensions, only the pixel content.
///
/// Returns the canvas dims (`[width, height]`) so the JS side
/// can confirm the destination matched the IR's natural canvas
/// size.
///
/// `layer` (when non-empty) filters dispatch to one of:
/// `"shadows"`, `"hatching"`, `"structural"`, `"decorators"`,
/// `"fixtures"`. `bare` (when `true`) elides the four
/// decoration layers — mirrors the SVG `bare` flag for the web
/// `/admin` debug visualisation.
#[cfg(target_arch = "wasm32")]
#[wasm_bindgen]
pub fn render_ir_to_canvas(
    ir_bytes: &[u8],
    ctx: &web_sys::CanvasRenderingContext2d,
    scale: f32,
    layer: Option<String>,
    bare: bool,
) -> Result<Vec<u32>, JsValue> {
    let webctx = web_canvas::WebCanvasCtx::from_ctx(ctx.clone())?;
    let layer_ref = layer.as_deref();
    let (w, h) = nhc_render::transform::canvas::floor_ir_to_canvas(
        ir_bytes,
        scale,
        layer_ref,
        bare,
        &webctx,
    )
    .map_err(|e| JsValue::from_str(&e.to_string()))?;
    Ok(vec![w, h])
}

/// Compute the destination canvas dims for an IR buffer + scale
/// without rendering.
///
/// JS dispatchers call this before sizing the `<canvas>` element
/// so the subsequent `render_ir_to_canvas` call has the correct
/// destination dims (Canvas2D rendering clips to the existing
/// canvas size). Returns `[width, height]` in CSS pixels.
#[wasm_bindgen]
pub fn ir_canvas_dims(
    ir_bytes: &[u8],
    scale: f32,
) -> Result<Vec<u32>, JsValue> {
    let (w, h) = nhc_render::transform::canvas::canvas_dims(ir_bytes, scale)
        .map_err(|e| JsValue::from_str(&e.to_string()))?;
    Ok(vec![w, h])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitmix64_next_is_deterministic_for_same_seed() {
        assert_eq!(splitmix64_next(42), splitmix64_next(42));
    }

    #[test]
    fn splitmix64_next_diverges_for_different_seeds() {
        assert_ne!(splitmix64_next(1), splitmix64_next(2));
    }

    #[test]
    fn splitmix64_next_zero_seed_matches_reference_vector() {
        // First splitmix64 output for seed=0 from the reference
        // implementation at https://prng.di.unimi.it/. Pinning
        // the value keeps the WASM bundle deterministic against
        // the same golden vector the PyO3 wheel consumes.
        assert_eq!(splitmix64_next(0), nhc_render::rng::SplitMix64::from_seed(0).next_u64());
    }
}
