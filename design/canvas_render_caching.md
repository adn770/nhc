# Canvas render caching & the WASM perf harness

The browser renders each floor by rasterising a NIR buffer through the
`crates/nhc-render-wasm` bundle (see `design/canvas_rendering.md`). To make
performance work measurable, the renderer carries per-render cache
instrumentation and the repo ships a two-tier benchmark harness. This document
is the canonical record of how to measure and what the numbers mean; the
phase-by-phase optimisation work is tracked in
`~/src/plans/wasm-render-caching.md`.

## Cache instrumentation

`floor_ir_to_canvas_profiled` returns a `RenderCacheDiagnostics`
(`crates/nhc-render/src/painter/mod.rs`) alongside the canvas dims. It carries
deterministic integer counters — they do **not** vary run to run, so they
answer "did this caching change actually engage?" with zero flakiness:

- `sprite_hits` / `sprite_misses` — the Phase 3 sprite cache
  (`CanvasPainter::stamp_cached_sprite`). A miss builds a bucket template
  offscreen; a hit blits a cached one.
- `grove_polygon_hits` / `grove_polygon_misses` — the grove polygon memo.
  **Reads 0 until Phase 3.E lands** — that zero is itself the "memo not yet
  active" signal.

The wasm `render_ir_to_canvas_profiled` entry appends these to the
`[nhc-render]` console line via `RenderCacheDiagnostics::profile_suffix()`. The
struct is a flat bag of `u32`s on purpose: the deferred Phase A
`groups_eliminated` and Phase 1/2 `tile_atlas_units` counters are a one-field
add, no redesign.

## The two-tier benchmark

Both tiers consume the **same committed `.nir` fixtures** under
`tests/fixtures/floor_ir/` — the bytes are in git, so the workload is identical
on every run and every machine. The primary workload is `seed19_city_surface`,
the densest settlement the generator produces (~40 buildings, ~170 vegetation
features on a 3456×2880 canvas).

### Tier 1 — native `RasterCtx` microbench (regression tripwire)

`crates/nhc-render/tests/render_timing.rs`, opt-in (`#[ignore]`):

```sh
cargo test -p nhc-render --test render_timing -- --ignored --nocapture
# fixtures / iterations: NHC_BENCH_FIXTURES, NHC_BENCH_WARMUP, NHC_BENCH_TIMED
```

Runs the fixture through `RasterCtx` (tiny_skia). Reports the **cache counts**
(the trustworthy, deterministic signal) plus per-layer wall-clock (informational
trend only). **`RasterCtx` is tiny_skia, NOT Canvas2D** — its ms does not
reflect the real `drawImage`/`fill` compositor cost. Use Tier 1 to catch a
count swing or an algorithmic-cost regression, never as the headline `total`.

### Tier 2 — headless-browser bench (ground truth, per phase)

`tests/perf/test_wasm_render_bench.py`, opt-in (`perf` marker), needs a one-time
bootstrap:

```sh
make perf-bootstrap                              # playwright + chromium (~150 MB)
make wasm-build                                  # bundle MUST be current
pytest -m perf tests/perf/test_wasm_render_bench.py -s
# fixture / iterations: NHC_PERF_FIXTURE, NHC_PERF_WARMUP, NHC_PERF_TIMED
```

Loads the **real shipped `pkg/` bundle** in Chromium over a localhost origin,
calls `render_ir_to_canvas_profiled` directly (no whole-floor cache), WARMUP=3 +
TIMED=20, and reports min/median/p95 per layer + total. It is **reporting-only**
— it asserts liveness (one profile line per render) but never a millisecond
threshold (absolute ms is hardware-bound, and there is no CI to gate). A
staleness guard fails the run if `pkg/` is older than `crates/*/src`, so it can
never silently time stale code.

### Two modes — software (default) vs GPU (opt-in)

| | software headless (default) | `NHC_PERF_GPU=1` (headed) |
|---|---|---|
| backend | SwiftShader (CPU) | real GPU (Metal/ANGLE on a Mac) |
| absolute ms | ~25× slow, **paint-heavy** (misleading) | **realistic**, fixture/roof-heavy |
| reproducibility | high (~4 % spread) | lower (~15 %; thermal/compositor) |
| needs | nothing | desktop display (no SSH/CI); pops a window |
| use for | deterministic counts + relative tripwire | headline + which layer to optimise |

`NHC_PERF_GPU=1` launches **headed system Chrome** (falls back to the bundled
headed Chromium) with the GPU blocklist relaxed. The harness probes the WebGL
`UNMASKED_RENDERER` and prints it (`gpu_renderer=…`) so you can confirm a real
backend engaged rather than a silent SwiftShader fallback — if it says
`SwiftShader`, GPU did NOT engage and the numbers are still software.

```sh
# Production-realistic spot-check (Mac desktop, pops a Chrome window):
NHC_PERF_GPU=1 pytest -m perf tests/perf/test_wasm_render_bench.py -s
```

### ⚠️ Which number to trust

- **Software headless** absolute ms is **not** comparable to production (no GPU,
  paint-dominated). Use it for the deterministic counts and a reproducible
  relative tripwire — track the phase-over-phase *delta*, not the total.
- **GPU headed** is the production-realistic number and, crucially, shows the
  **correct layer split** (fixture/roof dominate, matching the original
  production profile — software's paint-dominated split is an artefact). Use it
  to decide *which* layer a phase should attack and to read the headline total.
  Take a larger TIMED median to tame the ~15 % spread.

## Post-3.D baseline (recorded 2026-06-05, seed19 city)

Both tiers, same fixture, cache counts identical across tiers
(`sprite_hits=16 sprite_misses=141 grove_polygon_hits=0 grove_polygon_misses=0`
— 157 sprite stamps, low reuse across the 256-bucket space; grove memo
unwired):

| layer (ms) | Tier 2 GPU (M4 Pro Metal) | Tier 2 headless (software) | Tier 1 tiny_skia |
|------------|--------------------------:|---------------------------:|-----------------:|
| total      | **333.20**                | 8365.70                    | 25256.42         |
| paint      | 42.65                     | 7984.40                    | 9590.65          |
| roof       | 156.75                    | 230.55                     | 14407.37         |
| fixture    | 124.10                    | 132.80                     | 1014.50          |
| stroke     | 2.60                      | 11.70                      | 147.29           |
| stamp      | 6.40                      | 6.40                       | 70.71            |
| shadow     | 0.10                      | 0.10                       | 25.17            |
| hatch/path | 0.00                      | 0.00                       | 0.01             |

Spread: GPU **14.9 %** (TIMED=10), software headless **3.8 %** (TIMED=20).
`gpu_renderer = "ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro)"` — a real
GPU, confirmed. The **GPU total (333 ms on the city) is the production-realistic
headline** — same ballpark as the original ~262 ms *town*, on a far heavier
floor — and its layer split (fixture+roof dominant) matches the original
production profile. The two software rasterisers (Tier 2 headless paint-heavy,
Tier 1 tiny_skia roof-heavy) disagree with each other AND with the GPU, which is
exactly why their absolute split is not load-bearing — use them for the
deterministic counts and a relative tripwire only.

The running local table of phase ↔ profile pairs lives (gitignored) at
`debug/wasm-render-caching-profile.md`.
