"""Render a fixture's parity comparison from three rasteriser paths.

Three outputs per descriptor under debug/parity/<descriptor>/:

    reference.png        — the committed reference (truth).
    rust_actual.png      — fresh IR → nhc_render.ir_to_png  (tiny-skia)
    python_actual.png    — fresh IR → ir_to_svg → nhc_render.svg_to_png (resvg)

    diff_rust_vs_ref.png      — magenta where rust ≠ reference, else grey
    diff_python_vs_ref.png    — magenta where python-svg ≠ reference, else grey
    diff_rust_vs_python.png   — magenta where rust ≠ python-svg

    psnr.txt — three PSNR readings.

The python_actual is the cross-rasteriser path that *passes* the
parity gate (Python `_cave_path_from_outline` uses Shapely / GEOS).
Comparing it against rust_actual isolates the Rust geometry-pipeline
divergence from any tiny-skia / resvg AA differences.

Outputs under `debug/parity/<descriptor>/` (gitignored). Re-run after
each emitter / consumer change to inspect drift visually.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/parity_visualize.py <descriptor> ...

Useful descriptors include `seed42_rect_dungeon_dungeon`,
`seed7_octagon_crypt_dungeon`, `seed99_cave_cave_cave`,
`seed7_brick_building_floor0`. Run with no arguments to print this
help.
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import nhc_render
from nhc.rendering.ir_emitter import build_floor_ir
from tests.fixtures.floor_ir._inputs import descriptor_inputs


def ir_to_svg(buf: bytes) -> str:
    """Phase 2.19 shim: route through Rust ``nhc_render.ir_to_svg``."""
    return nhc_render.ir_to_svg(bytes(buf))


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "floor_ir"
OUT_ROOT = REPO / "debug" / "parity"


def _build_buf_for(descriptor: str) -> bytes:
    """Resolve descriptor → fresh IR buffer, handling the three loaders
    (standard, building, synthetic-roof)."""
    from tests.samples.regenerate_fixtures import (
        _BUILDING_FIXTURES, _build_building_inputs,
        _SYNTHETIC_ROOF_FIXTURES, _build_synthetic_buf,
    )
    for fx in _BUILDING_FIXTURES:
        if fx.descriptor == descriptor:
            site, level = _build_building_inputs(fx)
            return bytes(build_floor_ir(
                level, seed=fx.seed, hatch_distance=2.0, site=site,
            ))
    for fx in _SYNTHETIC_ROOF_FIXTURES:
        if fx.descriptor == descriptor:
            return bytes(_build_synthetic_buf(fx))
    inputs = descriptor_inputs(descriptor)
    return bytes(build_floor_ir(
        inputs.level,
        seed=inputs.seed,
        hatch_distance=inputs.hatch_distance,
        vegetation=inputs.vegetation,
    ))


def _decode(png: bytes) -> np.ndarray:
    return np.asarray(
        Image.open(io.BytesIO(png)).convert("RGBA"), dtype=np.uint8
    )


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return float("nan")
    diff = a.astype(np.float64) - b.astype(np.float64)
    mse = float(np.mean(diff * diff))
    if mse == 0.0:
        return math.inf
    return 20.0 * math.log10(255.0 / math.sqrt(mse))


def _pct_differ(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return float("nan")
    delta = a.astype(np.int32) - b.astype(np.int32)
    differs = np.any(delta != 0, axis=-1)
    return 100.0 * float(differs.sum()) / differs.size


def _diff_mask(actual: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Greyscale of reference + magenta where pixels differ."""
    if actual.shape != reference.shape:
        return reference  # bail
    delta = (actual.astype(np.int32) - reference.astype(np.int32))
    differs = np.any(delta != 0, axis=-1)
    grey = reference[..., :3].mean(axis=-1).astype(np.uint8)
    out = np.stack([grey, grey, grey, np.full_like(grey, 255)], axis=-1)
    out[differs, 0] = 255
    out[differs, 1] = 0
    out[differs, 2] = 255
    out[differs, 3] = 255
    return out


def visualize(descriptor: str) -> None:
    fixture_dir = FIXTURES / descriptor
    if not fixture_dir.is_dir():
        print(f"[skip] {descriptor}: fixture dir missing")
        return

    out_dir = OUT_ROOT / descriptor
    out_dir.mkdir(parents=True, exist_ok=True)

    buf = _build_buf_for(descriptor)
    reference_bytes = (fixture_dir / "reference.png").read_bytes()
    rust_bytes = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    svg = ir_to_svg(buf)
    python_bytes = bytes(nhc_render.svg_to_png(svg))

    (out_dir / "reference.png").write_bytes(reference_bytes)
    (out_dir / "rust_actual.png").write_bytes(rust_bytes)
    (out_dir / "python_actual.png").write_bytes(python_bytes)

    ref = _decode(reference_bytes)
    rust = _decode(rust_bytes)
    pyth = _decode(python_bytes)

    rust_vs_ref_db = _psnr(rust, ref)
    pyth_vs_ref_db = _psnr(pyth, ref)
    rust_vs_pyth_db = _psnr(rust, pyth)
    rust_vs_ref_pct = _pct_differ(rust, ref)
    pyth_vs_ref_pct = _pct_differ(pyth, ref)
    rust_vs_pyth_pct = _pct_differ(rust, pyth)

    summary = (
        f"{descriptor}:\n"
        f"  rust  vs reference : {rust_vs_ref_db:6.2f} dB  "
        f"({rust_vs_ref_pct:5.2f}% pixels differ)\n"
        f"  py-svg vs reference: {pyth_vs_ref_db:6.2f} dB  "
        f"({pyth_vs_ref_pct:5.2f}% pixels differ)  ← parity-gate path\n"
        f"  rust  vs py-svg    : {rust_vs_pyth_db:6.2f} dB  "
        f"({rust_vs_pyth_pct:5.2f}% pixels differ)  ← isolates Rust drift\n"
    )
    print(summary)
    (out_dir / "psnr.txt").write_text(summary)

    Image.fromarray(_diff_mask(rust, ref)).save(out_dir / "diff_rust_vs_ref.png")
    Image.fromarray(_diff_mask(pyth, ref)).save(out_dir / "diff_python_vs_ref.png")
    Image.fromarray(_diff_mask(rust, pyth)).save(out_dir / "diff_rust_vs_python.png")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for descriptor in argv:
        visualize(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
