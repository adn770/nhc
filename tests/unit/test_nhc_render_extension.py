"""Sentinel: the ``nhc_render`` PyO3 extension is installed and works.

Confirms the Rust crate at ``crates/nhc-render`` was built and
installed (``make rust-build`` or ``pip install -e
crates/nhc-render``), and that its splitmix64 stub matches the
canonical Vigna reference vectors. This guards the Rust ↔ Python
determinism contract — every later procedural primitive that
ships in the crate inherits the same vectors as its parity floor.

If this test goes red:

- ``ModuleNotFoundError: No module named 'nhc_render'`` — run
  ``make rust-build`` to rebuild the wheel and reinstall.
- Vector mismatch — investigate ``crates/nhc-render/src/rng.rs``
  before declaring the determinism contract broken; the reference
  vectors are checked against Vigna's splitmix64.c and the Python
  reference both, so a divergence here is load-bearing.
"""

from __future__ import annotations

import importlib

import pytest


nhc_render = pytest.importorskip(
    "nhc_render",
    reason=(
        "nhc_render extension not installed — run `make rust-build` "
        "or `pip install -e crates/nhc-render` first"
    ),
)


def test_extension_is_loadable() -> None:
    # Re-import to confirm the module survives a reload (catches
    # state mutation in the FFI surface).
    importlib.reload(nhc_render)
    assert hasattr(nhc_render, "splitmix64_next")


def test_splitmix64_seed_zero_first_value() -> None:
    # First step of the canonical splitmix64 stream from seed 0.
    # Cross-checked with Vigna's splitmix64.c reference impl and
    # the Rust unit tests in crates/nhc-render/src/rng.rs.
    assert nhc_render.splitmix64_next(0) == 0xE220A8397B1DCDAF


def test_splitmix64_seed_one() -> None:
    assert nhc_render.splitmix64_next(1) == 0x910A2DEC89025CC1


def test_splitmix64_seed_deadbeef() -> None:
    assert nhc_render.splitmix64_next(0xDEADBEEFCAFEBABE) == 0x0D7D93560D1929D2
