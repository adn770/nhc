"""Cross-rasteriser parity gate for the WASM canvas backend.

Phase 5.6 of ``plans/nhc_pure_ir_v5_migration_plan.md``. Spawns
the Node runner under ``tests/wasm/canvas_parity_runner.mjs`` to
render a fixture through the wasm-pack bundle (see Phase 5.1)
onto a Cairo-backed Canvas2D surface (``@napi-rs/canvas``), then
PSNR-compares the resulting PNG against the canonical tiny-skia
output frozen at ``tests/fixtures/floor_ir/<descriptor>/reference.png``.

The threshold is **30 dB** rather than the 35 dB the SVG /
tiny-skia gates use. The looser bound is the same one the parent
migration plan applies to every cross-rasteriser pair where
anti-aliasing semantics diverge: Cairo (Canvas2D) and tiny-skia
emit subtly different sub-pixel coverage for diagonal edges and
inside-curve fills, so a per-pixel diff sits a few decibels
below a same-rasteriser gate. 30 dB still rejects every fixture
where a structural / dispatch bug surfaces as visible drift.

Skipped automatically when:

- ``node`` isn't on PATH.
- ``node_modules/@napi-rs/canvas`` is missing (run
  ``npm install`` from the repo root).
- The wasm bundle isn't built (run ``make wasm-build``).

CI / a fresh-checkout workflow needs ``npm install`` +
``make wasm-build`` before this gate runs; otherwise it skips
silently and the next layer of regression detection — the
PNG-side parity gate at ``test_ir_png_parity.py`` — keeps
covering the dispatch correctness from the Rust side.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.unit.test_ir_png_parity import _decode, _psnr


_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _REPO_ROOT / "tests" / "wasm" / "canvas_parity_runner.mjs"
_NODE_MODULES = _REPO_ROOT / "node_modules" / "@napi-rs" / "canvas"
_WASM_BUNDLE = (
    _REPO_ROOT / "crates" / "nhc-render-wasm" / "pkg"
    / "nhc_render_wasm_bg.wasm"
)
_FIXTURE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "floor_ir"

# Cross-rasteriser PSNR floor — see module docstring.
WASM_PSNR_THRESHOLD_DB: float = 30.0

# Fixtures the gate runs against. Mirrors the v5 PSNR test
# harness's per-fixture coverage. Synthetic fixtures stay out of
# scope for the wasm gate at Phase 5.6 — the gameplay-shape
# fixtures already exercise every op-handler path through the
# painter, and the synthetic suite would add ~12 fresh wasm-pack
# spawns to the CI loop without surfacing a different defect
# class. Extend the list when a synthetic fixture's drift is
# different enough to warrant a dedicated gate.
_FIXTURES: tuple[str, ...] = (
    "seed7_town_surface",
    "seed42_rect_dungeon_dungeon",
    "seed7_octagon_crypt_dungeon",
    "seed99_cave_cave_cave",
    "seed7_brick_building_floor0",
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _skip_reason() -> str | None:
    if not _node_available():
        return "node not on PATH"
    if not _NODE_MODULES.is_dir():
        return "node_modules/@napi-rs/canvas missing — run `npm install`"
    if not _WASM_BUNDLE.exists():
        return "wasm bundle missing — run `make wasm-build`"
    if not _RUNNER.exists():
        return f"runner script missing at {_RUNNER}"
    return None


@pytest.fixture(scope="module", params=_FIXTURES)
def wasm_render(request, tmp_path_factory):
    """Render a fixture through the wasm bundle on a Cairo-backed
    Canvas2D ctx; return the resulting PNG bytes + the canonical
    reference for the gate to compare.

    Cached at module scope so each fixture only spawns the Node
    runner once across the gate's three downstream tests
    (PSNR-against-tiny-skia, exit-code, dimensions).
    """
    skip = _skip_reason()
    if skip is not None:
        pytest.skip(skip)
    fixture_dir = _FIXTURE_ROOT / request.param
    out_dir = tmp_path_factory.mktemp(f"wasm_{request.param}")
    out_path = out_dir / "render.png"
    proc = subprocess.run(
        ["node", str(_RUNNER), str(fixture_dir), str(out_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"runner exited {proc.returncode}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}",
        )
    meta = json.loads(proc.stdout.strip().splitlines()[-1])
    return {
        "descriptor": request.param,
        "rendered_png": out_path.read_bytes(),
        "reference_png": (fixture_dir / "reference.png").read_bytes(),
        "width": meta["width"],
        "height": meta["height"],
    }


def test_wasm_canvas_psnr_above_30db(wasm_render) -> None:
    """The wasm bundle's Cairo-backed render PSNR-matches the
    canonical tiny-skia reference at ≥ 30 dB. Drift below this
    floor indicates either a v5 op-handler dispatch bug on the
    canvas side OR a Cairo/tiny-skia anti-aliasing divergence
    that the painter trait isn't compensating for.
    """
    reference = _decode(wasm_render["reference_png"])
    actual = _decode(wasm_render["rendered_png"])
    db = _psnr(actual, reference)
    assert db >= WASM_PSNR_THRESHOLD_DB, (
        f"{wasm_render['descriptor']}: wasm-canvas PSNR "
        f"{db:.2f} dB (threshold {WASM_PSNR_THRESHOLD_DB:.1f} dB)"
    )


def test_wasm_canvas_dims_match_reference(wasm_render) -> None:
    """The wasm bundle's reported canvas dims must match the
    reference PNG's dimensions, otherwise the PSNR comparison
    runs against a stretched / cropped image and the gate's
    floor stops being meaningful."""
    from PIL import Image
    import io
    ref = Image.open(io.BytesIO(wasm_render["reference_png"]))
    assert (wasm_render["width"], wasm_render["height"]) == ref.size, (
        f"{wasm_render['descriptor']}: wasm dims "
        f"{wasm_render['width']}x{wasm_render['height']} vs "
        f"reference {ref.size}"
    )
