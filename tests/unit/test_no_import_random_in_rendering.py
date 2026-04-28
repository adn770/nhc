"""Architectural guard: no new ``import random`` in ``nhc/rendering/``.

Phase 7.7 of plans/nhc_ir_migration_plan.md. Procedural rendering
RNG must live Rust-side; the IR emitter does not need ``random``,
structural geometry never needed it, and per-primitive randomness
flows through the Rust crate.

This guard pins the no-RNG invariant in pure pytest -- the project
doesn't ship a separate ruff config today, so a test that scans
the source directory enforces the rule alongside every other check
in the fast suite.

The allowlist below lists files that legitimately still call
``random`` because their procedural pipeline has not been ported
yet. Each entry should be retired as the corresponding port lands.
Adding a new file to the allowlist requires planning-level
approval (cite the unfinished port in the comment).
"""
from __future__ import annotations

import pathlib
import re

import pytest


_RENDERING_ROOT = pathlib.Path(__file__).resolve().parents[2] / "nhc" / "rendering"


# Files that still legitimately import ``random``. Retire each
# entry when the matching Rust port lands. Cite the port in the
# comment so the allowlist itself documents the cleanup queue.
_ALLOWLIST: frozenset[str] = frozenset({
    # Wood-floor short-circuit + IR emitter wood-floor wiring.
    # Retire when the wood-floor pipeline ports to Rust.
    "_floor_detail.py",
    "_floor_layers.py",
    # Terrain-detail decorator pipeline (water / lava / chasm).
    # Retire when the terrain-detail port lands.
    "_terrain_detail.py",
    # Procedural masonry / roof / wall geometry — these have not
    # been folded into the IR yet (Phase 5+ territory).
    "_building_walls.py",
    "_doors_svg.py",
    "_dungeon_polygon.py",
    "_cave_geometry.py",
    "_enclosures.py",
    "_hatching.py",
    "_roofs.py",
    "_svg_helpers.py",
    # _decorators.py owns walk_and_paint's per-decorator RNG seed.
    # Retire alongside walk_and_paint when the last live caller
    # flips to Rust (see _decorators.py module docstring).
    "_decorators.py",
    # Renderer entry point + render context still seed
    # downstream RNGs for the legacy procedural paths above.
    "svg.py",
    "_render_context.py",
})


_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+random\b|from\s+random\b)",
    re.MULTILINE,
)


def _python_files() -> list[pathlib.Path]:
    """Top-level SVG-rendering modules + IR pipeline.

    Skips ``terminal/`` and ``graphical/`` because their RNG is
    not part of the floor-rendering pipeline this guard covers.
    Skips ``__pycache__`` directories.
    """
    files: list[pathlib.Path] = []
    for path in (_RENDERING_ROOT, _RENDERING_ROOT / "ir"):
        if not path.is_dir():
            continue
        for entry in sorted(path.iterdir()):
            if entry.is_file() and entry.suffix == ".py":
                files.append(entry)
    return files


def test_rendering_root_resolves() -> None:
    assert _RENDERING_ROOT.is_dir(), (
        f"expected rendering directory at {_RENDERING_ROOT}"
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_no_unexpected_import_random(path: pathlib.Path) -> None:
    """Every ``import random`` must be in :data:`_ALLOWLIST`."""
    text = path.read_text(encoding="utf-8")
    if not _IMPORT_RE.search(text):
        return
    assert path.name in _ALLOWLIST, (
        f"{path.relative_to(_RENDERING_ROOT.parent.parent)} imports "
        "random but is not in the allowlist. The IR emitter does "
        "not need RNG; per-primitive randomness lives Rust-side. "
        "If a legitimate need exists, add the file to the "
        "allowlist with a comment citing the unfinished port."
    )


def test_allowlist_entries_exist() -> None:
    """Stale allowlist entries fail this test so retiring an entry
    requires removing it from :data:`_ALLOWLIST` rather than
    drifting silently after the underlying file is deleted."""
    existing = {p.name for p in _python_files()}
    stale = _ALLOWLIST - existing
    assert not stale, f"allowlist references missing files: {stale}"
