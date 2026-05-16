"""Fixture-input registry for the floor-IR parity gate.

Maps a fixture descriptor (the directory name under
``tests/fixtures/floor_ir/``) to the inputs that ``build_floor_ir``
expects: ``(level, seed, hatch_distance, theme)``. The
single source of truth for the fixture set is
``tests/samples/regenerate_fixtures.py:_FIXTURES``; this module
imports from there so the parity gate and the regenerator can never
disagree about which level a descriptor names.

Phase 1.a uses this registry from the XFAIL parity tests in
``tests/unit/test_floor_ir.py`` and ``tests/unit/test_ir_to_svg.py``
so they call the real ``build_floor_ir(level, seed, ...)`` API
instead of the placeholder ``descriptor=`` keyword that the Phase
0.5 stubs used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.samples.regenerate_fixtures import _FIXTURES, _build_level

if TYPE_CHECKING:
    from nhc.dungeon.model import Level


@dataclass(frozen=True, slots=True)
class FixtureInputs:
    descriptor: str
    level: "Level"
    seed: int
    hatch_distance: float
    theme: str
    floor_kind: str


def descriptor_inputs(descriptor: str) -> FixtureInputs:
    """Resolve a descriptor to a ``build_floor_ir`` input tuple.

    Builds the level on every call — cheap enough for the starter
    set (3 fixtures) and avoids the hashability constraints of an
    LRU cache over Level objects. Revisit if the fixture set grows
    past ~15 entries and the per-test build cost shows up in the
    fast-suite timing budget.
    """
    for fx in _FIXTURES:
        if fx.descriptor == descriptor:
            return FixtureInputs(
                descriptor=descriptor,
                level=_build_level(fx),
                seed=fx.seed,
                hatch_distance=2.0,
                theme=fx.theme,
                floor_kind=fx.floor_kind,
            )
    raise KeyError(f"unknown fixture descriptor: {descriptor!r}")


def all_descriptors() -> tuple[str, ...]:
    return tuple(fx.descriptor for fx in _FIXTURES)
