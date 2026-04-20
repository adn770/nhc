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


# ---------------------------------------------------------------------------
# M4: _resolve_sub_hex_entry dispatcher resolver
# ---------------------------------------------------------------------------


def _sub_cell(*, major=HexFeatureType.NONE, minor=None, dungeon=None):
    """Build a throwaway SubHexCell for resolver tests."""
    from nhc.hexcrawl.model import SubHexCell

    return SubHexCell(
        coord=HexCoord(0, 0), biome=Biome.GREENLANDS,
        major_feature=major,
        minor_feature=minor if minor is not None else MinorFeatureType.NONE,
        dungeon=dungeon,
    )


def test_resolve_entry_bespoke_town() -> None:
    """A feature_cell sub-hex with a town DungeonRef resolves to bespoke."""
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(
        major=HexFeatureType.CITY,
        dungeon=DungeonRef(
            template="procedural:settlement", depth=1,
            site_kind="town", size_class="city",
        ),
    )
    kind, payload = resolve_sub_hex_entry(sub)
    assert kind == "bespoke"
    assert payload == "town"


def test_resolve_entry_bespoke_tower() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(
        major=HexFeatureType.TOWER,
        dungeon=DungeonRef(
            template="procedural:tower", depth=1, site_kind="tower",
        ),
    )
    kind, payload = resolve_sub_hex_entry(sub)
    assert kind == "bespoke"
    assert payload == "tower"


def test_resolve_entry_bespoke_cave() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(
        major=HexFeatureType.CAVE,
        dungeon=DungeonRef(template="procedural:cave", depth=1),
    )
    kind, payload = resolve_sub_hex_entry(sub)
    assert kind == "bespoke"
    assert payload == "cave"


def test_resolve_entry_family_wayside_well() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(minor=MinorFeatureType.WELL)
    kind, family, feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "wayside"
    assert feature is MinorFeatureType.WELL


def test_resolve_entry_family_wayside_signpost() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(minor=MinorFeatureType.SIGNPOST)
    kind, family, feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "wayside"
    assert feature is MinorFeatureType.SIGNPOST


def test_resolve_entry_family_inhabited_farm() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(minor=MinorFeatureType.FARM)
    kind, family, feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "inhabited_settlement"
    assert feature is MinorFeatureType.FARM


def test_resolve_entry_family_sacred_shrine() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(minor=MinorFeatureType.SHRINE)
    kind, family, _feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "sacred"


def test_resolve_entry_family_animal_den() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(minor=MinorFeatureType.LAIR)
    kind, family, _feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "animal_den"


def test_resolve_entry_family_curiosity_mushrooms() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(minor=MinorFeatureType.MUSHROOM_RING)
    kind, family, _feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "natural_curiosity"


def test_resolve_entry_family_undead_graveyard() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(major=HexFeatureType.GRAVEYARD)
    kind, family, _feature = resolve_sub_hex_entry(sub)
    assert kind == "family"
    assert family == "undead"


def test_resolve_entry_non_enterable_lake() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(major=HexFeatureType.LAKE)
    kind, _reason = resolve_sub_hex_entry(sub)
    assert kind == "non-enterable"


def test_resolve_entry_non_enterable_river() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    sub = _sub_cell(major=HexFeatureType.RIVER)
    kind, _reason = resolve_sub_hex_entry(sub)
    assert kind == "non-enterable"


def test_resolve_entry_empty_returns_none() -> None:
    from nhc.core.sub_hex_entry import resolve_sub_hex_entry

    assert resolve_sub_hex_entry(_sub_cell()) is None


# ---------------------------------------------------------------------------
# M4: Game.enter_sub_hex_family_site — the runtime entry path
# ---------------------------------------------------------------------------


def _flower_fixture(tmp_path, feature: MinorFeatureType):
    """Build a minimal Game positioned inside a flower on a sub-hex
    that carries ``feature``, ready for ``enter_sub_hex_family_site``."""
    import pytest as _pytest
    from nhc.core.game import Game
    from nhc.entities.registry import EntityRegistry
    from nhc.hexcrawl.mode import GameMode
    from nhc.i18n import init as i18n_init

    i18n_init("en")
    EntityRegistry.discover_all()

    class _Silent:
        game_mode = "classic"
        lang = "en"
        edge_doors = False
        messages: list[str] = []

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)

            def _sync(*_a, **_kw):
                return None

            return _sync

        async def get_input(self):
            return ("disconnect", None)

    mode = GameMode.HEX_EASY
    game = Game(
        client=_Silent(),
        backend=None,
        style="classic",
        world_type=mode.world_type, difficulty=mode.difficulty,
        save_dir=tmp_path,
        seed=42,
    )
    game.initialize()
    macro = game.hex_player_position
    cell = game.hex_world.get_cell(macro)
    # Pick any non-feature sub-hex and stamp the desired minor.
    pick = next(
        c for c, sc in cell.flower.cells.items()
        if sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )
    cell.flower.cells[pick].minor_feature = feature
    game.hex_world.enter_flower(macro, pick)
    return game, macro, pick


def test_enter_sub_hex_family_site_wayside_well(tmp_path) -> None:
    """Entering a WELL sub-hex produces a small wayside Level and
    stores it in the floor cache under the sub-hex key."""
    from nhc.hexcrawl.sub_hex_sites import SITE_TIER_DIMS, SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    import asyncio

    ok = asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert ok is True
    w, h = SITE_TIER_DIMS[SiteTier.SMALL]
    assert game.level is not None
    assert (game.level.width, game.level.height) == (w, h)
    assert game._active_sub_hex == sub

    # Cache key is the sub-hex namespace, keyed off the macro + sub
    # coords. Sub-hex keys live in the SubHexCacheManager (C1); the
    # legacy ``_floor_cache`` only holds macro-site keys.
    key = ("sub", macro.q, macro.r, sub.q, sub.r, 1)
    assert game._sub_hex_cache is not None
    assert game._sub_hex_cache.has(key)
    assert game._sub_hex_cache.get(key) is game.level
    assert key not in game._floor_cache


def test_enter_sub_hex_family_site_unknown_family(tmp_path) -> None:
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    import asyncio

    ok = asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "not_a_family", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert ok is False


def test_enter_sub_hex_family_site_cache_hit_reuses_level(tmp_path) -> None:
    """Second call with the same (macro, sub) returns the cached level."""
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    import asyncio

    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    first = game.level
    # Leave the site (clear _active_sub_hex) and re-enter.
    game._active_sub_hex = None
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert game.level is first


# ---------------------------------------------------------------------------
# B1: populator spawns SubHexSite.population into the ECS
# ---------------------------------------------------------------------------


def test_sub_hex_population_is_typed() -> None:
    """``SubHexSite.population`` is a typed dataclass, not an untyped
    dict, so generators can rely on field names instead of string
    lookups."""
    from nhc.hexcrawl.sub_hex_sites import SubHexPopulation, SubHexSite

    pop = SubHexPopulation()
    assert pop.creatures == []
    assert pop.npcs == []
    assert pop.items == []
    assert pop.features == []
    # Default on SubHexSite is an empty SubHexPopulation instance.
    from nhc.dungeon.model import Level
    level = Level.create_empty(
        id="t", name="t", depth=1, width=5, height=5,
    )
    site = SubHexSite(level=level, entry_tile=(1, 1))
    assert isinstance(site.population, SubHexPopulation)


def test_populate_sub_hex_spawns_creatures(tmp_path) -> None:
    """A family site carrying ``creatures=[("goblin", (3, 3))]`` spawns
    a goblin entity at (3, 3) whose Position.level_id matches the
    site level."""
    from nhc.core.ecs import World
    from nhc.core.sub_hex_populator import populate_sub_hex_site
    from nhc.dungeon.model import Level
    from nhc.entities.registry import EntityRegistry
    from nhc.hexcrawl.sub_hex_sites import SubHexPopulation, SubHexSite
    from nhc.i18n import init as i18n_init

    i18n_init("en")
    EntityRegistry.discover_all()

    level = Level.create_empty(
        id="sub_test", name="test", depth=1, width=10, height=10,
    )
    site = SubHexSite(
        level=level, entry_tile=(1, 1),
        population=SubHexPopulation(
            creatures=[("goblin", (3, 3))],
        ),
    )
    world = World()
    spawned = populate_sub_hex_site(world, site)
    assert len(spawned) == 1
    eid = spawned[0]
    pos = world.get_component(eid, "Position")
    assert pos is not None
    assert (pos.x, pos.y) == (3, 3)
    assert pos.level_id == level.id
    desc = world.get_component(eid, "Description")
    assert desc is not None
    assert "goblin" in desc.name.lower()


def test_populate_sub_hex_empty_is_noop(tmp_path) -> None:
    """An empty population spec spawns nothing."""
    from nhc.core.ecs import World
    from nhc.core.sub_hex_populator import populate_sub_hex_site
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.sub_hex_sites import SubHexSite

    level = Level.create_empty(
        id="sub_empty", name="e", depth=1, width=5, height=5,
    )
    site = SubHexSite(level=level, entry_tile=(1, 1))
    world = World()
    spawned = populate_sub_hex_site(world, site)
    assert spawned == []


def test_populate_sub_hex_spawns_items(tmp_path) -> None:
    """Items in the population spec land as ECS entities at the
    requested tile with Position.level_id set."""
    from nhc.core.ecs import World
    from nhc.core.sub_hex_populator import populate_sub_hex_site
    from nhc.dungeon.model import Level
    from nhc.entities.registry import EntityRegistry
    from nhc.hexcrawl.sub_hex_sites import SubHexPopulation, SubHexSite
    from nhc.i18n import init as i18n_init

    i18n_init("en")
    EntityRegistry.discover_all()
    # Pick the first registered item so the test is independent of
    # which specific items exist.
    sample = sorted(EntityRegistry.list_items())[0]

    level = Level.create_empty(
        id="sub_item", name="i", depth=1, width=5, height=5,
    )
    site = SubHexSite(
        level=level, entry_tile=(1, 1),
        population=SubHexPopulation(items=[(sample, (2, 2))]),
    )
    world = World()
    spawned = populate_sub_hex_site(world, site)
    assert len(spawned) == 1
    pos = world.get_component(spawned[0], "Position")
    assert pos is not None
    assert (pos.x, pos.y) == (2, 2)
    assert pos.level_id == level.id


def test_enter_sub_hex_family_site_populates(tmp_path) -> None:
    """Wiring check: entering a family site whose generator emits a
    creature pops it into the ECS world with a level-scoped Position."""
    import asyncio

    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier,
        SubHexPopulation,
        SubHexSite,
    )

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)

    # Monkeypatch the wayside generator so the family entry path
    # produces a site with a known creature, without polluting the
    # real wayside pool.
    import nhc.core.game as game_mod

    orig = game_mod.generate_wayside_site if hasattr(
        game_mod, "generate_wayside_site",
    ) else None
    # Actually the generator is imported inside
    # enter_sub_hex_family_site, so we monkeypatch at source.
    import nhc.hexcrawl.sub_hex_sites as sites_mod

    real = sites_mod.generate_wayside_site

    def fake_generator(*, feature, biome, seed, tier):
        site = real(
            feature=feature, biome=biome, seed=seed, tier=tier,
        )
        return SubHexSite(
            level=site.level,
            entry_tile=site.entry_tile,
            feature_tile=site.feature_tile,
            faction=site.faction,
            population=SubHexPopulation(
                creatures=[("goblin", (3, 3))],
            ),
        )

    sites_mod.generate_wayside_site = fake_generator
    try:
        asyncio.run(
            game.enter_sub_hex_family_site(
                macro, sub, "wayside", MinorFeatureType.WELL,
                SiteTier.SMALL, Biome.GREENLANDS,
            ),
        )
    finally:
        sites_mod.generate_wayside_site = real

    # One goblin should now live on the site level.
    goblins = [
        (eid, pos) for eid, pos in game.world.query("Position")
        if pos.level_id == game.level.id
        and game.world.get_component(eid, "AI")
    ]
    assert len(goblins) == 1
    _, gpos = goblins[0]
    assert (gpos.x, gpos.y) == (3, 3)


# ---------------------------------------------------------------------------
# B2: RumorSign entity + SignReadAction
# ---------------------------------------------------------------------------


def _make_rumor(world, text: str = "A caravan passed last week.") -> None:
    from nhc.hexcrawl.model import Rumor

    world.active_rumors.append(
        Rumor(id=f"r_{len(world.active_rumors)}", text=text),
    )


def test_rumor_sign_feature_registered() -> None:
    """``rumor_sign`` is registered as a feature entity with an ECS
    marker component the BumpAction router can key off."""
    from nhc.entities.registry import EntityRegistry

    EntityRegistry.discover_all()
    comps = EntityRegistry.get_feature("rumor_sign")
    assert "RumorSign" in comps
    assert "Renderable" in comps
    assert "BlocksMovement" in comps


def test_signpost_wayside_populates_rumor_sign(tmp_path) -> None:
    """Generating a wayside site for ``SIGNPOST`` lands a RumorSign
    at ``feature_tile`` in the population."""
    from nhc.hexcrawl.model import Biome
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier, generate_wayside_site,
    )

    site = generate_wayside_site(
        feature=MinorFeatureType.SIGNPOST,
        biome=Biome.GREENLANDS,
        seed=42,
        tier=SiteTier.SMALL,
    )
    assert site.feature_tile is not None
    signs = [
        (eid, xy) for eid, xy in site.population.features
        if eid == "rumor_sign"
    ]
    # Features go through the populator too; same list.
    sign_npcs = [
        (eid, xy) for eid, xy in (
            site.population.creatures + site.population.npcs
            + site.population.items + site.population.features
        ) if eid == "rumor_sign"
    ]
    assert sign_npcs, "expected a rumor_sign in the population"
    _, xy = sign_npcs[0]
    assert xy == site.feature_tile


def test_sign_read_action_dispenses_rumor(tmp_path) -> None:
    """Bumping a RumorSign fires SignReadAction and emits a
    MessageEvent whose text is the next active rumour."""
    import asyncio

    from nhc.core.actions._sign import SignReadAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    _make_rumor(game.hex_world, text="A caravan passed last week.")

    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    signs = [
        eid for eid, _ in game.world.query("RumorSign")
    ]
    assert len(signs) == 1
    action = SignReadAction(
        actor=game.player_id, sign_id=signs[0],
        hex_world=game.hex_world,
    )
    events = asyncio.run(action.execute(game.world, game.level))
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert "A caravan passed last week." in texts


def test_sign_read_action_no_rumor_emits_no_news(tmp_path) -> None:
    """Empty rumour pool produces a 'no news' message instead of
    erroring out."""
    import asyncio

    from nhc.core.actions._sign import SignReadAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier
    from nhc.i18n import t

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    # Pool is empty in the fixture.
    assert game.hex_world.active_rumors == []
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    signs = [eid for eid, _ in game.world.query("RumorSign")]
    action = SignReadAction(
        actor=game.player_id, sign_id=signs[0],
        hex_world=game.hex_world,
    )
    events = asyncio.run(action.execute(game.world, game.level))
    msgs = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert msgs, "SignReadAction must emit a message even with no rumors"
    # Use the action's own no-news key.
    assert msgs[0] == t("action.sign_read.no_news")


def test_sign_read_locale_keys_present() -> None:
    """``feature.rumor_sign`` and ``action.sign_read.no_news`` exist
    in all three locales."""
    import yaml
    from pathlib import Path

    root = Path("nhc/i18n/locales")
    for lang in ("en", "ca", "es"):
        data = yaml.safe_load((root / f"{lang}.yaml").read_text())
        feat = data.get("feature", {}).get("rumor_sign")
        assert feat and feat.get("name"), (
            f"missing feature.rumor_sign in {lang}"
        )
        assert feat.get("short"), (
            f"missing feature.rumor_sign.short in {lang}"
        )
        assert data.get("action", {}).get("sign_read", {}).get(
            "no_news"
        ), f"missing action.sign_read.no_news in {lang}"


# ---------------------------------------------------------------------------
# B3: WellDrink entity + WellInteractAction
# ---------------------------------------------------------------------------


def test_well_drink_feature_registered() -> None:
    """``well_drink`` is registered as a feature entity with a
    WellDrink marker component the BumpAction router can key off."""
    from nhc.entities.registry import EntityRegistry

    EntityRegistry.discover_all()
    comps = EntityRegistry.get_feature("well_drink")
    assert "WellDrink" in comps
    assert "Renderable" in comps
    assert "BlocksMovement" in comps


def test_well_wayside_populates_well_drink(tmp_path) -> None:
    """Generating a wayside site for ``WELL`` lands a well_drink
    feature entity at ``feature_tile`` in the population."""
    from nhc.hexcrawl.model import Biome
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier, generate_wayside_site,
    )

    site = generate_wayside_site(
        feature=MinorFeatureType.WELL,
        biome=Biome.GREENLANDS,
        seed=42,
        tier=SiteTier.SMALL,
    )
    wells = [
        (eid, xy) for eid, xy in site.population.features
        if eid == "well_drink"
    ]
    assert wells, "expected a well_drink in the population"
    _, xy = wells[0]
    assert xy == site.feature_tile


def test_well_interact_heals_one_hp(tmp_path) -> None:
    """Drinking from the well heals exactly +1 HP when below max."""
    import asyncio
    import random

    from nhc.core.actions._well import WellInteractAction
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    wells = [eid for eid, _ in game.world.query("WellDrink")]
    assert len(wells) == 1
    hp = game.world.get_component(game.player_id, "Health")
    hp.maximum = 10
    hp.current = 5
    # Force no rumour roll by seeding the RNG past 0.3.
    rng = random.Random()
    rng.seed(0xFACE)  # arbitrary; we also force random() below
    action = WellInteractAction(
        actor=game.player_id, well_id=wells[0],
        hex_world=game.hex_world,
        rng=random.Random(0),  # deterministic; triggers consistent roll
    )
    asyncio.run(action.execute(game.world, game.level))
    assert hp.current == 6


def test_well_interact_no_heal_at_full_hp(tmp_path) -> None:
    """Drinking at full HP does not overflow the health bar but the
    rumour roll still fires."""
    import asyncio
    import random

    from nhc.core.actions._well import WellInteractAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    wells = [eid for eid, _ in game.world.query("WellDrink")]
    hp = game.world.get_component(game.player_id, "Health")
    hp.maximum = 10
    hp.current = 10
    # Stack a rumour so a passing roll surfaces something.
    _make_rumor(game.hex_world, text="A bridge fell last season.")

    class _FixedRNG:
        """Roll <0.3 so the well surfaces a rumour."""

        def random(self):
            return 0.1

    action = WellInteractAction(
        actor=game.player_id, well_id=wells[0],
        hex_world=game.hex_world, rng=_FixedRNG(),
    )
    events = asyncio.run(action.execute(game.world, game.level))
    assert hp.current == 10
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert any("bridge" in t for t in texts)


def test_well_interact_surfaces_rumor_on_low_roll(tmp_path) -> None:
    """A roll below 0.3 consumes a rumour and surfaces its text."""
    import asyncio

    from nhc.core.actions._well import WellInteractAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    wells = [eid for eid, _ in game.world.query("WellDrink")]
    _make_rumor(game.hex_world, text="Thieves lurk on the west road.")

    class _LowRoll:
        def random(self):
            return 0.1

    action = WellInteractAction(
        actor=game.player_id, well_id=wells[0],
        hex_world=game.hex_world, rng=_LowRoll(),
    )
    events = asyncio.run(action.execute(game.world, game.level))
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert any("Thieves" in t for t in texts)
    assert game.hex_world.active_rumors == [], (
        "low-roll should consume the active rumour"
    )


def test_well_interact_silent_on_high_roll(tmp_path) -> None:
    """A roll >= 0.3 does not consume a rumour or emit one."""
    import asyncio

    from nhc.core.actions._well import WellInteractAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    wells = [eid for eid, _ in game.world.query("WellDrink")]
    _make_rumor(game.hex_world, text="Thieves lurk on the west road.")

    class _HighRoll:
        def random(self):
            return 0.9

    action = WellInteractAction(
        actor=game.player_id, well_id=wells[0],
        hex_world=game.hex_world, rng=_HighRoll(),
    )
    events = asyncio.run(action.execute(game.world, game.level))
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert not any("Thieves" in t for t in texts)
    assert len(game.hex_world.active_rumors) == 1


def test_well_drink_locale_keys_present() -> None:
    """Well i18n entries exist in all three locales."""
    import yaml
    from pathlib import Path

    root = Path("nhc/i18n/locales")
    for lang in ("en", "ca", "es"):
        data = yaml.safe_load((root / f"{lang}.yaml").read_text())
        well = data.get("feature", {}).get("well")
        assert well and (
            (isinstance(well, dict) and well.get("name")) or well
        ), f"missing feature.well in {lang}"
        wd = data.get("action", {}).get("well_drink", {})
        assert wd.get("healed"), f"missing action.well_drink.healed in {lang}"
        assert wd.get("rumour"), f"missing action.well_drink.rumour in {lang}"


# ---------------------------------------------------------------------------
# B4: RumorVendorInteractAction base + new NPCs
# ---------------------------------------------------------------------------


def test_rumor_vendor_interact_action_is_base() -> None:
    """``InnkeeperInteractAction`` inherits from
    :class:`RumorVendorInteractAction` so new vendor NPCs (farmer,
    campsite_traveller, orchardist) share a single dispense flow."""
    from nhc.core.actions._innkeeper import InnkeeperInteractAction
    from nhc.core.actions._rumor_vendor import (
        RumorVendorInteractAction,
    )

    assert issubclass(
        InnkeeperInteractAction, RumorVendorInteractAction,
    )


def test_new_rumor_vendor_creatures_registered() -> None:
    """farmer, campsite_traveller and orchardist are registered
    creatures and carry a RumorVendor marker."""
    from nhc.entities.registry import EntityRegistry

    EntityRegistry.discover_all()
    for entity_id in ("farmer", "campsite_traveller", "orchardist"):
        comps = EntityRegistry.get_creature(entity_id)
        assert "RumorVendor" in comps, (
            f"{entity_id} must carry the RumorVendor marker"
        )


def test_inhabited_settlement_populates_matching_npc(tmp_path) -> None:
    """The inhabited-settlement generator places the right NPC next
    to the centrepiece based on ``feature``."""
    from nhc.hexcrawl.model import Biome
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier, generate_inhabited_settlement_site,
    )

    mapping = {
        MinorFeatureType.FARM: "farmer",
        MinorFeatureType.CAMPSITE: "campsite_traveller",
        MinorFeatureType.ORCHARD: "orchardist",
    }
    for minor, expected in mapping.items():
        site = generate_inhabited_settlement_site(
            feature=minor, biome=Biome.GREENLANDS, seed=42,
            tier=SiteTier.MEDIUM,
        )
        npcs = [
            (eid, xy) for eid, xy in site.population.npcs
            if eid == expected
        ]
        assert npcs, (
            f"{minor.name}: expected NPC {expected} in population"
        )


def test_farmer_bump_dispenses_rumor(tmp_path) -> None:
    """A bump onto the farmer dispatches the rumor-vendor flow and
    emits a MessageEvent with the next overland rumour."""
    import asyncio

    from nhc.core.actions import BumpAction
    from nhc.core.actions._rumor_vendor import (
        RumorVendorInteractAction,
    )
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.FARM)
    _make_rumor(game.hex_world, text="The miller's dog has gone missing.")
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "inhabited_settlement", MinorFeatureType.FARM,
            SiteTier.MEDIUM, Biome.GREENLANDS,
        ),
    )
    farmers = [
        (eid, pos) for eid, pos in game.world.query("Position")
        if pos.level_id == game.level.id
        and game.world.has_component(eid, "RumorVendor")
    ]
    assert len(farmers) == 1
    fid, fpos = farmers[0]
    # Stand the player adjacent so the bump routes through.
    player_pos = game.world.get_component(game.player_id, "Position")
    player_pos.x = fpos.x - 1
    player_pos.y = fpos.y
    bump = BumpAction(
        actor=game.player_id, dx=1, dy=0,
        hex_world=game.hex_world,
    )
    resolved = bump.resolve(game.world, game.level)
    assert isinstance(resolved, RumorVendorInteractAction)
    events = asyncio.run(resolved.execute(game.world, game.level))
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert any("miller's dog" in t for t in texts)


# ---------------------------------------------------------------------------
# B5: wilderness signpost rumour pool
# ---------------------------------------------------------------------------


def _strip_settlements(game, within_of) -> None:
    """Remove every settlement feature within radius 6 of ``within_of``
    so the wilderness pool isn't pre-empted by a stray CITY on the
    generated continental map."""
    from nhc.hexcrawl.coords import distance as hex_distance
    from nhc.hexcrawl.model import HexFeatureType

    settlement_features = {
        HexFeatureType.VILLAGE,
        HexFeatureType.CITY,
        HexFeatureType.COMMUNITY,
        HexFeatureType.KEEP,
    }
    for coord, cell in list(game.hex_world.cells.items()):
        if (cell.feature in settlement_features
                and hex_distance(coord, within_of) <= 6):
            cell.feature = HexFeatureType.NONE
            cell.dungeon = None


def test_wilderness_rumors_table_exists() -> None:
    """``rumor.wilderness`` loads in each locale so the fallback
    pool has at least one entry to draw from."""
    from nhc.tables.registry import TableRegistry

    for lang in ("en", "ca", "es"):
        registry = TableRegistry.get_or_load(lang)
        # _get_table raises UnknownTableError when missing.
        registry._get_table("rumor.wilderness")


def test_seed_wilderness_rumor_pool_appends(tmp_path) -> None:
    """``seed_wilderness_rumor_pool`` appends 1-2 rumours to the
    world's active pool, each with a RumorSource and no reveal."""
    from nhc.hexcrawl.rumor_pool import seed_wilderness_rumor_pool

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    assert game.hex_world.active_rumors == []
    seeded = seed_wilderness_rumor_pool(
        game.hex_world, world_seed=42,
        macro_coord=macro, lang="en", count=2,
    )
    assert len(seeded) == 2
    assert len(game.hex_world.active_rumors) == 2
    for r in seeded:
        assert r.source is not None
        assert r.source.table_id == "rumor.wilderness"
        assert r.reveals is None


def test_wilderness_pool_is_per_hex_deterministic(tmp_path) -> None:
    """Same (world_seed, macro_coord) yields the same pool."""
    from nhc.hexcrawl.rumor_pool import seed_wilderness_rumor_pool

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    first = [
        (r.source.entry_id, r.text)
        for r in seed_wilderness_rumor_pool(
            game.hex_world, world_seed=42,
            macro_coord=macro, lang="en", count=2,
        )
    ]
    game.hex_world.active_rumors.clear()
    second = [
        (r.source.entry_id, r.text)
        for r in seed_wilderness_rumor_pool(
            game.hex_world, world_seed=42,
            macro_coord=macro, lang="en", count=2,
        )
    ]
    assert first == second

    # Different macro produces a different pool (otherwise the
    # per-hex seeding is broken).
    other_macro = HexCoord(macro.q + 1, macro.r + 2)
    game.hex_world.active_rumors.clear()
    other = [
        (r.source.entry_id, r.text)
        for r in seed_wilderness_rumor_pool(
            game.hex_world, world_seed=42,
            macro_coord=other_macro, lang="en", count=2,
        )
    ]
    # Stable determinism must include the macro — at least the
    # pair of texts should diverge for some offset.
    assert other != first or len(first) == 1


def test_has_settlement_in_reach(tmp_path) -> None:
    """``has_settlement_in_reach`` detects a nearby keep/town/village."""
    from nhc.hexcrawl.model import HexFeatureType
    from nhc.hexcrawl.rumor_pool import has_settlement_in_reach

    game, macro, _ = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    _strip_settlements(game, macro)
    assert not has_settlement_in_reach(
        game.hex_world, macro, radius=3,
    )
    # Plant a village adjacent.
    neighbor = HexCoord(macro.q + 1, macro.r)
    if neighbor in game.hex_world.cells:
        game.hex_world.cells[neighbor].feature = (
            HexFeatureType.VILLAGE
        )
    assert has_settlement_in_reach(
        game.hex_world, macro, radius=3,
    )


def test_signpost_reads_wilderness_rumor_when_isolated(tmp_path) -> None:
    """In a macro hex with no settlement within radius 3, bumping a
    signpost with an empty rumour pool seeds the wilderness pool and
    dispenses one of its entries."""
    import asyncio

    from nhc.core.actions._sign import SignReadAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    _strip_settlements(game, macro)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    signs = [eid for eid, _ in game.world.query("RumorSign")]
    action = SignReadAction(
        actor=game.player_id, sign_id=signs[0],
        hex_world=game.hex_world,
    )
    events = asyncio.run(action.execute(game.world, game.level))
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    assert texts and texts[0], (
        "signpost should surface a wilderness rumour"
    )
    # The dispensed rumour must match a wilderness-table entry.
    from nhc.tables.registry import TableRegistry

    registry = TableRegistry.get_or_load("en")
    table = registry._get_table("rumor.wilderness")
    # Render every entry and check the dispensed text matches one.
    rendered = {
        registry.render(
            "rumor.wilderness", entry_id=e.id, context={}
        ).text
        for e in table.entries
    }
    assert texts[0] in rendered


def test_signpost_near_settlement_does_not_seed_wilderness(
    tmp_path,
) -> None:
    """With the town pool empty and a settlement within reach,
    bumping a signpost falls back to the come-back-later beat, NOT
    a wilderness rumour."""
    import asyncio

    from nhc.core.actions._sign import SignReadAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.model import HexFeatureType
    from nhc.hexcrawl.sub_hex_sites import SiteTier
    from nhc.i18n import t

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.SIGNPOST)
    _strip_settlements(game, macro)
    # Plant a village within reach.
    neighbor = HexCoord(macro.q + 1, macro.r)
    assert neighbor in game.hex_world.cells
    game.hex_world.cells[neighbor].feature = HexFeatureType.VILLAGE
    # Simulate a town visit: last_rumor_day > 0 but the pool is
    # empty right now (all rumours consumed earlier).
    game.hex_world.last_rumor_day = 1
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    signs = [eid for eid, _ in game.world.query("RumorSign")]
    action = SignReadAction(
        actor=game.player_id, sign_id=signs[0],
        hex_world=game.hex_world,
    )
    events = asyncio.run(action.execute(game.world, game.level))
    texts = [
        ev.text for ev in events if isinstance(ev, MessageEvent)
    ]
    # Must match the localized no_news fallback exactly — wilderness
    # seed is skipped so the sign surfaces the standard beat.
    assert texts == [t("action.sign_read.no_news")]


# ---------------------------------------------------------------------------
# C1: route family-site entries through SubHexCacheManager
# ---------------------------------------------------------------------------


def test_family_entry_populates_sub_hex_cache(tmp_path) -> None:
    """After entering a family site, the sub-hex key lives in the
    SubHexCacheManager, not the legacy ``_floor_cache``."""
    import asyncio

    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    key = ("sub", macro.q, macro.r, sub.q, sub.r, 1)
    assert game._sub_hex_cache is not None
    assert game._sub_hex_cache.has(key)
    # The sub-hex key must NOT also live in the plain floor cache.
    assert key not in game._floor_cache


def test_family_entry_reuses_cached_level_from_manager(tmp_path) -> None:
    """Cache-hit path returns the same Level instance from the manager."""
    import asyncio

    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    first = game.level
    game._active_sub_hex = None
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert game.level is first


def test_sub_hex_cache_capacity_evicts_oldest(tmp_path) -> None:
    """With the manager's capacity forced to 1, entering a second
    distinct sub-hex site evicts the first."""
    import asyncio

    from nhc.core.sub_hex_cache import SubHexCacheManager
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub_a = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    # Pick a second non-feature sub-hex to stamp another minor onto.
    cell = game.hex_world.get_cell(macro)
    sub_b = next(
        c for c, sc in cell.flower.cells.items()
        if c != sub_a
        and sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )
    cell.flower.cells[sub_b].minor_feature = MinorFeatureType.SIGNPOST

    # Force a 1-slot manager via a pre-emptive replacement so Game
    # picks it up on first entry.
    game._sub_hex_cache = SubHexCacheManager(
        capacity=1, storage_dir=tmp_path, player_id="test",
    )
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    key_a = ("sub", macro.q, macro.r, sub_a.q, sub_a.r, 1)
    assert game._sub_hex_cache.has(key_a)

    # Leave sub_a and enter sub_b; this should evict sub_a.
    game._active_sub_hex = None
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_b, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    key_b = ("sub", macro.q, macro.r, sub_b.q, sub_b.r, 1)
    assert game._sub_hex_cache.has(key_b)
    assert not game._sub_hex_cache.has(key_a)


def test_re_entry_after_eviction_regenerates_level(tmp_path) -> None:
    """Re-entering an evicted sub-hex site produces a fresh Level
    (distinct object from the original, but functionally equivalent
    because the seed is deterministic)."""
    import asyncio

    from nhc.core.sub_hex_cache import SubHexCacheManager
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub_a = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    cell = game.hex_world.get_cell(macro)
    sub_b = next(
        c for c, sc in cell.flower.cells.items()
        if c != sub_a
        and sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )
    cell.flower.cells[sub_b].minor_feature = MinorFeatureType.SIGNPOST
    game._sub_hex_cache = SubHexCacheManager(
        capacity=1, storage_dir=tmp_path, player_id="test",
    )
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    original_level = game.level
    game._active_sub_hex = None
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_b, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    game._active_sub_hex = None
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert game.level is not original_level
    # Deterministic regeneration: same dimensions and id prefix.
    assert game.level.width == original_level.width
    assert game.level.height == original_level.height


# ---------------------------------------------------------------------------
# C2: record sub-hex mutations via EventBus
# ---------------------------------------------------------------------------


def _active_sub_hex_mutations(game) -> dict:
    """Helper: read the mutation dict for the currently active sub-hex
    cache entry straight from the manager."""
    macro = game.hex_world.exploring_hex
    sub = game._active_sub_hex
    key = ("sub", macro.q, macro.r, sub.q, sub.r, 1)
    entry = game._sub_hex_cache._entries.get(key)
    assert entry is not None
    return entry["mutations"]


def test_terrain_changed_event_exists() -> None:
    """``TerrainChanged`` is a pub/sub Event carrying tile coord +
    the applied change kind."""
    from nhc.core.events import Event, TerrainChanged

    ev = TerrainChanged(x=2, y=3, kind="dug")
    assert isinstance(ev, Event)
    assert (ev.x, ev.y, ev.kind) == (2, 3, "dug")


def test_item_pickup_appends_looted_tile(tmp_path) -> None:
    """Picking up an item inside a sub-hex site appends its tile to
    ``mutations['looted']`` of that site's cache entry."""
    import asyncio

    from nhc.core.events import ItemPickedUp
    from nhc.entities.components import Position
    from nhc.entities.registry import EntityRegistry
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    EntityRegistry.discover_all()
    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    # Spawn a fake item at (4, 2) and move the actor onto it so the
    # handler can read Position off the actor.
    actor_pos = game.world.get_component(game.player_id, "Position")
    actor_pos.x, actor_pos.y = 4, 2
    asyncio.run(
        game.event_bus.emit(ItemPickedUp(
            entity=game.player_id, item=-1,
        )),
    )
    muts = _active_sub_hex_mutations(game)
    assert [4, 2] in muts.get("looted", [])


def test_creature_died_appends_killed(tmp_path) -> None:
    """A CreatureDied event inside a sub-hex site appends to
    ``mutations['killed']``."""
    import asyncio

    from nhc.core.events import CreatureDied
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    asyncio.run(
        game.event_bus.emit(CreatureDied(
            entity=4242, killer=game.player_id, cause="melee",
        )),
    )
    muts = _active_sub_hex_mutations(game)
    assert 4242 in muts.get("killed", [])


def test_door_opened_records_door_state(tmp_path) -> None:
    """DoorOpened inside a sub-hex site records ``{'x,y': 'open'}``."""
    import asyncio

    from nhc.core.events import DoorOpened
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    asyncio.run(
        game.event_bus.emit(DoorOpened(
            entity=game.player_id, x=5, y=3,
        )),
    )
    muts = _active_sub_hex_mutations(game)
    assert muts.get("doors", {}).get("5,3") == "open"


def test_terrain_changed_records_dug_tile(tmp_path) -> None:
    """TerrainChanged (kind='dug') inside a sub-hex site records
    ``{'x,y': 'dug'}`` in terrain mutations."""
    import asyncio

    from nhc.core.events import TerrainChanged
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    asyncio.run(
        game.event_bus.emit(TerrainChanged(x=7, y=4, kind="dug")),
    )
    muts = _active_sub_hex_mutations(game)
    assert muts.get("terrain", {}).get("7,4") == "dug"


def test_mutation_handlers_no_op_outside_sub_hex(tmp_path) -> None:
    """Emitting a mutation event outside an active sub-hex site is
    a no-op — no cache entry is touched."""
    import asyncio

    from nhc.core.events import CreatureDied, DoorOpened

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    # Never entered a sub-hex family site — manager is lazy and
    # _active_sub_hex is still None.
    assert game._active_sub_hex is None
    asyncio.run(
        game.event_bus.emit(CreatureDied(entity=1, cause="x")),
    )
    asyncio.run(
        game.event_bus.emit(DoorOpened(entity=1, x=0, y=0)),
    )
    # No exception raised; the handlers short-circuited.
    assert game._active_sub_hex is None


def test_dig_action_emits_terrain_changed(tmp_path) -> None:
    """DigAction on a wall emits a TerrainChanged event so the
    mutation handler observes the dig."""
    import asyncio

    from nhc.core.actions import DigAction
    from nhc.core.events import TerrainChanged
    from nhc.dungeon.model import Level, Terrain

    level = Level.create_empty(
        id="t", name="t", depth=1, width=5, height=5,
    )
    for y in range(5):
        for x in range(5):
            level.tiles[y][x].terrain = Terrain.FLOOR
    level.tiles[2][3].terrain = Terrain.WALL

    from nhc.core.ecs import World
    from nhc.entities.components import (
        Equipment, Position, Stats,
    )
    world = World()
    # Create a minimal actor with a digging tool.
    actor = world.create_entity({
        "Position": Position(x=2, y=2, level_id=level.id),
        "Stats": Stats(strength=5),
        "Equipment": Equipment(),
    })
    # Forge a digging tool entity.
    from nhc.entities.components import DiggingTool, Weapon
    tool = world.create_entity({
        "Weapon": Weapon(damage="1d6"),
        "DiggingTool": DiggingTool(bonus=5),
    })
    equip = world.get_component(actor, "Equipment")
    equip.weapon = tool

    action = DigAction(actor=actor, dx=1, dy=0)
    # Force a guaranteed success with a high-str modifier.
    events = asyncio.run(action.execute(world, level))
    terrain_events = [
        e for e in events if isinstance(e, TerrainChanged)
    ]
    assert terrain_events, (
        "DigAction on a wall must emit TerrainChanged"
    )
    ev = terrain_events[0]
    assert (ev.x, ev.y, ev.kind) == (3, 2, "dug")


# ---------------------------------------------------------------------------
# C3: replay sub-hex mutations on re-entry
# ---------------------------------------------------------------------------


def _force_eviction(game, macro, sub_a, sub_b, tmp_path) -> None:
    """Force the current sub-hex site (sub_a) to be evicted from the
    manager by lowering capacity to 1 and entering a second site.

    Leaves the player back on sub_b's level with sub_a evicted. On the
    evicted site's next entry, the manager runs a cache miss.
    """
    import asyncio

    from nhc.core.sub_hex_cache import SubHexCacheManager
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    # Replace the manager with a 1-slot version that preserves any
    # already-recorded mutations on sub_a.
    prev = game._sub_hex_cache
    new = SubHexCacheManager(
        capacity=1, storage_dir=tmp_path, player_id="test",
    )
    if prev is not None:
        for k, v in prev._entries.items():
            new.store(k, v["level"], mutations=v["mutations"])
    game._sub_hex_cache = new
    # Exit sub_a so the next entry lands us on sub_b.
    from nhc.core.events import LeaveSiteRequested
    asyncio.run(
        game.event_bus.emit(LeaveSiteRequested(actor=game.player_id)),
    )
    # Enter sub_b; capacity=1 evicts sub_a, persisting its mutations
    # to disk.
    cell = game.hex_world.get_cell(macro)
    cell.flower.cells[sub_b].minor_feature = MinorFeatureType.SIGNPOST
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_b, "wayside", MinorFeatureType.SIGNPOST,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    # Exit sub_b; sub_b's mutations evict to disk too (empty record).
    asyncio.run(
        game.event_bus.emit(LeaveSiteRequested(actor=game.player_id)),
    )


def test_replay_looted_removes_item(tmp_path) -> None:
    """Loot an item at (4, 2), evict, re-enter — the populator must
    skip the placement at that tile."""
    import asyncio

    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier, SubHexPopulation, SubHexSite,
    )
    from nhc.entities.registry import EntityRegistry

    EntityRegistry.discover_all()
    game, macro, sub_a = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    cell = game.hex_world.get_cell(macro)
    sub_b = next(
        c for c, sc in cell.flower.cells.items()
        if c != sub_a
        and sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )

    # Patch the wayside generator to stamp a known item on the map.
    import nhc.hexcrawl.sub_hex_sites as sites_mod

    real = sites_mod.generate_wayside_site
    sample_item = sorted(EntityRegistry.list_items())[0]

    def fake(*, feature, biome, seed, tier):
        site = real(
            feature=feature, biome=biome, seed=seed, tier=tier,
        )
        return SubHexSite(
            level=site.level,
            entry_tile=site.entry_tile,
            feature_tile=site.feature_tile,
            faction=site.faction,
            population=SubHexPopulation(
                items=[(sample_item, (4, 2))],
                features=list(site.population.features),
            ),
        )

    sites_mod.generate_wayside_site = fake
    try:
        asyncio.run(
            game.enter_sub_hex_family_site(
                macro, sub_a, "wayside", MinorFeatureType.WELL,
                SiteTier.SMALL, Biome.GREENLANDS,
            ),
        )
        # Item should exist at (4, 2) on this level.
        before = [
            eid for eid, pos in game.world.query("Position")
            if pos.level_id == game.level.id and (pos.x, pos.y) == (4, 2)
        ]
        assert before, "precondition: item exists at (4, 2)"
        # Record the loot.
        game._append_sub_hex_mutation("looted", [4, 2])
        _force_eviction(game, macro, sub_a, sub_b, tmp_path)
        # Re-enter sub_a.
        asyncio.run(
            game.enter_sub_hex_family_site(
                macro, sub_a, "wayside", MinorFeatureType.WELL,
                SiteTier.SMALL, Biome.GREENLANDS,
            ),
        )
        after = [
            eid for eid, pos in game.world.query("Position")
            if pos.level_id == game.level.id and (pos.x, pos.y) == (4, 2)
        ]
        assert not after, (
            "looted tile should not re-spawn the item on re-entry"
        )
    finally:
        sites_mod.generate_wayside_site = real


def test_replay_killed_skips_creature(tmp_path) -> None:
    """Kill a creature at (3, 3), evict, re-enter — the populator
    skips it via the stable-id record."""
    import asyncio

    from nhc.core.sub_hex_populator import populate_sub_hex_site  # noqa
    from nhc.hexcrawl.sub_hex_sites import (
        SiteTier, SubHexPopulation, SubHexSite,
    )
    import nhc.hexcrawl.sub_hex_sites as sites_mod

    game, macro, sub_a = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    cell = game.hex_world.get_cell(macro)
    sub_b = next(
        c for c, sc in cell.flower.cells.items()
        if c != sub_a
        and sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )

    real = sites_mod.generate_wayside_site

    def fake(*, feature, biome, seed, tier):
        site = real(
            feature=feature, biome=biome, seed=seed, tier=tier,
        )
        return SubHexSite(
            level=site.level, entry_tile=site.entry_tile,
            feature_tile=site.feature_tile, faction=site.faction,
            population=SubHexPopulation(
                creatures=[("goblin", (3, 3))],
                features=list(site.population.features),
            ),
        )

    sites_mod.generate_wayside_site = fake
    try:
        asyncio.run(
            game.enter_sub_hex_family_site(
                macro, sub_a, "wayside", MinorFeatureType.WELL,
                SiteTier.SMALL, Biome.GREENLANDS,
            ),
        )
        goblins = [
            eid for eid, _ in game.world.query("AI")
            if (pos := game.world.get_component(eid, "Position"))
            and pos.level_id == game.level.id and (pos.x, pos.y) == (3, 3)
        ]
        assert goblins
        # Record the kill using the populator stable id for (goblin,3,3).
        game._append_sub_hex_mutation("killed", "goblin_3_3")
        _force_eviction(game, macro, sub_a, sub_b, tmp_path)
        asyncio.run(
            game.enter_sub_hex_family_site(
                macro, sub_a, "wayside", MinorFeatureType.WELL,
                SiteTier.SMALL, Biome.GREENLANDS,
            ),
        )
        respawned = [
            eid for eid, _ in game.world.query("AI")
            if (pos := game.world.get_component(eid, "Position"))
            and pos.level_id == game.level.id and (pos.x, pos.y) == (3, 3)
        ]
        assert not respawned, (
            "killed creature must not re-spawn on re-entry"
        )
    finally:
        sites_mod.generate_wayside_site = real


def test_replay_doors_restores_open_state(tmp_path) -> None:
    """An opened door persists across eviction — the tile re-opens
    on re-entry."""
    import asyncio

    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub_a = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    cell = game.hex_world.get_cell(macro)
    sub_b = next(
        c for c, sc in cell.flower.cells.items()
        if c != sub_a
        and sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    # Plant a closed-door tile we can flip.
    tile = game.level.tile_at(3, 3)
    tile.feature = "door_closed"
    # Record the open mutation.
    game._set_sub_hex_mutation("doors", "3,3", "open")
    _force_eviction(game, macro, sub_a, sub_b, tmp_path)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert game.level.tile_at(3, 3).feature == "door_open"


def test_replay_terrain_restores_dug(tmp_path) -> None:
    """A dug wall persists across eviction — the tile comes back as
    floor with dug_wall True."""
    import asyncio

    from nhc.dungeon.model import Terrain
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub_a = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    cell = game.hex_world.get_cell(macro)
    sub_b = next(
        c for c, sc in cell.flower.cells.items()
        if c != sub_a
        and sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    # Target a boundary wall tile.
    tile = game.level.tile_at(0, 0)
    assert tile.terrain is Terrain.WALL
    game._set_sub_hex_mutation("terrain", "0,0", "dug")
    _force_eviction(game, macro, sub_a, sub_b, tmp_path)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub_a, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    replayed = game.level.tile_at(0, 0)
    assert replayed.terrain is Terrain.FLOOR
    assert replayed.dug_wall is True


# ---------------------------------------------------------------------------
# C4: GC stale mutation records at save time
# ---------------------------------------------------------------------------


def test_gc_old_records_unlinks_old_files(tmp_path) -> None:
    """``SubHexCacheManager.gc_old_records`` unlinks files whose mtime
    is older than ``max_age_days`` and preserves fresh ones."""
    import os
    import time

    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=4, storage_dir=tmp_path, player_id="p1",
    )
    cache_dir = tmp_path / "players" / "p1" / "sub_hex_cache"
    cache_dir.mkdir(parents=True)
    old_path = cache_dir / "8_3_-1_0.json"
    new_path = cache_dir / "8_3_1_1.json"
    old_path.write_text("{}")
    new_path.write_text("{}")
    # Back-date the old file 100 days.
    hundred_days_ago = time.time() - 100 * 24 * 60 * 60
    os.utime(old_path, (hundred_days_ago, hundred_days_ago))

    mgr.gc_old_records(max_age_days=90)
    assert not old_path.exists()
    assert new_path.exists()


def test_gc_old_records_handles_missing_dir(tmp_path) -> None:
    """gc_old_records is a no-op when the cache directory doesn't
    exist yet (first-run path)."""
    from nhc.core.sub_hex_cache import SubHexCacheManager

    mgr = SubHexCacheManager(
        capacity=4, storage_dir=tmp_path, player_id="never-made",
    )
    # Must not raise.
    mgr.gc_old_records(max_age_days=90)


def test_autosave_triggers_gc_old_records(tmp_path) -> None:
    """Game.autosave / _build_payload path invokes gc_old_records
    on the sub-hex cache so long-dead records don't linger forever."""
    import os
    import time

    # Ensure the manager is set up so the autosave GC hook has
    # something to call. Enter a sub-hex site to materialise it.
    import asyncio

    from nhc.core.autosave import autosave as autosave_fn
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    assert game._sub_hex_cache is not None
    cache_dir = game._sub_hex_cache._cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    old_file = cache_dir / "99_99_99_99.json"
    old_file.write_text("{}")
    hundred_days_ago = time.time() - 120 * 24 * 60 * 60
    os.utime(old_file, (hundred_days_ago, hundred_days_ago))

    autosave_fn(game, game.save_dir, blocking=True)
    assert not old_file.exists(), (
        "autosave must GC old sub-hex mutation records"
    )


# ---------------------------------------------------------------------------
# A3: day clock freezes for the duration of a sub-hex family visit
# ---------------------------------------------------------------------------


def test_sub_hex_family_visit_does_not_advance_day_clock(tmp_path) -> None:
    """Entering a sub-hex site, ticking turns inside, and exiting
    through the leave-site event leaves ``hex_world.day`` /
    ``hex_world.time`` / ``hex_world.hour`` untouched. Matches the
    behaviour of a macro-feature dungeon visit (caves, towns): time
    inside a site is "out of band" for the overland clock."""
    import asyncio

    from nhc.core.events import LeaveSiteRequested
    from nhc.hexcrawl.sub_hex_sites import SiteTier

    game, macro, sub = _flower_fixture(tmp_path, MinorFeatureType.WELL)
    day0 = game.hex_world.day
    time0 = game.hex_world.time
    hour0 = game.hex_world.hour

    asyncio.run(
        game.enter_sub_hex_family_site(
            macro, sub, "wayside", MinorFeatureType.WELL,
            SiteTier.SMALL, Biome.GREENLANDS,
        ),
    )
    # Simulate in-site turns. The dungeon-tick path does not touch
    # ``hex_world.advance_clock``; bumping ``game.turn`` stands in
    # for a handful of in-level moves without wiring a full turn
    # loop into the test.
    for _ in range(10):
        game.turn += 1

    assert game.hex_world.day == day0
    assert game.hex_world.time is time0
    assert game.hex_world.hour == hour0

    asyncio.run(
        game.event_bus.emit(LeaveSiteRequested(actor=game.player_id)),
    )
    assert game.level is None
    assert game.hex_world.day == day0
    assert game.hex_world.time is time0
    assert game.hex_world.hour == hour0


# ---------------------------------------------------------------------------
# M5: welcome message / i18n hint updates
# ---------------------------------------------------------------------------


def test_overland_enter_hint_mentions_x_explore() -> None:
    """The overland tile hint should read 'x to explore', not 'e to enter'."""
    import yaml
    from pathlib import Path

    root = Path("nhc/i18n/locales")
    for lang in ("en", "ca", "es"):
        data = yaml.safe_load((root / f"{lang}.yaml").read_text())
        hint = data["hex"]["ui"]["enter_hint"]
        controls = data["hex"]["ui"]["controls"]
        assert "x" in hint.lower(), f"{lang}: {hint}"
        # The old binding (standalone 'e enter ·') is gone.
        assert " e enter" not in controls
        assert " e entrar" not in controls
        assert "x " in controls


def test_flower_welcome_message_mentions_x_and_L(tmp_path) -> None:
    """Starting a hex game in flower view shows the new x/L hint."""
    from nhc.core.game import Game
    from nhc.entities.registry import EntityRegistry
    from nhc.hexcrawl.mode import GameMode
    from nhc.i18n import init as i18n_init

    i18n_init("en")
    EntityRegistry.discover_all()

    captured: list[str] = []

    class _Capture:
        game_mode = "classic"
        lang = "en"
        edge_doors = False
        messages: list[str] = []

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)

            def _sync(*_a, **_kw):
                return None

            return _sync

        def add_message(self, text):
            captured.append(text)

        async def get_input(self):
            return ("disconnect", None)

    mode = GameMode.HEX_EASY
    game = Game(
        client=_Capture(),
        backend=None, style="classic",
        world_type=mode.world_type, difficulty=mode.difficulty,
        save_dir=tmp_path, seed=42,
    )
    game.initialize()
    joined = " | ".join(captured)
    assert "'x'" in joined
    assert "'L'" in joined
    # Old 'e' binding is gone.
    assert "'e'" not in joined


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
