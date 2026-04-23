#!/usr/bin/env python3
"""Detect function-local imports that shadow module-level names.

Walks ``nhc/`` and classifies every function-local ``import`` /
``from ... import`` statement as one of:

- ``SHADOW_CONDITIONAL`` -- name is also bound at module level *and*
  the local import sits in a conditional branch (``if``, ``try`` /
  ``except``). This is the bug class that caused the teleporter-pad
  ``UnboundLocalError`` (commit edc429b): Python's compile-time scope
  analysis promotes the name to function-local everywhere in the
  body, so earlier unconditional reads explode with
  ``UnboundLocalError`` the moment the branch is *not* taken.

- ``SHADOW_UNCONDITIONAL`` -- name is also bound at module level, but
  the local import is at function top. Harmless today; one
  copy-paste away from the conditional variant above.

- ``LOCAL_ONLY`` -- name is *not* bound at module level. Advisory
  only; printed with ``--all``.

Exits non-zero if any ``SHADOW_*`` finding exists.

Stdlib only on purpose -- the pre-commit hook must work without a
venv.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Iterator


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCAN = REPO_ROOT / "nhc"
EXCLUDED_PARTS = {
    "__pycache__",
    ".venv",
    "tests",
    "scripts",
    "tools",
    "debug",
}


def _iter_py_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_PARTS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _module_names(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
    return out


def _walk_funcs(
    body: Iterable[ast.stmt],
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
            yield from _walk_funcs(node.body)
        elif isinstance(node, ast.ClassDef):
            yield from _walk_funcs(node.body)
        elif hasattr(node, "body"):
            yield from _walk_funcs(getattr(node, "body", []) or [])


def _local_imports(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[tuple[int, str, bool]]:
    """Yield ``(lineno, bound_name, is_conditional)`` for every import
    inside ``func`` (not recursing into nested defs/classes -- those
    are visited separately by :func:`_walk_funcs`)."""

    def visit(body: Iterable[ast.stmt], conditional: bool):
        for n in body:
            if isinstance(n, ast.Import):
                for a in n.names:
                    yield (
                        n.lineno,
                        (a.asname or a.name).split(".")[0],
                        conditional,
                    )
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    yield n.lineno, a.asname or a.name, conditional
            elif isinstance(n, ast.If):
                yield from visit(n.body, True)
                yield from visit(n.orelse, True)
            elif isinstance(n, ast.Try):
                yield from visit(n.body, True)
                for h in n.handlers:
                    yield from visit(h.body, True)
                yield from visit(n.orelse, True)
                yield from visit(n.finalbody, True)
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.While)):
                yield from visit(n.body, conditional)
                yield from visit(n.orelse, conditional)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                yield from visit(n.body, conditional)

    yield from visit(func.body, False)


def _classify_file(path: Path) -> list[dict]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    mod_names = _module_names(tree)
    findings: list[dict] = []
    for func in _walk_funcs(tree.body):
        for lineno, name, conditional in _local_imports(func):
            if name in mod_names:
                category = (
                    "SHADOW_CONDITIONAL" if conditional else "SHADOW_UNCONDITIONAL"
                )
            else:
                category = "LOCAL_ONLY"
            findings.append(
                {
                    "path": str(path),
                    "line": lineno,
                    "name": name,
                    "func": func.name,
                    "category": category,
                }
            )
    return findings


def scan(paths: Iterable[Path]) -> list[dict]:
    """Public API -- classify function-local imports in ``paths``."""
    out: list[dict] = []
    for p in paths:
        out.extend(_classify_file(p))
    return out


def _resolve_cli_paths(raw: list[str]) -> list[Path]:
    out: list[Path] = []
    for r in raw:
        pp = Path(r).resolve()
        if any(part in EXCLUDED_PARTS for part in pp.parts):
            continue
        if pp.suffix == ".py" and pp.is_file():
            out.append(pp)
    return out


def _format_line(finding: dict) -> str:
    p = Path(finding["path"])
    try:
        rel = p.relative_to(REPO_ROOT)
    except ValueError:
        rel = p
    return (
        f"{rel}:{finding['line']}: {finding['category']} "
        f"'{finding['name']}' in {finding['func']}()"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Flag function-local imports that shadow module-level names."
        ),
    )
    ap.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Limit scan to these .py files (default: walk nhc/).",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Also report LOCAL_ONLY (advisory) findings.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout.",
    )
    args = ap.parse_args(argv)

    if args.paths:
        paths = _resolve_cli_paths(args.paths)
    else:
        paths = sorted(_iter_py_files(DEFAULT_SCAN))

    findings = scan(paths)
    shadows = [f for f in findings if f["category"].startswith("SHADOW")]
    visible = findings if args.all else shadows

    if args.json:
        json.dump(visible, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for f in visible:
            print(_format_line(f))
        if shadows:
            print(f"\n{len(shadows)} shadow(s) found.", file=sys.stderr)

    return 1 if shadows else 0


if __name__ == "__main__":
    sys.exit(main())
