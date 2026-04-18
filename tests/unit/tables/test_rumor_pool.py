"""Tests for nhc.hexcrawl.rumor_pool — seeding and consumption."""

from __future__ import annotations

from pathlib import Path

from nhc.hexcrawl.model import Rumor
from nhc.i18n import init as i18n_init


_PACK = Path(__file__).resolve().parents[3] / "content" / "testland" / "pack.yaml"


def _world(seed: int = 7):
    from nhc.hexcrawl._generator import generate_continental_world
    from nhc.hexcrawl.pack import load_pack

    return generate_continental_world(seed=seed, pack=load_pack(_PACK))


def setup_module():
    i18n_init("en")


def test_caller_uses_registry_directly() -> None:
    """seed_rumor_pool generates table-backed rumors."""
    from nhc.hexcrawl.rumor_pool import seed_rumor_pool

    world = _world()
    seed_rumor_pool(world, seed=1, lang="en", count=3)
    assert len(world.active_rumors) == 3
    for r in world.active_rumors:
        assert r.source is not None
        assert r.source.table_id in (
            "rumor.true_feature", "rumor.false_lead",
        )


def test_consume_rumor_reveals_hex() -> None:
    """consume_rumor pops and reveals."""
    from nhc.hexcrawl.rumor_pool import consume_rumor, seed_rumor_pool

    world = _world()
    seed_rumor_pool(world, seed=1, lang="en", count=3)
    first = world.active_rumors[0]
    target = first.reveals
    assert target not in world.revealed
    rumor = consume_rumor(world)
    assert rumor is first
    assert target in world.revealed
    assert len(world.active_rumors) == 2


def test_consume_rumor_empty_returns_none() -> None:
    from nhc.hexcrawl.rumor_pool import consume_rumor

    world = _world()
    assert consume_rumor(world) is None


def test_top_up_appends_to_existing() -> None:
    from nhc.hexcrawl.rumor_pool import seed_rumor_pool, top_up_rumor_pool

    world = _world()
    seed_rumor_pool(world, seed=1, lang="en", count=2)
    first_ids = {r.id for r in world.active_rumors}
    top_up_rumor_pool(world, seed=99, lang="en", count=2)
    assert len(world.active_rumors) == 4
    current_ids = {r.id for r in world.active_rumors}
    assert first_ids <= current_ids
