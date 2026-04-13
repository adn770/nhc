"""Tests for the temple room type and depth-2 guarantee."""

from __future__ import annotations

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import TempleShape
from nhc.dungeon.pipeline import generate_level


def _find_temples(level):
    return [r for r in level.rooms if "temple" in r.tags]


def _entities_in_room(level, room):
    inside = set(room.floor_tiles())
    return [e for e in level.entities if (e.x, e.y) in inside]


class TestTempleDepthGuarantee:
    def test_depth_2_always_has_temple(self):
        """Every depth-2 BSP floor must spawn exactly one temple."""
        for seed in range(40):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            temples = _find_temples(level)
            assert len(temples) == 1, (
                f"seed={seed} produced {len(temples)} temples"
            )

    def test_temple_room_uses_temple_shape(self):
        for seed in range(20):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            for room in _find_temples(level):
                assert isinstance(room.shape, TempleShape), (
                    f"seed={seed} temple room is not TempleShape"
                )

    def test_no_temple_at_depth_1(self):
        for seed in range(40):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=1, seed=seed,
            ))
            assert not _find_temples(level), (
                f"seed={seed} produced a temple at depth 1"
            )


class TestTempleContents:
    def test_temple_has_priest(self):
        for seed in range(20):
            level = generate_level(GenerationParams(
                width=120, height=40, depth=2, seed=seed,
            ))
            for room in _find_temples(level):
                priests = [
                    e for e in _entities_in_room(level, room)
                    if (e.entity_type == "creature"
                        and e.entity_id == "priest")
                ]
                assert len(priests) == 1, (
                    f"seed={seed} temple has {len(priests)} priests"
                )
                p = priests[0]
                assert "temple_services" in p.extra
                assert "shop_stock" in p.extra
                assert "heal" in p.extra["temple_services"]
                assert "remove_curse" in p.extra["temple_services"]
                assert "bless" in p.extra["temple_services"]
