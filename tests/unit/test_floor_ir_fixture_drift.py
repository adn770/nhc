"""Guard: committed parity fixtures match a fresh regeneration.

Runs the same ``--check`` invocation that CI uses, but at pytest
time so a fixture drift caused by a rendering change is caught
in the standard dev loop instead of waiting for CI.

The fixtures themselves live under ``tests/fixtures/floor_ir/``;
the regenerator is at ``tests/samples/regenerate_fixtures.py``.
"""

from __future__ import annotations

from tests.samples.regenerate_fixtures import (
    _FIXTURES,
    _check_fixture,
    _root_dir,
)


def test_committed_fixtures_match_fresh_regeneration() -> None:
    root = _root_dir()
    drifts: list[str] = []
    for fx in _FIXTURES:
        drifts.extend(_check_fixture(fx, root))
    assert not drifts, (
        "Floor-IR fixtures drifted from a fresh regeneration. "
        "Run `python -m tests.samples.regenerate_fixtures` and "
        "commit the changes — but only after confirming the "
        "rendering change was intentional. Drifts:\n"
        + "\n".join(f"  - {d}" for d in drifts)
    )
