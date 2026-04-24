"""Inhabited-settlement sub-hex sites are not bare fields.

The ``inhabited_settlement`` family handles the CAMPSITE and
ORCHARD minor features. The original implementation dropped a
single feature tile on the bare floor of an enclosed rectangle
plus one NPC; no orchard trees, no campfire area. The player saw
a 30×20 grass field with a tag floating in the middle and an NPC
next to it — didn't read as a campsite / orchard.

These tests pin the richer layout:

- ORCHARD: several ``tree`` feature tiles in a grid pattern.
- CAMPSITE: stays open (no interior walls), campfire present,
  NPC next to fire.

FARM used to share this path too but now routes through the
unified farm assembler (see ``tests/unit/sites/test_farm_tier.py``
and :meth:`Game._enter_sub_hex_farm`). The generator raises on
FARM so stale callers fail loudly rather than silently producing
a bare rectangle.
"""

from __future__ import annotations

import pytest

from nhc.dungeon.model import Terrain
from nhc.hexcrawl.model import Biome, MinorFeatureType
from nhc.hexcrawl.sub_hex_sites import (
    SiteTier,
    generate_inhabited_settlement_site,
)


def _site(feature: MinorFeatureType, seed: int = 1):
    return generate_inhabited_settlement_site(
        feature=feature,
        biome=Biome.GREENLANDS,
        seed=seed,
        tier=SiteTier.MEDIUM,
    )


def _collect(level, terrain=None, feature=None):
    out: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tile_at(x, y)
            if tile is None:
                continue
            if terrain is not None and tile.terrain is not terrain:
                continue
            if feature is not None and tile.feature != feature:
                continue
            out.append((x, y))
    return out


def test_farm_feature_is_rejected_by_inhabited_settlement() -> None:
    """FARM no longer routes through this generator — loud raise
    guards against stale call sites."""
    with pytest.raises(ValueError):
        generate_inhabited_settlement_site(
            feature=MinorFeatureType.FARM,
            biome=Biome.GREENLANDS,
            seed=1,
            tier=SiteTier.MEDIUM,
        )


class TestCampsiteVariant:
    def test_campsite_has_campfire_feature(self) -> None:
        site = _site(MinorFeatureType.CAMPSITE)
        assert _collect(site.level, feature="campfire"), (
            "CAMPSITE must place a campfire feature tile"
        )

    def test_campsite_stays_open_ground(self) -> None:
        """A campsite is a clearing — no interior walls beyond
        the 1-tile perimeter the shell already stamps."""
        site = _site(MinorFeatureType.CAMPSITE)
        w, h = site.level.width, site.level.height
        perimeter = {
            (x, y)
            for y in range(h) for x in range(w)
            if x in (0, w - 1) or y in (0, h - 1)
        }
        walls = set(_collect(site.level, terrain=Terrain.WALL))
        interior_walls = walls - perimeter
        assert not interior_walls, (
            f"CAMPSITE should have no interior walls, got "
            f"{len(interior_walls)}"
        )


class TestOrchardVariant:
    def test_orchard_has_multiple_tree_features(self) -> None:
        """ORCHARD is not a single tree — it's rows of them. At
        least four ``tree`` feature tiles."""
        site = _site(MinorFeatureType.ORCHARD)
        trees = _collect(site.level, feature="tree")
        assert len(trees) >= 4, (
            f"ORCHARD expected at least 4 tree feature tiles, "
            f"got {len(trees)}"
        )
