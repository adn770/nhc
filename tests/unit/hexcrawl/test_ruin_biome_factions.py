"""Biome-keyed ruin faction pools (M9 of biome-features v2).

`place_features._place_ruins` should roll a faction from the cell's
biome pool and stamp it on `DungeonRef.faction`. The ruin surface
populator consults that faction, and every descent floor (1-3) must
inherit the same faction so the dungeon reads as a coherent lair
rather than a grab-bag of encounter tables.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from nhc.core.game import Game
from nhc.dungeon.populator import FACTION_POOLS
from nhc.dungeon.sites.ruin import assemble_ruin
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import (
    Biome, DungeonRef, HexCell, HexFeatureType, HexWorld,
)
from nhc.i18n import init as i18n_init


# ── Expected faction pools (design/biome_features.md §8) ──────────────

EXPECTED_RUIN_POOLS: dict[Biome, set[str]] = {
    Biome.FOREST:    {"bandit", "beast", "cultist"},
    Biome.DEADLANDS: {"undead", "cultist"},
    Biome.MARSH:     {"lizardman", "beast"},
    Biome.SANDLANDS: {"gnoll", "undead"},
    Biome.ICELANDS:  {"frozen_dead", "yeti", "cultist"},
}


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


# ── Biome pool composition ────────────────────────────────────────────

class TestRuinBiomeFactionTable:
    @pytest.mark.parametrize("biome,expected", [
        (Biome.FOREST, EXPECTED_RUIN_POOLS[Biome.FOREST]),
        (Biome.DEADLANDS, EXPECTED_RUIN_POOLS[Biome.DEADLANDS]),
        (Biome.MARSH, EXPECTED_RUIN_POOLS[Biome.MARSH]),
        (Biome.SANDLANDS, EXPECTED_RUIN_POOLS[Biome.SANDLANDS]),
        (Biome.ICELANDS, EXPECTED_RUIN_POOLS[Biome.ICELANDS]),
    ])
    def test_ruin_biome_factions_table_matches_design(self, biome, expected):
        from nhc.hexcrawl._features import RUIN_BIOME_FACTIONS
        assert biome in RUIN_BIOME_FACTIONS
        pool_ids = {entry[0] for entry in RUIN_BIOME_FACTIONS[biome]}
        assert pool_ids == expected


# ── Faction pool references only registered creatures ─────────────────

class TestFactionPoolsComplete:
    @pytest.mark.parametrize("faction_key", [
        "cultist", "lizardman", "frozen_dead", "yeti",
        "beast", "undead",
    ])
    def test_faction_pool_has_entry(self, faction_key):
        assert faction_key in FACTION_POOLS

    @pytest.mark.parametrize("faction_key", [
        "cultist", "lizardman", "frozen_dead", "yeti",
        "beast", "undead",
    ])
    def test_faction_pool_references_registered_creatures(
        self, faction_key,
    ):
        registered = set(EntityRegistry.list_creatures())
        for cid, weight in FACTION_POOLS[faction_key]:
            assert cid in registered, (
                f"{faction_key} pool refs unregistered {cid!r}"
            )
            assert weight > 0

    def test_beast_category_expands_to_concrete_creatures(self):
        from nhc.dungeon.populator import BEAST_POOL
        assert FACTION_POOLS["beast"] == BEAST_POOL

    def test_undead_category_expands_to_concrete_creatures(self):
        from nhc.dungeon.populator import UNDEAD_POOL
        assert FACTION_POOLS["undead"] == UNDEAD_POOL


# ── _place_ruins stamps the rolled faction on DungeonRef ──────────────

def _make_cells(biome: Biome, count: int = 8) -> tuple[
    dict, dict[Biome, list[HexCoord]],
]:
    """Build a trivial cell map with ``count`` hexes of ``biome``.

    Returns (cells, hexes_by_biome) suitable for feeding
    :func:`_place_ruins`. The map is a single horizontal row.
    """
    coords = [HexCoord(q, 0) for q in range(count)]
    cells = {
        c: HexCell(coord=c, biome=biome) for c in coords
    }
    hexes_by_biome = {b: [] for b in Biome}
    hexes_by_biome[biome] = list(coords)
    return cells, hexes_by_biome


@pytest.mark.parametrize("biome", [
    Biome.FOREST, Biome.DEADLANDS, Biome.MARSH,
    Biome.SANDLANDS, Biome.ICELANDS,
])
def test_ruin_faction_rolls_from_biome_pool(biome):
    """Across many seeds, every rolled faction must live in the
    biome's expected pool. Also asserts at least half the pool
    shows up over 40 rolls so we know it's not a constant."""
    from nhc.hexcrawl._features import _place_ruins

    seen: set[str] = set()
    expected_pool = EXPECTED_RUIN_POOLS[biome]
    for seed in range(40):
        cells, hexes_by_biome = _make_cells(biome, count=4)
        taken: set[HexCoord] = set()
        rng = random.Random(seed)
        _place_ruins(cells, hexes_by_biome, taken, 1, rng)
        ruin_coord = next(iter(taken))
        faction = cells[ruin_coord].dungeon.faction
        assert faction is not None, "faction must be rolled"
        assert faction in expected_pool, (
            f"{biome.value}: rolled {faction!r} not in {expected_pool}"
        )
        seen.add(faction)

    assert len(seen) >= max(2, len(expected_pool) // 2), (
        f"{biome.value}: only saw {seen}; roll distribution is "
        f"suspiciously narrow"
    )


def test_ruin_faction_is_persisted_on_dungeon_ref():
    """After _place_ruins, every RUIN hex has DungeonRef.faction set."""
    from nhc.hexcrawl._features import _place_ruins
    cells, hexes_by_biome = _make_cells(Biome.FOREST, count=5)
    taken: set[HexCoord] = set()
    _place_ruins(cells, hexes_by_biome, taken, 3, random.Random(1))
    placed = [
        c for c in cells.values()
        if c.feature is HexFeatureType.RUIN
    ]
    assert len(placed) == 3
    for cell in placed:
        assert cell.dungeon is not None
        assert cell.dungeon.faction is not None


# ── Ruin surface consults the faction pool ────────────────────────────

class TestRuinSurfaceUsesFaction:
    def test_ruin_surface_spawns_creatures_from_faction_pool(self):
        """Forest ruins with faction='bandit' spawn only bandits + pool
        mates; icelands ruins with faction='yeti' spawn only yetis +
        pool mates."""
        for biome, faction in (
            (Biome.FOREST, "bandit"),
            (Biome.ICELANDS, "yeti"),
        ):
            allowed = {cid for cid, _ in FACTION_POOLS[faction]}
            # Populate with explicit faction via a fake surface
            # assembled by the real assembler (ruins use faction via
            # metadata).
            site = assemble_ruin(
                f"ruin_{biome.value}_{faction}",
                random.Random(7), biome=biome,
            )
            site.surface.metadata.faction = faction
            from nhc.dungeon.sites.ruin import _populate_ruin_surface
            # Clear any pre-populated entities from assembly and
            # rerun with faction applied.
            site.surface.entities = []
            _populate_ruin_surface(site.surface, random.Random(7))
            creature_ids = {
                e.entity_id for e in site.surface.entities
                if e.entity_type == "creature"
            }
            assert creature_ids, (
                f"{biome.value}/{faction}: no creatures placed"
            )
            assert creature_ids <= allowed, (
                f"{biome.value}/{faction}: placed {creature_ids} "
                f"but pool allows only {allowed}"
            )

    def test_ruin_surface_without_faction_falls_back_to_default_pool(
        self,
    ):
        """When faction is None (assembler called directly, no
        DungeonRef), the populator keeps using CREATURE_POOLS[1]
        so legacy tests stay green."""
        from nhc.dungeon.populator import CREATURE_POOLS
        from nhc.dungeon.sites.ruin import _populate_ruin_surface
        site = assemble_ruin(
            "ruin_nofac", random.Random(1), biome=Biome.FOREST,
        )
        site.surface.entities = []
        site.surface.metadata.faction = None
        _populate_ruin_surface(site.surface, random.Random(1))
        default_ids = {cid for cid, _ in CREATURE_POOLS[1]}
        placed = {
            e.entity_id for e in site.surface.entities
            if e.entity_type == "creature"
        }
        assert placed, "fallback pool still places creatures"
        assert placed <= default_ids


# ── Descent floors inherit the surface faction ────────────────────────

class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(), backend=None,
        style="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path, seed=42,
    )
    g.initialize()
    return g


def _seed_forest_ruin(g: Game, faction: str = "cultist") -> HexCell:
    g.hex_world = HexWorld(
        pack_id="t", seed=42, width=1, height=1,
    )
    cell = HexCell(
        coord=HexCoord(0, 0), biome=Biome.FOREST,
        feature=HexFeatureType.RUIN,
        dungeon=DungeonRef(
            template="procedural:ruin",
            site_kind="ruin",
            faction=faction,
        ),
    )
    g.hex_world.set_cell(cell)
    g.hex_world.visit(cell.coord)
    g.hex_player_position = cell.coord
    return cell


async def _descend_onto_floor(g: Game, floor: int) -> None:
    """Park the player on ruin Floor `floor` (1..3)."""
    cell = _seed_forest_ruin(g)
    await g._enter_walled_site(cell.coord, "ruin")
    # Swap into the building so descent entry picks it up.
    assert g._active_site is not None
    building = g._active_site.buildings[0]
    g.level = building.ground
    stair_xy = next(
        (x, y)
        for y in range(building.ground.height)
        for x in range(building.ground.width)
        if building.ground.tiles[y][x].feature == "stairs_down"
    )
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = stair_xy
    pos.level_id = building.ground.id
    from nhc.core.events import LevelEntered
    for _ in range(floor):
        new_depth = g.level.depth + 1
        g._on_level_entered(LevelEntered(depth=new_depth))


class TestDescentFloorsInheritFaction:
    def test_ruin_descent_floor_1_inherits_surface_faction(
        self, tmp_path,
    ):
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, 1)
            assert g.level.depth == 2
            assert g.level.metadata is not None
            assert g.level.metadata.faction == "cultist"

        asyncio.run(_run())

    def test_ruin_descent_floors_2_and_3_share_the_faction(
        self, tmp_path,
    ):
        g = _make_game(tmp_path)

        async def _run():
            await _descend_onto_floor(g, 3)
            assert g.level.depth == 4
            assert g.level.metadata.faction == "cultist"

        asyncio.run(_run())
