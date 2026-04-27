"""Sentinel: Python 3.14 is the supported runtime.

Pins the floor set in pyproject.toml's ``requires-python`` and the
Docker base image. Catches regressions where the requirement gets
silently relaxed (e.g. a contributor reverting `>=3.14` to `>=3.10`
to make their local 3.12 venv work) — the IR migration's PyO3 abi3
wheel doesn't actually require this floor, but the rest of the
codebase is allowed to lean on 3.14-only features now that the
container runs on 3.14.
"""

from __future__ import annotations

import sys


def test_python_runtime_is_3_14_or_newer() -> None:
    assert sys.version_info >= (3, 14), (
        f"Python 3.14+ required; got {sys.version_info[:3]}. "
        f"See plans/nhc_ir_prereqs_plan.md Phase 1."
    )
