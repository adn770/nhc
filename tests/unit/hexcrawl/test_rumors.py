"""Rumor system (M-2.7): true + false intel at settlements.

``generate_rumors`` seeds a small pool of :class:`Rumor` records
keyed off the hex world state. Each rumor either points at a
real hex feature (``truth=True``) or misdirects the player to a
non-feature tile (``truth=False``). ``gather_rumor_at`` pops the
next rumor off the active list, reveals its coord, and hands the
:class:`Rumor` back so the settlement UI can narrate it.
"""

from __future__ import annotations

import random
from pathlib import Path

from nhc.hexcrawl._generator import generate_continental_world
from nhc.hexcrawl.model import HexFeatureType, Rumor
from nhc.hexcrawl.pack import load_pack
from nhc.hexcrawl.rumor_pool import (
    gather_rumor_at,
    generate_rumors,
)


_PACK = Path(__file__).resolve().parents[3] / "content" / "testland" / "pack.yaml"


def _world(seed: int = 7):
    return generate_continental_world(seed=seed, pack=load_pack(_PACK))


# ---------------------------------------------------------------------------
# generate_rumors: shape + mix
# ---------------------------------------------------------------------------


def test_generate_rumors_returns_requested_count() -> None:
    world = _world()
    rumors = generate_rumors(world, seed=1, count=4)
    assert len(rumors) == 4
    assert all(isinstance(r, Rumor) for r in rumors)


def test_generate_rumors_mixes_truth_and_lies() -> None:
    """A count >= 4 should surface both a true and a false rumor."""
    world = _world()
    rumors = generate_rumors(world, seed=1, count=6)
    truths = [r for r in rumors if r.truth]
    lies = [r for r in rumors if not r.truth]
    assert truths, "expected at least one true rumor"
    assert lies, "expected at least one false rumor"


def test_generate_rumors_true_rumors_point_to_feature_hexes() -> None:
    world = _world()
    rumors = generate_rumors(world, seed=1, count=6)
    for r in rumors:
        assert r.reveals is not None
        cell = world.get_cell(r.reveals)
        assert cell is not None, (
            f"rumor {r.id} points to {r.reveals!r}, not in world"
        )
        if r.truth:
            assert cell.feature is not HexFeatureType.NONE, (
                f"true rumor {r.id} points to non-feature hex "
                f"{r.reveals!r}"
            )


def test_generate_rumors_false_rumors_point_to_non_feature_hexes() -> None:
    world = _world()
    rumors = generate_rumors(world, seed=1, count=8)
    lies = [r for r in rumors if not r.truth]
    assert lies
    for r in lies:
        cell = world.get_cell(r.reveals)
        assert cell.feature is HexFeatureType.NONE, (
            f"false rumor {r.id} should point to a non-feature "
            f"hex, got {cell.feature}"
        )


def test_generate_rumors_seed_reproducibility() -> None:
    world_a = _world(seed=7)
    world_b = _world(seed=7)
    a = generate_rumors(world_a, seed=42, count=5)
    b = generate_rumors(world_b, seed=42, count=5)
    to_tuple = lambda r: (r.id, r.text, r.truth, r.reveals)
    assert [to_tuple(r) for r in a] == [to_tuple(r) for r in b]


# ---------------------------------------------------------------------------
# gather_rumor_at: consumes from active_rumors + reveals coord
# ---------------------------------------------------------------------------


def test_gather_rumor_reveals_target_hex() -> None:
    world = _world()
    world.active_rumors = generate_rumors(world, seed=1, count=3)
    first = world.active_rumors[0]
    assert first.reveals not in world.revealed, (
        "precondition: rumor target should be unrevealed so the "
        "reveal side-effect is observable"
    )
    rumor = gather_rumor_at(world, rng=random.Random(1))
    assert rumor is first, "should pop the head of active_rumors"
    assert first.reveals in world.revealed, (
        "gather should reveal the rumor's target hex"
    )
    assert len(world.active_rumors) == 2, (
        "gather should consume the rumor from the pool"
    )


def test_gather_rumor_empty_returns_none() -> None:
    world = _world()
    world.active_rumors = []
    assert gather_rumor_at(world, rng=random.Random(1)) is None
