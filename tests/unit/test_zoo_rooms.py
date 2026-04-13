"""Tests for the zoo room type.

Zoos are medium-sized rooms filled with creatures.  They must
NOT be doorless (at least one corridor connection) and are
placed at a low probability so they stay a pleasant surprise.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.pipeline import generate_level


ZOO_MIN_WIDTH = 5
ZOO_MIN_HEIGHT = 5


def _find_zoos(level):
    return [r for r in level.rooms if "zoo" in r.tags]


def _connection_count(level, room_id: str) -> int:
    n = 0
    for c in level.corridors:
        if room_id in c.connects:
            n += 1
    return n


def _entities_in_room(level, room):
    inside = set(room.floor_tiles())
    return [
        e for e in level.entities if (e.x, e.y) in inside
    ]


class TestZooDepthGate:
    def test_no_zoos_below_depth_5(self):
        """Zoos must not appear on depths 1–4."""
        for depth in (1, 2, 3, 4):
            for seed in range(50):
                level = generate_level(GenerationParams(
                    width=120, height=40, depth=depth, seed=seed,
                ))
                assert not _find_zoos(level), (
                    f"seed={seed} depth={depth} produced a zoo"
                )


class TestZooAssignment:
    def test_zoos_appear_across_seeds(self):
        """Zoos are rare but not impossible.  Across 100 seeds on
        a large map at depth 3 we should see at least a handful."""
        with_zoo = 0
        for seed in range(100):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=5, seed=seed,
            ))
            if _find_zoos(level):
                with_zoo += 1
        assert with_zoo >= 5, (
            f"Only {with_zoo}/100 seeds produced a zoo — probability "
            f"is too low"
        )
        assert with_zoo <= 80, (
            f"{with_zoo}/100 seeds produced a zoo — probability is "
            f"too high for a 'rare' room"
        )

    def test_zoo_is_not_doorless(self):
        """Every zoo must have at least one corridor connection.

        A room with zero corridors has no door — zoos are meant to
        be entered through a door, not found by digging.
        """
        for seed in range(100):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=5, seed=seed,
            ))
            for zoo in _find_zoos(level):
                conn = _connection_count(level, zoo.id)
                assert conn >= 1, (
                    f"seed={seed} zoo {zoo.id} has {conn} "
                    f"corridor connections (doorless)"
                )

    def test_zoo_has_minimum_size(self):
        for seed in range(50):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=5, seed=seed,
            ))
            for zoo in _find_zoos(level):
                assert zoo.rect.width >= ZOO_MIN_WIDTH, (
                    f"seed={seed} zoo {zoo.id} width "
                    f"{zoo.rect.width} < {ZOO_MIN_WIDTH}"
                )
                assert zoo.rect.height >= ZOO_MIN_HEIGHT, (
                    f"seed={seed} zoo {zoo.id} height "
                    f"{zoo.rect.height} < {ZOO_MIN_HEIGHT}"
                )

    def test_zoo_not_on_vault_entry_or_exit(self):
        for seed in range(50):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=5, seed=seed,
            ))
            for zoo in _find_zoos(level):
                assert "vault" not in zoo.tags
                assert "entry" not in zoo.tags
                assert "exit" not in zoo.tags


class TestZooPopulation:
    def test_zoo_is_filled_with_creatures(self):
        """A zoo should contain several creatures — that is its
        defining feature."""
        found = False
        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=5, seed=seed,
            ))
            zoos = _find_zoos(level)
            if not zoos:
                continue
            found = True
            for zoo in zoos:
                creatures = [
                    e for e in _entities_in_room(level, zoo)
                    if e.entity_type == "creature"
                ]
                assert len(creatures) >= 4, (
                    f"seed={seed} zoo {zoo.id} only has "
                    f"{len(creatures)} creatures"
                )
        if not found:
            pytest.skip("no zoos generated in 200 seeds")

    def test_zoo_creatures_are_pooled_by_depth(self):
        """Zoo creatures should come from the depth-appropriate
        pool — no bosses or out-of-tier picks."""
        from nhc.dungeon.populator import CREATURE_POOLS

        for seed in range(200):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=5, seed=seed,
            ))
            zoos = _find_zoos(level)
            if not zoos:
                continue
            tier = min(max(1, level.depth), max(CREATURE_POOLS.keys()))
            allowed = {cid for cid, _ in CREATURE_POOLS[tier]}
            for zoo in zoos:
                for e in _entities_in_room(level, zoo):
                    if e.entity_type != "creature":
                        continue
                    assert e.entity_id in allowed, (
                        f"seed={seed} zoo {zoo.id} has out-of-pool "
                        f"creature {e.entity_id}"
                    )
