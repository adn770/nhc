"""Tier 2 isolated WASM render bench — Phase M.

Drives the REAL shipped wasm-pack bundle in headless Chromium over a
localhost origin, on a committed .nir fixture, with warmup + median.
This is the ground-truth perf number: the actual Canvas2D
drawImage/fill compositor cost, with every game-side variable
(random content, manual nav, whole-floor cache, one-shot timing)
removed.

Reporting-only: it never asserts a millisecond threshold (absolute
ms is hardware-bound and there is no CI to gate against). It asserts
only liveness (it rendered and scraped N profile lines) and prints
min / median / p95 per layer + total for the operator to compare
against debug/wasm-render-caching-profile.md.

Opt-in: under the ``perf`` marker (auto-skipped unless ``-m perf``),
and skips gracefully if Playwright/Chromium are absent. Bootstrap
with ``make perf-bootstrap``. Run with:

    pytest -m perf tests/perf/test_wasm_render_bench.py -s

Tunables via env: NHC_PERF_FIXTURE (default seed19_city_surface),
NHC_PERF_WARMUP (3), NHC_PERF_TIMED (20).
"""

from __future__ import annotations

import os
import statistics

import pytest

from tests.perf.conftest import (
    require_fresh_wasm_bundle,
    require_playwright,
)

pytestmark = pytest.mark.perf

FIXTURE = os.environ.get("NHC_PERF_FIXTURE", "seed19_city_surface")
WARMUP = int(os.environ.get("NHC_PERF_WARMUP", "3"))
TIMED = int(os.environ.get("NHC_PERF_TIMED", "20"))
# NHC_PERF_GPU=1 → headed Chrome with GPU enabled (real Metal/ANGLE
# on a Mac desktop), for production-like absolute numbers. Default
# (unset) stays headless software (reproducible relative baseline).
# GPU mode needs a display (no SSH/CI), pops a window, and is
# noisier — see design/canvas_render_caching.md.
GPU = os.environ.get("NHC_PERF_GPU") == "1"


def _launch(p):
    """Launch the browser per the GPU toggle.

    GPU: headed system Chrome with the blocklist relaxed + 2D-canvas
    accel forced. Falls back to the bundled headed Chromium if the
    ``chrome`` channel isn't found. Default: headless shell
    (software).
    """
    if not GPU:
        return p.chromium.launch()
    gpu_args = [
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        "--enable-accelerated-2d-canvas",
    ]
    try:
        return p.chromium.launch(
            headless=False, channel="chrome", args=gpu_args,
        )
    except Exception:
        # No system Chrome channel — use the bundled full Chromium
        # (still GPU-capable headed; not the headless shell).
        return p.chromium.launch(headless=False, args=gpu_args)


def _parse_line(line: str) -> dict[str, float]:
    """Parse one ``[nhc-render] … key=value …`` line into numbers.

    Strips the ``ms`` suffix on ``total`` and ignores non-numeric
    tokens (the label, ``canvas=WxH``)."""
    out: dict[str, float] = {}
    for tok in line.split():
        if "=" not in tok:
            continue
        key, _, val = tok.partition("=")
        if val.endswith("ms"):
            val = val[:-2]
        try:
            out[key] = float(val)
        except ValueError:
            continue
    return out


def _summary(values: list[float]) -> tuple[float, float, float]:
    """(min, median, p95) for a list of samples."""
    s = sorted(values)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return s[0], statistics.median(s), p95


def test_wasm_render_bench(static_server):
    require_fresh_wasm_bundle()
    sync_playwright = require_playwright()

    url = f"{static_server}/tests/perf/harness.html?fixture={FIXTURE}"
    lines: list[str] = []
    with sync_playwright() as p:
        try:
            browser = _launch(p)
        except Exception as exc:  # browser binary not installed
            pytest.skip(
                f"chromium launch failed ({exc}) — run `make perf-bootstrap`",
            )
        try:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            # Module scripts run async — wait until the harness has
            # defined its readiness promise before awaiting it.
            page.wait_for_function(
                "() => typeof window.benchReady !== 'undefined'",
                timeout=30000,
            )
            # Await the harness setup promise; bail loudly on error.
            ready = page.evaluate("async () => await window.benchReady")
            if not ready:
                err = page.evaluate("() => window.benchError || 'unknown'")
                pytest.fail(f"harness setup failed: {err}")
            gpu_renderer = page.evaluate("() => window.gpuRenderer")
            lines = page.evaluate(
                "async (a) => window.runBench(a.warmup, a.timed)",
                {"warmup": WARMUP, "timed": TIMED},
            )
        finally:
            browser.close()

    # Liveness — we got one profile line per timed render.
    assert len(lines) == TIMED, (
        f"expected {TIMED} [nhc-render] lines, got {len(lines)}:\n"
        + "\n".join(lines)
    )

    parsed = [_parse_line(s) for s in lines]
    keys = [
        "total", "shadow", "hatch", "paint", "stroke", "stamp",
        "roof", "path", "fixture",
    ]
    mode = "GPU/headed" if GPU else "software/headless"
    print(f"\n[tier2] fixture={FIXTURE} warmup={WARMUP} timed={TIMED} mode={mode}")
    print(f"[tier2]   gpu_renderer={gpu_renderer}")
    for key in keys:
        vals = [p[key] for p in parsed if key in p]
        if not vals:
            continue
        lo, med, p95 = _summary(vals)
        print(
            f"[tier2]   {key:>8}: min={lo:7.2f} median={med:7.2f} "
            f"p95={p95:7.2f}",
        )
    # Cache counts are deterministic — report the first line's.
    counts = {
        k: int(v)
        for k, v in parsed[0].items()
        if k.startswith("sprite_") or k.startswith("grove_polygon_")
    }
    print(f"[tier2]   counts: {counts}")

    # Stability signal (not a gate): median spread of total.
    totals = [p["total"] for p in parsed if "total" in p]
    if len(totals) >= 2:
        med = statistics.median(totals)
        spread = (max(totals) - min(totals)) / med if med else 0.0
        print(f"[tier2]   total spread (max-min)/median = {spread:.1%}")
