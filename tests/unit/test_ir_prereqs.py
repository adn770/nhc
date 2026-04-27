"""Sentinel: IR migration Python-side prereqs are installed.

Catches regressions where someone removes ``flatbuffers`` or
``maturin`` from the dependency manifests. These packages are
small but load-bearing for the IR migration:

- ``flatbuffers`` is the runtime the FB-generated Python bindings
  (under ``nhc/rendering/ir/``) import at module load time. Once
  Phase 0 of the IR migration plan lands, removing this package
  breaks every test that imports IR types.

- ``maturin`` is the PyO3 wheel builder used by IR plan Phase 0.3+
  to produce the ``nhc_render`` Rust extension wheel. Without it,
  ``pip install -e .`` cannot build the Rust crate.

System-side toolchain prereqs (rustc, cargo, flatc, wasm-pack,
wasm-opt) are NOT covered here — they are install-time concerns
documented in plans/nhc_ir_prereqs_plan.md Appendix A and fail
loudly the moment the IR migration plan tries to use them.
"""

from __future__ import annotations


def test_flatbuffers_runtime_importable() -> None:
    import flatbuffers

    assert hasattr(flatbuffers, "Builder"), (
        "flatbuffers package missing Builder API — check the "
        "installed version"
    )


def test_maturin_importable() -> None:
    # maturin is principally a CLI, but the package object exists
    # and importing it confirms the venv resolution works.
    import maturin  # noqa: F401
