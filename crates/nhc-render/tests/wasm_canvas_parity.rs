//! WASM-canvas parity harness — Phase 0 of
//! `plans/wasm-render-caching.md`.
//!
//! Routes a `FloorIR` buffer through `floor_ir_to_canvas` driving
//! a `RasterCtx` (tiny_skia-backed `Canvas2DCtx`) and compares the
//! result to a per-fixture `wasm_canvas_reference.png` at
//! PSNR ≥ 30 dB. The PNG-path parity gate
//! (`tests/unit/test_ir_png_parity.py`) catches drift on
//! `SkiaPainter`; this gate catches drift on `CanvasPainter`
//! before it ships to the browser.
//!
//! Set `REGEN_WASM_CANVAS=1` to overwrite the reference PNGs from
//! the current render output. Same code path as the comparison —
//! no risk of regen-time vs test-time divergence.
//!
//! Reference fixtures (three for coverage breadth):
//! - `seed7_town_surface` — town, fixture/roof-heavy
//! - `seed99_cave_cave_cave` — cave, shadow/hatch-heavy
//! - `seed7_octagon_crypt_dungeon` — dungeon, paint/stamp-heavy

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use nhc_render::painter::RasterCtx;
use nhc_render::transform::canvas::{canvas_dims, floor_ir_to_canvas};
use tiny_skia::Pixmap;

const FIXTURE_NAMES: &[&str] = &[
    "seed7_town_surface",
    "seed99_cave_cave_cave",
    "seed7_octagon_crypt_dungeon",
];

const PSNR_MIN_DB: f64 = 30.0;
const WASM_CANVAS_REF: &str = "wasm_canvas_reference.png";

fn fixtures_root() -> PathBuf {
    // Tests run from the crate root (`crates/nhc-render`). Walk
    // up two levels to reach the repo root, then into
    // `tests/fixtures/floor_ir`.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .and_then(Path::parent)
        .expect("crate manifest has a repo root above it")
        .join("tests/fixtures/floor_ir")
}

fn render_fixture(name: &str) -> Pixmap {
    let path = fixtures_root().join(name).join("floor.nir");
    let buf = fs::read(&path)
        .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let (w, h) = canvas_dims(&buf, 1.0)
        .unwrap_or_else(|e| panic!("canvas_dims {name}: {e}"));
    let ctx = RasterCtx::new(w, h);
    floor_ir_to_canvas(&buf, 1.0, None, false, &ctx)
        .unwrap_or_else(|e| panic!("floor_ir_to_canvas {name}: {e}"));
    ctx.pixmap_clone()
}

fn reference_path(name: &str) -> PathBuf {
    fixtures_root().join(name).join(WASM_CANVAS_REF)
}

fn regen_mode() -> bool {
    matches!(env::var("REGEN_WASM_CANVAS"), Ok(v) if v == "1")
}

/// PSNR in dB across RGB channels (alpha ignored). Identical
/// images report `f64::INFINITY`; lower scores indicate more
/// drift. The 30 dB gate matches the Q1 / Q23-locked threshold in
/// `plans/wasm-render-caching.md` — Canvas2D's `drawImage`
/// resampler introduces sub-pixel drift that PNG's 50 dB gate
/// wouldn't tolerate, so the WASM-canvas budget is relaxed.
fn psnr_db(a: &Pixmap, b: &Pixmap) -> f64 {
    assert_eq!(
        (a.width(), a.height()),
        (b.width(), b.height()),
        "psnr_db: pixmap dimensions differ ({}×{} vs {}×{})",
        a.width(),
        a.height(),
        b.width(),
        b.height(),
    );
    let bytes_a = a.data();
    let bytes_b = b.data();
    debug_assert_eq!(bytes_a.len(), bytes_b.len());

    let mut sum_sq: f64 = 0.0;
    let mut count: u64 = 0;
    // tiny_skia layout is RGBA per pixel; iterate in 4-byte
    // strides, sum squared diffs over R, G, B only.
    for (chunk_a, chunk_b) in
        bytes_a.chunks_exact(4).zip(bytes_b.chunks_exact(4))
    {
        for i in 0..3 {
            let d = chunk_a[i] as f64 - chunk_b[i] as f64;
            sum_sq += d * d;
        }
        count += 3;
    }
    if sum_sq == 0.0 || count == 0 {
        return f64::INFINITY;
    }
    let mse = sum_sq / count as f64;
    20.0 * (255.0_f64).log10() - 10.0 * mse.log10()
}

fn compare_or_regen(name: &str) {
    let rendered = render_fixture(name);
    let ref_path = reference_path(name);
    if regen_mode() || !ref_path.exists() {
        let bytes = rendered
            .encode_png()
            .unwrap_or_else(|e| panic!("encode_png {name}: {e}"));
        fs::write(&ref_path, &bytes)
            .unwrap_or_else(|e| panic!("write {}: {e}", ref_path.display()));
        eprintln!(
            "[wasm_canvas_parity] {} wrote {} ({} bytes)",
            name,
            ref_path.display(),
            bytes.len(),
        );
        return;
    }
    let ref_bytes = fs::read(&ref_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", ref_path.display()));
    let reference = Pixmap::decode_png(&ref_bytes)
        .unwrap_or_else(|e| panic!("decode_png {name}: {e}"));
    let psnr = psnr_db(&rendered, &reference);
    assert!(
        psnr >= PSNR_MIN_DB,
        "{name}: PSNR {:.2} dB below {:.2} dB gate \
         (regenerate with REGEN_WASM_CANVAS=1 after intentional drift)",
        psnr,
        PSNR_MIN_DB,
    );
}

#[test]
fn town_surface_round_trips_at_30db() {
    compare_or_regen(FIXTURE_NAMES[0]);
}

#[test]
fn cave_surface_round_trips_at_30db() {
    compare_or_regen(FIXTURE_NAMES[1]);
}

#[test]
fn dungeon_floor_round_trips_at_30db() {
    compare_or_regen(FIXTURE_NAMES[2]);
}

/// Sanity gate on the comparator: identical pixmaps report
/// infinity, mismatched ones report finite. Catches accidental
/// always-pass bugs in `psnr_db`.
#[test]
fn psnr_comparator_distinguishes_identical_from_distinct() {
    let a = Pixmap::new(8, 8).unwrap();
    let mut b = Pixmap::new(8, 8).unwrap();
    b.fill(tiny_skia::Color::from_rgba8(255, 0, 0, 255));
    assert!(psnr_db(&a, &a).is_infinite(), "identical → infinity");
    let finite = psnr_db(&a, &b);
    assert!(
        finite.is_finite() && finite < 30.0,
        "distinct → finite low score, got {finite}",
    );
}
