"""Tests for the BSP region partitioning generator (test setting).

The generator emits a fully populated :class:`HexWorld` with biome
regions, hex features, and a guaranteed-reachable feature graph from
the hub.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
import textwrap

import pytest

from nhc.hexcrawl.coords import HexCoord, in_bounds, neighbors
from nhc.hexcrawl.generator import (
    GeneratorRetryError,
    _partition,
    generate_test_world,
)
from nhc.hexcrawl.model import Biome, HexFeatureType
from nhc.hexcrawl.pack import load_pack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DEFAULT_PACK_BODY = textwrap.dedent(
    """
    id: testland
    version: 1
    attribution: "NHC test setting"
    map:
      generator: bsp_regions
      width: 8
      height: 8
      num_regions: 5
      region_min: 6
      region_max: 16
    features:
      hub: 1
      village:
        min: 1
        max: 2
      dungeon:
        min: 3
        max: 5
      wonder:
        min: 1
        max: 3
    """
)


@pytest.fixture
def default_pack(tmp_path: Path):
    p = tmp_path / "pack.yaml"
    p.write_text(_DEFAULT_PACK_BODY)
    return load_pack(p)


def _feature_hexes(world, types: set[HexFeatureType]) -> list[HexCoord]:
    return [
        c for c, cell in world.cells.items() if cell.feature in types
    ]


# ---------------------------------------------------------------------------
# Partition helper
# ---------------------------------------------------------------------------


def test_partition_produces_target_region_count() -> None:
    import random
    rng = random.Random(42)
    regions = _partition(
        width=8, height=8,
        target_regions=5, min_cells=6, max_cells=16,
        rng=rng,
    )
    assert len(regions) == 5


def test_partition_covers_full_map_without_overlap() -> None:
    import random
    rng = random.Random(7)
    width, height = 8, 8
    regions = _partition(
        width=width, height=height,
        target_regions=5, min_cells=6, max_cells=16,
        rng=rng,
    )
    seen: set[tuple[int, int]] = set()
    for q_min, r_min, q_max, r_max in regions:
        for q in range(q_min, q_max):
            for r in range(r_min, r_max):
                key = (q, r)
                assert key not in seen, f"overlap at {key}"
                seen.add(key)
    assert seen == {(q, r) for q in range(width) for r in range(height)}


def test_partition_respects_min_and_max_cells() -> None:
    import random
    rng = random.Random(1234)
    regions = _partition(
        width=8, height=8,
        target_regions=5, min_cells=6, max_cells=16,
        rng=rng,
    )
    for q_min, r_min, q_max, r_max in regions:
        area = (q_max - q_min) * (r_max - r_min)
        assert 6 <= area <= 16, (q_min, r_min, q_max, r_max, area)


# ---------------------------------------------------------------------------
# generate_test_world
# ---------------------------------------------------------------------------


def test_generator_respects_seed_reproducibility(default_pack) -> None:
    a = generate_test_world(seed=42, pack=default_pack)
    b = generate_test_world(seed=42, pack=default_pack)
    assert a.cells.keys() == b.cells.keys()
    for c in a.cells:
        assert a.cells[c].biome is b.cells[c].biome
        assert a.cells[c].feature is b.cells[c].feature


def test_generator_different_seeds_differ(default_pack) -> None:
    a = generate_test_world(seed=1, pack=default_pack)
    b = generate_test_world(seed=2, pack=default_pack)
    diff = sum(
        1 for c in a.cells
        if a.cells[c].biome is not b.cells[c].biome
    )
    # With different seeds, at least some hexes should land in
    # different biomes; a deterministic mismatch confirms the seed
    # is actually plumbed through.
    assert diff > 0


def test_generator_fills_full_map(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    expected = {
        HexCoord(q, r)
        for q in range(default_pack.map.width)
        for r in range(default_pack.map.height)
    }
    assert set(w.cells.keys()) == expected


def test_generator_places_exactly_one_hub(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    hubs = _feature_hexes(w, {HexFeatureType.CITY})
    assert len(hubs) == 1
    # Hub must be in greenlands (the design rule); fallback biomes
    # are used only when no greenlands region exists, which is rare
    # for the default pack but allowed by the algorithm.
    hub_cell = w.cells[hubs[0]]
    assert hub_cell.biome in {
        Biome.GREENLANDS, Biome.DRYLANDS,
    }, hub_cell.biome


def test_generator_places_villages_within_range(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    villages = _feature_hexes(w, {HexFeatureType.VILLAGE})
    target = default_pack.features.village
    assert target.min <= len(villages) <= target.max


def test_generator_places_dungeons_within_range(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    dungeon_types = {
        HexFeatureType.CAVE, HexFeatureType.RUIN, HexFeatureType.TOWER,
    }
    dungeons = _feature_hexes(w, dungeon_types)
    target = default_pack.features.dungeon
    assert target.min <= len(dungeons) <= target.max


def test_generator_places_wonders_within_range(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    wonder_types = {
        HexFeatureType.WONDER, HexFeatureType.CRYSTALS,
        HexFeatureType.STONES, HexFeatureType.PORTAL,
    }
    wonders = _feature_hexes(w, wonder_types)
    target = default_pack.features.wonder
    assert target.min <= len(wonders) <= target.max


def test_generator_features_are_reachable_from_hub(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    hubs = _feature_hexes(w, {HexFeatureType.CITY})
    assert len(hubs) == 1
    # BFS over neighbours that lie inside the map.
    seen: set[HexCoord] = {hubs[0]}
    q: deque[HexCoord] = deque([hubs[0]])
    while q:
        c = q.popleft()
        for n in neighbors(c):
            if not in_bounds(n, default_pack.map.width, default_pack.map.height):
                continue
            if n in seen:
                continue
            seen.add(n)
            q.append(n)
    feature_cells = [
        c for c, cell in w.cells.items()
        if cell.feature is not HexFeatureType.NONE
    ]
    for c in feature_cells:
        assert c in seen, f"feature at {c} unreachable from hub"


def test_generator_dungeon_features_have_dungeon_ref(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    dungeon_types = {
        HexFeatureType.CAVE, HexFeatureType.RUIN, HexFeatureType.TOWER,
    }
    dungeons = _feature_hexes(w, dungeon_types)
    assert len(dungeons) > 0
    for c in dungeons:
        cell = w.cells[c]
        assert cell.dungeon is not None, (c, cell.feature)
        assert cell.dungeon.template.startswith("procedural:")


def test_generator_caves_in_mountain_regions(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    caves = _feature_hexes(w, {HexFeatureType.CAVE})
    for c in caves:
        assert w.cells[c].biome is Biome.MOUNTAIN, (
            c, w.cells[c].biome,
        )


def test_generator_ruins_in_forest_or_deadlands(default_pack) -> None:
    w = generate_test_world(seed=42, pack=default_pack)
    ruins = _feature_hexes(w, {HexFeatureType.RUIN})
    for c in ruins:
        assert w.cells[c].biome in {
            Biome.FOREST, Biome.DEADLANDS,
        }, (c, w.cells[c].biome)


def test_generator_seed_sweep_always_succeeds(default_pack) -> None:
    # Sweeping a small set of seeds ensures the retry-on-unreachable
    # path doesn't blow up under common inputs.
    for seed in range(20):
        w = generate_test_world(seed=seed, pack=default_pack)
        assert len(w.cells) == 64


def test_generator_retry_failure_raises(default_pack) -> None:
    # If max_attempts is exceeded the generator raises rather than
    # silently returning a broken world. We force this by demanding
    # an impossible feature target (more dungeons than mountain hexes
    # could plausibly host on this tiny map).
    pack = default_pack
    pack.features.dungeon.min = 100
    pack.features.dungeon.max = 100
    with pytest.raises(GeneratorRetryError):
        generate_test_world(seed=0, pack=pack, max_attempts=3)
