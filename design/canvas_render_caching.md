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

Loads the **real shipped `pkg/` bundle** in headless Chromium over a localhost
origin, calls `render_ir_to_canvas_profiled` directly (no whole-floor cache),
WARMUP=3 + TIMED=20, and reports min/median/p95 per layer + total. It is
**reporting-only** — it asserts liveness (one profile line per render) but never
a millisecond threshold (absolute ms is hardware-bound, and there is no CI to
gate). A staleness guard fails the run if `pkg/` is older than `crates/*/src`,
so it can never silently time stale code.

## ⚠️ Headless is software-rendered — read before trusting absolute ms

Headless Chromium rasterises Canvas2D in **software** (no GPU), so Tier 2's
absolute numbers are paint-dominated and roughly an order of magnitude slower
than a real GPU-accelerated browser. The original ~262 ms town baseline was
captured in a real browser; **Tier 2 headless numbers are not comparable to
it.** What Tier 2 *is* good for: a **reproducible relative baseline** for
phase-over-phase deltas (the post-3.D run measured a 3.8 % total spread — well
under the 5 % stability target) and the deterministic cache counts. Track the
delta a phase produces, not the absolute total. For an absolute production
number, capture a real GPU browser separately (e.g. DevTools on a deployed
session).

## Post-3.D baseline (recorded 2026-06-05, seed19 city)

Both tiers, same fixture, cache counts identical across tiers
(`sprite_hits=16 sprite_misses=141 grove_polygon_hits=0 grove_polygon_misses=0`
— 157 sprite stamps, low reuse across the 256-bucket space; grove memo
unwired):

| layer (ms) | Tier 2 headless median | Tier 1 tiny_skia median |
|------------|-----------------------:|------------------------:|
| total      | 8365.70                | 25256.42                |
| paint      | 7984.40                | 9590.65                 |
| roof       | 230.55                 | 14407.37                |
| fixture    | 132.80                 | 1014.50                 |
| stroke     | 11.70                  | 147.29                  |
| stamp      | 6.40                   | 70.71                   |
| shadow     | 0.10                   | 25.17                   |
| hatch/path | 0.00                   | 0.01                    |

Tier 2 total spread (max−min)/median = **3.8 %**. Note the two software
rasterisers disagree on the layer split (Tier 2 paint-dominated; Tier 1
roof-dominated), and both differ from a GPU browser's fixture/roof balance —
another reason the absolute split is not load-bearing; the counts and the
phase-over-phase delta are.

The running local table of phase ↔ profile pairs lives (gitignored) at
`debug/wasm-render-caching-profile.md`.
