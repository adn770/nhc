"""Tests for sub-hex entry: folding the macro feature onto the
feature_cell and sub-hex dispatch.

Companion to ``nhc_sub_hex_entry_plan.md``.
"""

from __future__ import annotations

import json

import pytest

from nhc.core.save import _deserialize_hex_world, _serialize_hex_world
from nhc.hexcrawl._flowers import generate_flower
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexCell,
    HexFeatureType,
    HexWorld,
    MinorFeatureType,
)
from nhc.hexcrawl.seed import dungeon_seed


# ---------------------------------------------------------------------------
# M1: folding macro feature + DungeonRef onto feature_cell sub-hex
# ---------------------------------------------------------------------------


def test_feature_cell_sub_hex_gets_parent_dungeon() -> None:
    """The feature_cell sub-hex carries a copy of the macro DungeonRef."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
        dungeon=DungeonRef(
            template="procedural:cave",
            depth=2,
            site_kind=None,
            size_class=None,
            faction="goblin",
        ),
        elevation=0.5,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    assert flower.feature_cell is not None
    fc = flower.cells[flower.feature_cell]
    assert fc.major_feature is HexFeatureType.CAVE
    assert fc.dungeon is not None
    assert fc.dungeon.template == "procedural:cave"
    assert fc.dungeon.depth == 2
    assert fc.dungeon.faction == "goblin"


def test_non_feature_cells_have_no_dungeon() -> None:
    """Only the feature_cell holds a dungeon; other sub-hexes do not."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.CITY,
        dungeon=DungeonRef(
            template="procedural:settlement",
            depth=1,
            site_kind="town",
            size_class="city",
        ),
        elevation=0.3,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    fc = flower.feature_cell
    assert fc is not None
    for coord, cell in flower.cells.items():
        if coord == fc:
            assert cell.dungeon is not None
        else:
            assert cell.dungeon is None, (
                f"sub-hex {coord} unexpectedly has a dungeon"
            )


def test_no_feature_means_no_sub_hex_dungeon() -> None:
    """A macro with no feature yields no feature_cell and no dungeon."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.NONE,
        dungeon=None,
        elevation=0.3,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    assert flower.feature_cell is None
    assert all(c.dungeon is None for c in flower.cells.values())


def test_parent_without_dungeon_still_places_feature() -> None:
    """A macro with feature but no DungeonRef leaves sub-hex dungeon None.

    Non-enterable macros like LAKE/RIVER set ``cell.feature`` but
    leave ``cell.dungeon`` unset. The fold should copy what is
    there (a ``None``) rather than synthesise a DungeonRef.
    """
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.LAKE,
        dungeon=None,
        elevation=0.3,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    fc = flower.feature_cell
    assert fc is not None
    assert flower.cells[fc].major_feature is HexFeatureType.LAKE
    assert flower.cells[fc].dungeon is None


def test_sub_hex_dungeon_survives_save_roundtrip() -> None:
    """Serialise/deserialise preserves every DungeonRef field on the
    feature_cell sub-hex so the dispatcher can read it after reload."""
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    parent = HexCell(
        coord=HexCoord(1, 1),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.CITY,
        dungeon=DungeonRef(
            template="procedural:settlement",
            depth=1,
            site_kind="town",
            size_class="city",
            faction="human",
        ),
        elevation=0.3,
    )
    parent.flower = generate_flower(parent, {parent.coord: parent}, seed=99)
    hw.set_cell(parent)

    data = _serialize_hex_world(hw)
    hw2 = _deserialize_hex_world(data)
    cell2 = hw2.get_cell(HexCoord(1, 1))
    assert cell2 is not None
    assert cell2.flower is not None
    fc2 = cell2.flower.feature_cell
    assert fc2 is not None
    sub = cell2.flower.cells[fc2]
    assert sub.dungeon is not None
    assert sub.dungeon.template == "procedural:settlement"
    assert sub.dungeon.depth == 1
    assert sub.dungeon.site_kind == "town"
    assert sub.dungeon.size_class == "city"
    assert sub.dungeon.faction == "human"


# ---------------------------------------------------------------------------
# M2: dungeon_seed accepts an optional sub coord
# ---------------------------------------------------------------------------


def test_dungeon_seed_without_sub_is_stable() -> None:
    """Existing two-argument call path keeps its value (backward compat)."""
    s1 = dungeon_seed(123, HexCoord(1, 2), "procedural:cave")
    s2 = dungeon_seed(123, HexCoord(1, 2), "procedural:cave")
    assert s1 == s2


def test_dungeon_seed_none_sub_matches_no_sub() -> None:
    """``sub=None`` equals the no-sub path so the macro seed is stable."""
    s_none = dungeon_seed(
        123, HexCoord(1, 2), "procedural:cave", sub=None,
    )
    s_unset = dungeon_seed(123, HexCoord(1, 2), "procedural:cave")
    assert s_none == s_unset


def test_dungeon_seed_with_sub_is_stable() -> None:
    s1 = dungeon_seed(
        123, HexCoord(1, 2), "procedural:cave", sub=HexCoord(0, 1),
    )
    s2 = dungeon_seed(
        123, HexCoord(1, 2), "procedural:cave", sub=HexCoord(0, 1),
    )
    assert s1 == s2


def test_dungeon_seed_differs_from_macro_seed() -> None:
    s_macro = dungeon_seed(123, HexCoord(1, 2), "procedural:cave")
    s_sub = dungeon_seed(
        123, HexCoord(1, 2), "procedural:cave", sub=HexCoord(0, 1),
    )
    assert s_macro != s_sub


def test_dungeon_seed_distinct_subs_differ() -> None:
    s_a = dungeon_seed(
        123, HexCoord(1, 2), "procedural:cave", sub=HexCoord(0, 1),
    )
    s_b = dungeon_seed(
        123, HexCoord(1, 2), "procedural:cave", sub=HexCoord(1, 0),
    )
    assert s_a != s_b


# ---------------------------------------------------------------------------
# M2: sub-hex cache keying + LRU + mutation persistence
# ---------------------------------------------------------------------------


def _fake_level(name: str) -> object:
    """Minimal stand-in for a dungeon Level in cache-behaviour tests."""
    class _L:
        pass

    lvl = _L()
    lvl.name = name
    lvl.id = name
    return lvl


def test_sub_hex_cache_key_shape() -> None:
    """Game._cache_key returns ('sub', q, r, sq, sr, depth) when a
    sub-hex site is active, regardless of the overland coord."""
    from nhc.core.game import Game
    from nhc.hexcrawl.mode import WorldType

    game = Game.__new__(Game)
    game.world_type = WorldType.HEXCRAWL
    game.hex_player_position = HexCoord(3, 4)
    game._active_cave_cluster = None
    game._active_descent_building = None
    game._active_site = None
    game._active_sub_hex = HexCoord(-1, 0)

    key = game._cache_key(1)
    assert key == ("sub", 3, 4, -1, 0, 1)


def test_sub_hex_cache_key_distinct_per_sub() -> None:
    """Two different sub-coords under the same macro yield different
    cache keys, so each sub-hex site caches independently."""
    from nhc.core.game import Game
    from nhc.hexcrawl.mode import WorldType

    game = Game.__new__(Game)
    game.world_type = WorldType.HEXCRAWL
    game.hex_player_position = HexCoord(3, 4)
    game._active_cave_cluster = None
    game._active_descent_building = None
    game._active_site = None

    game._active_sub_hex = HexCoord(-1, 0)
    key_a = game._cache_key(1)
    game._active_sub_hex = HexCoord(1, 1)
    key_b = game._cache_key(1)
    assert key_a != key_b


def test_sub_hex_cache_key_does_not_affect_macro_keys() -> None:
    """When _active_sub_hex is None the macro-keyed path is unchanged."""
    from nhc.core.game import Game
    from nhc.hexcrawl.mode import WorldType

    game = Game.__new__(Game)
    game.world_type = WorldType.HEXCRAWL
    game.hex_player_position = HexCoord(3, 4)
    game._active_cave_cluster = None
    game._active_descent_building = None
    game._active_site = None
    game._active_sub_hex = None

    key = game._cache_key(1)
    assert key == (3, 4, 1)


def test_sub_hex_cache_lru_evicts_oldest(tmp_path) -> None:
    """After 33 distinct sub-hex inserts the first is evicted."""
    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=32, storage_dir=tmp_path, player_id="p1",
    )
    for i in range(33):
        key = ("sub", 0, 0, i, 0, 1)
        mgr.store(key, _fake_level(f"L{i}"), mutations={})
    # First insert should now be evicted.
    assert not mgr.has(("sub", 0, 0, 0, 0, 1))
    # Every later insert is still resident.
    for i in range(1, 33):
        assert mgr.has(("sub", 0, 0, i, 0, 1))


def test_sub_hex_cache_lru_access_promotes(tmp_path) -> None:
    """Reading a sub-hex entry marks it most-recently-used."""
    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=2, storage_dir=tmp_path, player_id="p1",
    )
    k0 = ("sub", 0, 0, 0, 0, 1)
    k1 = ("sub", 0, 0, 1, 0, 1)
    k2 = ("sub", 0, 0, 2, 0, 1)
    mgr.store(k0, _fake_level("L0"), mutations={})
    mgr.store(k1, _fake_level("L1"), mutations={})
    # Touch k0 so it becomes MRU.
    mgr.get(k0)
    # Inserting k2 should now evict k1, not k0.
    mgr.store(k2, _fake_level("L2"), mutations={})
    assert mgr.has(k0)
    assert not mgr.has(k1)
    assert mgr.has(k2)


def test_sub_hex_cache_mutation_persists_on_evict(tmp_path) -> None:
    """On eviction the sparse mutation record is written to disk under
    <storage_dir>/players/<pid>/sub_hex_cache/<macro>_<sub>.json."""
    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=1, storage_dir=tmp_path, player_id="p1",
    )
    k0 = ("sub", 8, 3, -1, 0, 1)
    k1 = ("sub", 8, 3, 1, 1, 1)
    mgr.store(
        k0, _fake_level("L0"),
        mutations={"looted": [[4, 2]], "killed": [101]},
    )
    # Evict k0 by inserting beyond capacity.
    mgr.store(k1, _fake_level("L1"), mutations={})

    path = (
        tmp_path / "players" / "p1" / "sub_hex_cache"
        / "8_3_-1_0.json"
    )
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["macro"] == [8, 3]
    assert data["sub"] == [-1, 0]
    assert data["mutations"]["looted"] == [[4, 2]]
    assert data["mutations"]["killed"] == [101]


def test_sub_hex_cache_mutation_load_and_delete(tmp_path) -> None:
    """load_mutations reads the persisted record then deletes the file."""
    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=1, storage_dir=tmp_path, player_id="p1",
    )
    k0 = ("sub", 8, 3, -1, 0, 1)
    k1 = ("sub", 8, 3, 1, 1, 1)
    mgr.store(
        k0, _fake_level("L0"),
        mutations={"looted": [[4, 2]]},
    )
    mgr.store(k1, _fake_level("L1"), mutations={})
    path = (
        tmp_path / "players" / "p1" / "sub_hex_cache"
        / "8_3_-1_0.json"
    )
    assert path.exists()

    loaded = mgr.load_mutations(k0)
    assert loaded == {"looted": [[4, 2]]}
    assert not path.exists()


def test_sub_hex_cache_load_mutations_missing_returns_empty(tmp_path) -> None:
    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=4, storage_dir=tmp_path, player_id="p1",
    )
    assert mgr.load_mutations(("sub", 0, 0, 0, 0, 1)) == {}


# ---------------------------------------------------------------------------
# M3: family-based sub-hex site generators
# ---------------------------------------------------------------------------


def _tier_dims(tier: str) -> tuple[int, int]:
    from nhc.hexcrawl.sub_hex_sites import SITE_TIER_DIMS, SiteTier

    return SITE_TIER_DIMS[SiteTier(tier)]


def test_wayside_well_small_tier_has_well_feature() -> None:
    """WELL → small wayside site with a 'well' feature tile."""
    from nhc.dungeon.model import Terrain
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_wayside_site,
    )

    site = generate_wayside_site(
        feature=MinorFeatureType.WELL,
        biome=Biome.GREENLANDS,
        seed=1,
        tier=SiteTier.SMALL,
    )
    w, h = _tier_dims("small")
    assert site.level.width == w
    assert site.level.height == h
    # Entry tile must be walkable.
    ex, ey = site.entry_tile
    entry = site.level.tile_at(ex, ey)
    assert entry is not None and entry.terrain is Terrain.FLOOR
    # A tile somewhere on the map is tagged as the well.
    flagged = [
        (x, y)
        for y in range(h) for x in range(w)
        if (t := site.level.tile_at(x, y)) and t.feature == "well"
    ]
    assert len(flagged) == 1


def test_wayside_signpost_has_signpost_feature() -> None:
    from nhc.dungeon.model import Terrain
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_wayside_site,
    )

    site = generate_wayside_site(
        feature=MinorFeatureType.SIGNPOST,
        biome=Biome.GREENLANDS,
        seed=7,
        tier=SiteTier.SMALL,
    )
    flagged = [
        (x, y)
        for y in range(site.level.height)
        for x in range(site.level.width)
        if (t := site.level.tile_at(x, y)) and t.feature == "signpost"
    ]
    assert len(flagged) == 1
    assert site.feature_tile == flagged[0]


def test_sacred_site_medium_tier() -> None:
    from nhc.dungeon.model import Terrain
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_sacred_site,
    )

    site = generate_sacred_site(
        feature=MinorFeatureType.SHRINE,
        biome=Biome.GREENLANDS,
        seed=42,
        tier=SiteTier.MEDIUM,
    )
    w, h = _tier_dims("medium")
    assert (site.level.width, site.level.height) == (w, h)
    # Entry tile walkable.
    ex, ey = site.entry_tile
    entry = site.level.tile_at(ex, ey)
    assert entry is not None and entry.terrain is Terrain.FLOOR


def test_inhabited_settlement_farm_medium_tier() -> None:
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_inhabited_settlement_site,
    )

    site = generate_inhabited_settlement_site(
        feature=MinorFeatureType.FARM,
        biome=Biome.GREENLANDS,
        seed=1,
        tier=SiteTier.MEDIUM,
    )
    w, h = _tier_dims("medium")
    assert (site.level.width, site.level.height) == (w, h)
    assert site.entry_tile is not None


def test_animal_den_medium_tier() -> None:
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_animal_den_site,
    )

    site = generate_animal_den_site(
        feature=MinorFeatureType.LAIR,
        biome=Biome.FOREST,
        seed=1,
        tier=SiteTier.MEDIUM,
    )
    w, h = _tier_dims("medium")
    assert (site.level.width, site.level.height) == (w, h)


def test_natural_curiosity_small_tier() -> None:
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_natural_curiosity_site,
    )

    site = generate_natural_curiosity_site(
        feature=MinorFeatureType.HERB_PATCH,
        biome=Biome.FOREST,
        seed=1,
        tier=SiteTier.SMALL,
    )
    w, h = _tier_dims("small")
    assert (site.level.width, site.level.height) == (w, h)


def test_undead_site_medium_tier() -> None:
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_undead_site,
    )

    site = generate_undead_site(
        feature=HexFeatureType.GRAVEYARD,
        biome=Biome.DEADLANDS,
        seed=1,
        tier=SiteTier.MEDIUM,
    )
    w, h = _tier_dims("medium")
    assert (site.level.width, site.level.height) == (w, h)


def test_family_generators_are_deterministic() -> None:
    """Same seed → identical level tile grid."""
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        generate_wayside_site,
    )

    s1 = generate_wayside_site(
        feature=MinorFeatureType.WELL, biome=Biome.GREENLANDS,
        seed=1234, tier=SiteTier.SMALL,
    )
    s2 = generate_wayside_site(
        feature=MinorFeatureType.WELL, biome=Biome.GREENLANDS,
        seed=1234, tier=SiteTier.SMALL,
    )
    # Compare the full tile grid (terrain + feature).
    for y in range(s1.level.height):
        for x in range(s1.level.width):
            t1 = s1.level.tile_at(x, y)
            t2 = s2.level.tile_at(x, y)
            assert t1.terrain == t2.terrain
            assert t1.feature == t2.feature
    assert s1.entry_tile == s2.entry_tile
    assert s1.feature_tile == s2.feature_tile
