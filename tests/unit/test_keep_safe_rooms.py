"""Tests for keep-as-safe-base behavior.

On procedural:keep levels, the courtyard and barracks rooms are
tagged "safe" so the populator does not spawn hostile creatures
there. The keep serves as the player's protected base.
"""

from __future__ import annotations

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.pipeline import generate_level


def _generate_keep(seed: int = 42):
    params = GenerationParams(
        width=60, height=40, depth=1,
        template="procedural:keep", seed=seed,
    )
    return generate_level(params)


class TestKeepSafeTagging:
    def test_courtyard_tagged_safe(self):
        level = _generate_keep()
        courtyard_rooms = [
            r for r in level.rooms if "courtyard" in r.tags
        ]
        assert len(courtyard_rooms) >= 1
        for room in courtyard_rooms:
            assert "safe" in room.tags

    def test_barracks_tagged_safe(self):
        level = _generate_keep()
        barracks = [r for r in level.rooms if "barracks" in r.tags]
        # At least one barracks room should exist on a keep
        for room in barracks:
            assert "safe" in room.tags

    def test_non_keep_levels_have_no_safe_tag(self):
        """Other templates should not gain a "safe" tag."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
        )
        level = generate_level(params)
        for room in level.rooms:
            assert "safe" not in room.tags


class TestKeepHostileSuppression:
    def test_safe_rooms_have_no_creatures(self):
        """No creature entities spawn inside safe-tagged rooms."""
        # Try several seeds to catch any leakage
        for seed in (1, 2, 3, 7, 42):
            level = _generate_keep(seed)
            safe_rooms = [
                r for r in level.rooms if "safe" in r.tags
            ]
            assert safe_rooms, (
                f"seed={seed}: expected at least one safe room"
            )
            for room in safe_rooms:
                for e in level.entities:
                    if e.entity_type != "creature":
                        continue
                    inside = (
                        room.rect.x <= e.x < room.rect.x + room.rect.width
                        and room.rect.y <= e.y
                        < room.rect.y + room.rect.height
                    )
                    assert not inside, (
                        f"seed={seed}: creature "
                        f"{e.entity_id!r} spawned in safe "
                        f"{room.tags}"
                    )
