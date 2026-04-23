"""Regression: no function-local import may shadow a module-level name.

Python's compile-time scope analysis promotes every name bound
inside a function body to function-local, regardless of whether
the binding statement is reachable at runtime. So a *conditional*
``from X import Y`` inside a function causes every earlier
reference to ``Y`` in that function to raise ``UnboundLocalError``
when the branch is not taken -- even if ``Y`` is imported at
module level.

This test walks ``nhc/`` with ``ast`` (via
``scripts/lint_import_shadowing.py``) and asserts there are zero
``SHADOW_CONDITIONAL`` or ``SHADOW_UNCONDITIONAL`` findings. It
supersedes the narrower, MessageEvent-specific regression test
(commit edc429b) with a static check that covers the whole
package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "lint_import_shadowing.py"


def _load_lint_module():
    spec = importlib.util.spec_from_file_location(
        "lint_import_shadowing", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_function_local_imports_shadow_module_level():
    lint = _load_lint_module()
    paths = sorted(lint._iter_py_files(lint.DEFAULT_SCAN))
    findings = lint.scan(paths)
    shadows = [f for f in findings if f["category"].startswith("SHADOW")]
    if shadows:
        lines = "\n".join(
            f"  {Path(f['path']).relative_to(REPO_ROOT)}:{f['line']} "
            f"{f['category']} '{f['name']}' in {f['func']}()"
            for f in shadows
        )
        raise AssertionError(
            f"{len(shadows)} function-local import(s) shadow a "
            f"module-level name -- hoist to module scope:\n{lines}"
        )
