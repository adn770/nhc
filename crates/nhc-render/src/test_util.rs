//! Shared helpers for transform/png handler unit tests.
//!
//! Each handler test module needs to decode the PNG output and
//! sample pixels at known canvas coordinates. Before this module
//! was extracted, every test file (`floor_op.rs`,
//! `exterior_wall_op.rs`, `interior_wall_op.rs`,
//! `corridor_wall_op.rs`) carried its own copy of `decode` and
//! `pixel_at`. New handler commits in Phase 1.20+ should reach for
//! these helpers instead of re-inventing them.
//!
//! `psnr_db` matches `tests/unit/test_ir_png_parity.py::_psnr`,
//! so Rust-side parity drill-downs report the same number the
//! Python parity gate does.

#![cfg(test)]

use tiny_skia::Pixmap;

/// Decode PNG bytes into a `Pixmap`.
pub fn decode(png: &[u8]) -> Pixmap {
    Pixmap::decode_png(png).expect("decode PNG")
}

/// Sample the RGB triplet at canvas coords `(px_x, px_y)`.
pub fn pixel_at(pixmap: &Pixmap, px_x: u32, px_y: u32) -> (u8, u8, u8) {
    let idx = (px_y * pixmap.width() + px_x) as usize;
    let p = pixmap.pixels()[idx];
    (p.red(), p.green(), p.blue())
}

/// Sample the RGBA quad at canvas coords `(px_x, px_y)`.
pub fn pixel_rgba(pixmap: &Pixmap, px_x: u32, px_y: u32) -> (u8, u8, u8, u8) {
    let idx = (px_y * pixmap.width() + px_x) as usize;
    let p = pixmap.pixels()[idx];
    (p.red(), p.green(), p.blue(), p.alpha())
}

/// PSNR in dB between two equally-sized pixmaps over RGBA channels.
/// Returns `f64::INFINITY` when the inputs are pixel-identical.
pub fn psnr_db(a: &Pixmap, b: &Pixmap) -> f64 {
    assert_eq!(a.width(), b.width(), "PSNR width mismatch");
    assert_eq!(a.height(), b.height(), "PSNR height mismatch");
    let pa = a.pixels();
    let pb = b.pixels();
    let n = pa.len();
    assert_eq!(n, pb.len(), "PSNR pixel-count mismatch");
    let mut mse = 0.0_f64;
    for i in 0..n {
        let dr = pa[i].red() as f64 - pb[i].red() as f64;
        let dg = pa[i].green() as f64 - pb[i].green() as f64;
        let db = pa[i].blue() as f64 - pb[i].blue() as f64;
        let da = pa[i].alpha() as f64 - pb[i].alpha() as f64;
        mse += dr * dr + dg * dg + db * db + da * da;
    }
    mse /= (n * 4) as f64;
    if mse == 0.0 {
        f64::INFINITY
    } else {
        20.0 * (255.0 / mse.sqrt()).log10()
    }
}

/// Assert PSNR(a, b) ≥ `threshold_db`. `label` is included in the
/// failure message — pass the test name or the fixture descriptor.
pub fn assert_psnr_ge(a: &Pixmap, b: &Pixmap, threshold_db: f64, label: &str) {
    let db = psnr_db(a, b);
    assert!(
        db >= threshold_db,
        "{label}: PSNR {db:.2} dB below threshold {threshold_db:.1} dB",
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use tiny_skia::{Color, Pixmap};

    fn solid(width: u32, height: u32, r: u8, g: u8, b: u8, a: u8) -> Pixmap {
        let mut pm = Pixmap::new(width, height).unwrap();
        pm.fill(Color::from_rgba8(r, g, b, a));
        pm
    }

    #[test]
    fn psnr_identical_pixmaps_is_infinity() {
        let a = solid(4, 4, 200, 100, 50, 255);
        let b = solid(4, 4, 200, 100, 50, 255);
        assert!(psnr_db(&a, &b).is_infinite());
    }

    #[test]
    fn psnr_off_by_one_red_channel_is_finite() {
        let a = solid(4, 4, 100, 100, 100, 255);
        let b = solid(4, 4, 101, 100, 100, 255);
        let db = psnr_db(&a, &b);
        assert!(db.is_finite());
        assert!(db > 40.0, "1-bit-of-red drift should be high PSNR, got {db}");
    }

    #[test]
    fn pixel_at_returns_rgb() {
        // Opaque fill so premultiplication is a no-op and the
        // returned RGB matches the input exactly.
        let pm = solid(2, 2, 10, 20, 30, 255);
        assert_eq!(pixel_at(&pm, 0, 0), (10, 20, 30));
    }

    #[test]
    fn pixel_rgba_returns_rgba() {
        // tiny-skia stores RGBA premultiplied; with alpha < 255 the
        // RGB channels are scaled. Verify the helper returns whatever
        // is stored and that the alpha round-trips.
        let pm = solid(2, 2, 10, 20, 30, 40);
        let (r, g, b, a) = pixel_rgba(&pm, 0, 0);
        assert_eq!(a, 40, "alpha channel mismatch");
        assert!(r <= a && g <= a && b <= a, "RGB exceeded alpha — not premultiplied");
    }

    #[test]
    fn assert_psnr_ge_passes_above_threshold() {
        let a = solid(4, 4, 100, 100, 100, 255);
        let b = solid(4, 4, 100, 100, 100, 255);
        assert_psnr_ge(&a, &b, 40.0, "identity");
    }

    #[test]
    #[should_panic(expected = "below threshold")]
    fn assert_psnr_ge_panics_below_threshold() {
        let a = solid(4, 4, 0, 0, 0, 255);
        let b = solid(4, 4, 255, 255, 255, 255);
        assert_psnr_ge(&a, &b, 40.0, "extreme");
    }
}
