"""Settlement services wiring (M-2.3).

When the player enters a settlement hex, the generated town
Level should carry entity placements for a merchant (shop
room), a priest (temple room), and a hirable adventurer (inn
room). Spawning them via ``_spawn_level_entities`` lets the
existing :mod:`nhc.core.actions._shop`, ``_temple``, and
``_henchman`` interact actions fire on a bump, unchanged.

Stable and training rooms stay empty in v1 -- stable is a
mount-system placeholder, training is reserved for a future
XP-sink service. They exist here as tagged rooms so pack
descriptions and future wiring have a slot to hook into.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.hexcrawl.town import generate_town
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
    cell.dungeon = DungeonRef(template="procedural:settlement")
    return coord


def _room_with_tag(level, tag: str):
    for room in level.rooms:
        if tag in room.tags:
            return room
    raise AssertionError(f"no room tagged {tag!r}")


# ---------------------------------------------------------------------------
# Generator: placements on the Level match room tags
# ---------------------------------------------------------------------------


def test_town_places_merchant_in_shop_room() -> None:
    level = generate_town(seed=1)
    shop = _room_with_tag(level, "shop")
    merchants = [p for p in level.entities if p.entity_id == "merchant"]
    assert len(merchants) == 1, "town should place exactly one merchant"
    p = merchants[0]
    rect = shop.rect
    assert rect.x <= p.x < rect.x + rect.width
    assert rect.y <= p.y < rect.y + rect.height
    assert p.extra.get("shop_stock"), "merchant needs a non-empty stock"


def test_town_places_priest_in_temple_room() -> None:
    level = generate_town(seed=1)
    temple = _room_with_tag(level, "temple")
    priests = [p for p in level.entities if p.entity_id == "priest"]
    assert len(priests) == 1
    p = priests[0]
    rect = temple.rect
    assert rect.x <= p.x < rect.x + rect.width
    assert rect.y <= p.y < rect.y + rect.height
    assert p.extra.get("temple_services"), (
        "priest needs temple_services set"
    )


def test_town_places_hirable_adventurer_in_inn() -> None:
    level = generate_town(seed=1)
    inn = _room_with_tag(level, "inn")
    adventurers = [p for p in level.entities if p.entity_id == "adventurer"]
    assert len(adventurers) == 1
    p = adventurers[0]
    rect = inn.rect
    assert rect.x <= p.x < rect.x + rect.width
    assert rect.y <= p.y < rect.y + rect.height
    # Level-scaled adventurer factory needs a level hint.
    assert p.extra.get("adventurer_level", 0) >= 1


def test_town_leaves_stable_and_training_empty() -> None:
    level = generate_town(seed=1)
    stable = _room_with_tag(level, "stable")
    training = _room_with_tag(level, "training")
    for room in (stable, training):
        rect = room.rect
        inside = [
            p for p in level.entities
            if rect.x <= p.x < rect.x + rect.width
            and rect.y <= p.y < rect.y + rect.height
        ]
        assert inside == [], (
            f"room {room.tags} should be empty in v1, got {inside}"
        )


# ---------------------------------------------------------------------------
# Game wiring: entering a settlement materializes the NPCs as ECS entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_settlement_spawns_merchant_entity(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    # Priest also carries a ShopInventory (holy water + potions) so
    # the merchant is identified as the one without TempleServices.
    merchants = [
        (eid, inv) for eid, inv in g.world.query("ShopInventory")
        if g.world.get_component(eid, "TempleServices") is None
    ]
    assert len(merchants) == 1
    _eid, shop_inv = merchants[0]
    assert shop_inv.stock, "ShopInventory should carry a non-empty stock"


@pytest.mark.asyncio
async def test_enter_settlement_spawns_priest_entity(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    hits = list(g.world.query("TempleServices"))
    assert len(hits) == 1
    _eid, svc = hits[0]
    assert "heal" in svc.services


@pytest.mark.asyncio
async def test_enter_settlement_spawns_hirable_henchman(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    hits = list(g.world.query("Henchman"))
    unhired = [(eid, h) for eid, h in hits if not h.hired]
    assert len(unhired) == 1, (
        f"exactly one unhired adventurer expected, got {unhired}"
    )


@pytest.mark.asyncio
async def test_re_enter_settlement_preserves_spent_merchant(tmp_path) -> None:
    """Floor cache must remember who we killed / hired so exiting
    and re-entering the same town doesn't resurrect the merchant.
    """
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    # Remove the merchant entity to simulate "killed / emptied".
    # Priest also has ShopInventory (holy water stock) so filter
    # to the entity that has no TempleServices.
    for eid, _ in list(g.world.query("ShopInventory")):
        if g.world.get_component(eid, "TempleServices") is None:
            g.world.destroy_entity(eid)
    await g.exit_dungeon_to_hex()
    await g.enter_hex_feature()
    remaining = [
        eid for eid, _ in g.world.query("ShopInventory")
        if g.world.get_component(eid, "TempleServices") is None
    ]
    assert remaining == [], (
        "merchant should stay gone after exit+re-entry"
    )
