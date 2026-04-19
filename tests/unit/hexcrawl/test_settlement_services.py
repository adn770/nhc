"""Settlement services wiring.

Every settlement hex (hamlet / village / town / city) routes
through the town site assembler. The assembler tags three
buildings with service roles (shop / inn / temple) and appends
NPC :class:`EntityPlacement`s to each tagged building's ground
floor: a merchant in the shop, an innkeeper + hirable adventurer
in the inn, a priest in the temple. Stable and training are
reserved slots (no NPCs in v1).

The NPCs become ECS entities only when the player crosses the
matching building's door -- ``Game._swap_to_building`` calls
``_spawn_level_entities`` on the target level. These tests
exercise both halves: the static placement on the assembled
Site and the dynamic spawn via a simulated door crossing.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.game import Game
from nhc.dungeon.sites.town import assemble_town
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.i18n import init as i18n_init


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


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_hex_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _settle_hub(g: Game) -> HexCoord:
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    if cell.feature is HexFeatureType.NONE:
        cell.feature = HexFeatureType.CITY
    cell.dungeon = DungeonRef(
        template="procedural:settlement", size_class="village",
    )
    return coord


def _building_with_role(site, role: str):
    return next(
        b for b in site.buildings
        if role in b.ground.rooms[0].tags
    )


# ---------------------------------------------------------------------------
# Assembler: service-building placements
# ---------------------------------------------------------------------------


def test_town_places_merchant_in_shop_building() -> None:
    site = assemble_town(
        "t1", random.Random(1), size_class="village",
    )
    shop = _building_with_role(site, "shop")
    merchants = [
        p for p in shop.ground.entities
        if p.entity_id == "merchant"
    ]
    assert len(merchants) == 1
    assert merchants[0].extra.get("shop_stock"), (
        "merchant needs a non-empty stock"
    )


def test_town_places_priest_in_temple_building() -> None:
    site = assemble_town(
        "t1", random.Random(1), size_class="village",
    )
    temple = _building_with_role(site, "temple")
    priests = [
        p for p in temple.ground.entities
        if p.entity_id == "priest"
    ]
    assert len(priests) == 1
    assert priests[0].extra.get("temple_services"), (
        "priest needs temple_services set"
    )


def test_town_places_hirable_adventurer_in_inn() -> None:
    site = assemble_town(
        "t1", random.Random(1), size_class="village",
    )
    inn = _building_with_role(site, "inn")
    adventurers = [
        p for p in inn.ground.entities
        if p.entity_id == "adventurer"
    ]
    assert len(adventurers) == 1
    assert adventurers[0].extra.get("adventurer_level", 0) >= 1


def test_town_places_innkeeper_in_inn() -> None:
    site = assemble_town(
        "t1", random.Random(1), size_class="village",
    )
    inn = _building_with_role(site, "inn")
    innkeepers = [
        p for p in inn.ground.entities
        if p.entity_id == "innkeeper"
    ]
    assert len(innkeepers) == 1


# ---------------------------------------------------------------------------
# Game wiring: crossing a door materialises the NPC as an ECS entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_shop_building_spawns_merchant(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    site = g._active_site
    shop = _building_with_role(site, "shop")
    # Swap in via the door-crossing helper; this is the same code
    # path the runtime handler uses after a move lands on an open
    # surface door.
    g._swap_to_building(shop, *shop.base_rect.center)
    merchants = [
        (eid, inv)
        for eid, inv in g.world.query("ShopInventory")
        if g.world.get_component(eid, "TempleServices") is None
    ]
    assert len(merchants) == 1
    _eid, stock = merchants[0]
    assert stock.stock


@pytest.mark.asyncio
async def test_enter_temple_building_spawns_priest(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    site = g._active_site
    temple = _building_with_role(site, "temple")
    g._swap_to_building(temple, *temple.base_rect.center)
    priests = list(g.world.query("TempleServices"))
    assert len(priests) == 1
    _eid, svc = priests[0]
    assert "heal" in svc.services


@pytest.mark.asyncio
async def test_enter_inn_building_spawns_hirable_adventurer(
    tmp_path,
) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    site = g._active_site
    inn = _building_with_role(site, "inn")
    g._swap_to_building(inn, *inn.base_rect.center)
    unhired = [
        (eid, h) for eid, h in g.world.query("Henchman")
        if not h.hired
    ]
    assert len(unhired) == 1


@pytest.mark.asyncio
async def test_leaving_and_reentering_building_preserves_merchant_state(
    tmp_path,
) -> None:
    """Entity stashing across door swaps keeps the merchant gone
    when the player destroys them and re-enters the shop."""
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    site = g._active_site
    shop = _building_with_role(site, "shop")
    g._swap_to_building(shop, *shop.base_rect.center)
    # Destroy the merchant to simulate a sale-emptied shop.
    for eid, _ in list(g.world.query("ShopInventory")):
        if g.world.get_component(eid, "TempleServices") is None:
            g.world.destroy_entity(eid)
    # Step back out onto the surface and then into the shop again.
    g._swap_to_site_surface(*next(iter(site.building_doors.keys())))
    g._swap_to_building(shop, *shop.base_rect.center)
    remaining = [
        eid for eid, _ in g.world.query("ShopInventory")
        if g.world.get_component(eid, "TempleServices") is None
    ]
    assert remaining == []
