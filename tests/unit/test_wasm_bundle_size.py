"""WASM bundle size budget gate (Phase 5.5).

Pins the gzipped size of ``crates/nhc-render-wasm/pkg/nhc_render_wasm_bg.wasm``
under the 400 KB target from
``plans/nhc_pure_ir_v5_migration_plan.md``. A regression here means a
recent Rust-side change inflated the wasm bundle past the
on-the-wire budget the JS dispatcher (Phase 5.4) downloads.

The bundle is built by ``make wasm-build`` into a ``.gitignored``
``pkg/`` directory, so this test skips when the bundle is absent
rather than failing — CI / the dev loop should run ``make
wasm-build`` before exercising this gate. The unoptimised bundle
already sits at ~188 KB gzipped on a fresh tree, so the gate has
generous headroom; tighten the budget here when the natural size
shrinks (Phase 5.6 + further wasm-snip work).
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLE_PATH = (
    _REPO_ROOT / "crates" / "nhc-render-wasm" / "pkg"
    / "nhc_render_wasm_bg.wasm"
)

# 400 KB gzipped — the success-criterion target spelled out in
# the v5 migration plan and the parent Phase 11 plan it inherits
# from. The current bundle sits well under (~186 KB at HEAD), so
# the budget catches a >2x regression rather than fine-grained
# growth. Tighten as the natural size shrinks.
BUDGET_BYTES = 400 * 1024


@pytest.mark.skipif(
    not _BUNDLE_PATH.exists(),
    reason=(
        "WASM bundle not built — run `make wasm-build` to "
        "regenerate then re-run this test"
    ),
)
def test_wasm_bundle_under_gzipped_budget() -> None:
    raw = _BUNDLE_PATH.read_bytes()
    # Match the on-the-wire compression: HTTP servers (and the
    # Flask dev server) hand out the bundle with
    # ``Content-Encoding: gzip`` at compression level 9 by default
    # so the test mirrors what the player actually downloads.
    compressed = gzip.compress(raw, compresslevel=9)
    raw_kb = len(raw) / 1024
    gz_kb = len(compressed) / 1024
    budget_kb = BUDGET_BYTES / 1024
    assert len(compressed) <= BUDGET_BYTES, (
        f"WASM bundle is {gz_kb:.1f} KB gzipped (raw {raw_kb:.1f} KB), "
        f"budget {budget_kb:.0f} KB. Tighten with wasm-opt flag "
        f"changes in crates/nhc-render-wasm/Cargo.toml; see Phase "
        f"5.5 of plans/nhc_pure_ir_v5_migration_plan.md."
    )
