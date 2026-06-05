//! Tier 1 native render bench — Phase M of
//! `plans/wasm-render-caching.md`.
//!
//! Drives a committed `.nir` fixture through `floor_ir_to_canvas_profiled`
//! on a `RasterCtx` (tiny_skia-backed `Canvas2DCtx`) and reports two
//! signals:
//!
//! - **Cache counts** (`sprite_hits/misses`, `grove_polygon_hits/misses`):
//!   deterministic integers — they do not vary run to run. This is the
//!   trustworthy part. A regression like "the sprite cache silently
//!   stopped hitting" shows up here as a count swing with zero flakiness.
//!   The native `RasterCtx` renders through the same `CanvasPainter` the
//!   browser uses, so the counts match the browser exactly.
//! - **Per-layer wall-clock**: informational trend only. `RasterCtx` is
//!   tiny_skia, NOT Canvas2D, so its ms does NOT reflect the real
//!   `drawImage`/`fill` compositor cost — that is Tier 2's job
//!   (`tests/perf/test_wasm_render_bench.py`). Treat these numbers as a
//!   rough algorithmic-cost shape, never as the headline `total`.
//!
//! Opt-in (slow on big fixtures — tiny_skia software-rasterises the full
//! 3456×2880 city canvas). Run explicitly:
//!
//! ```sh
//! cargo test -p nhc-render --test render_timing -- --ignored --nocapture
//! ```
//!
//! Tunable via env:
//! - `NHC_BENCH_FIXTURES` — comma-separated fixture dir names. Default:
//!   the city alone (the primary workload). Add the town / cave / dungeon
//!   for secondary coverage:
//!   `NHC_BENCH_FIXTURES=seed19_city_surface,seed7_town_surface`.
//! - `NHC_BENCH_WARMUP` / `NHC_BENCH_TIMED` — iteration counts
//!   (default 1 / 3). Counts need only one render; the extra timed runs
//!   just stabilise the informational median.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use nhc_render::painter::RasterCtx;
use nhc_render::transform::canvas::{canvas_dims, floor_ir_to_canvas_profiled};

/// Layer names in the order `floor_ir_to_canvas_profiled` fires them.
const LAYERS: &[&str] = &[
    "shadow", "hatch", "paint", "stroke", "stamp", "roof", "path", "fixture",
];

fn fixtures_root() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .and_then(Path::parent)
        .expect("crate manifest has a repo root above it")
        .join("tests/fixtures/floor_ir")
}

fn env_usize(key: &str, default: usize) -> usize {
    env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn fixtures() -> Vec<String> {
    match env::var("NHC_BENCH_FIXTURES") {
        Ok(v) if !v.trim().is_empty() => {
            v.split(',').map(|s| s.trim().to_string()).collect()
        }
        // Default: the primary workload only. Secondary fixtures are
        // opt-in because tiny_skia renders of cave/dungeon are minutes
        // each.
        _ => vec!["seed19_city_surface".to_string()],
    }
}

fn median(mut xs: Vec<f64>) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = xs.len();
    if n % 2 == 1 {
        xs[n / 2]
    } else {
        (xs[n / 2 - 1] + xs[n / 2]) / 2.0
    }
}

fn bench_fixture(name: &str, warmup: usize, timed: usize) {
    let path = fixtures_root().join(name).join("floor.nir");
    let buf = fs::read(&path)
        .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let (w, h) =
        canvas_dims(&buf, 1.0).unwrap_or_else(|e| panic!("canvas_dims: {e}"));

    // Warmup (discarded) — primes allocator / page cache.
    for _ in 0..warmup {
        let ctx = RasterCtx::new(w, h);
        floor_ir_to_canvas_profiled(&buf, 1.0, false, &ctx, |_| {})
            .expect("warmup render");
    }

    // Timed runs. Per-layer durations accumulate column-wise; the cache
    // diagnostics are deterministic so we just keep the last.
    let mut per_layer: Vec<Vec<f64>> = vec![Vec::new(); LAYERS.len()];
    let mut totals: Vec<f64> = Vec::new();
    let mut last_diag = Default::default();

    for _ in 0..timed {
        let ctx = RasterCtx::new(w, h);
        let start = Instant::now();
        let mut prev = start;
        let mut idx = 0usize;
        let (_, _, diag) = floor_ir_to_canvas_profiled(
            &buf,
            1.0,
            false,
            &ctx,
            |_name| {
                let now = Instant::now();
                per_layer[idx].push((now - prev).as_secs_f64() * 1000.0);
                prev = now;
                idx += 1;
            },
        )
        .expect("timed render");
        totals.push((Instant::now() - start).as_secs_f64() * 1000.0);
        last_diag = diag;
    }

    eprintln!("\n[tier1] fixture={name} canvas={w}x{h} timed={timed}");
    eprint!("[tier1]   layers(ms median):");
    for (i, layer) in LAYERS.iter().enumerate() {
        eprint!(" {layer}={:.2}", median(per_layer[i].clone()));
    }
    eprintln!();
    eprintln!("[tier1]   total(ms median)={:.2}", median(totals));
    // The deterministic, trustworthy signal.
    eprintln!("[tier1]   counts:{}", last_diag.profile_suffix());
    eprintln!(
        "[tier1]   NOTE tiny_skia ms is algorithmic-cost trend only; \
         the real total is Tier 2 (browser Canvas2D)."
    );
}

/// Opt-in Tier 1 bench. Ignored by default; run with `--ignored`.
#[test]
#[ignore = "perf bench — run with --ignored --nocapture"]
fn tier1_native_render_bench() {
    let warmup = env_usize("NHC_BENCH_WARMUP", 1);
    let timed = env_usize("NHC_BENCH_TIMED", 3);
    for name in fixtures() {
        bench_fixture(&name, warmup, timed);
    }
}
