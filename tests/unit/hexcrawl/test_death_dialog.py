"""Mode-aware death handling.

hex-easy players get a choice on death: permadeath (game over) or
cheat death (respawn at the last hub, lose gold / equipment /
henchmen, advance the clock by one day). hex-survival skips the
dialog -- permadeath only. Dungeon mode keeps its existing flow
and never sees cheat death.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.components import (
    Description, Inventory, Player, Renderable,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
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


def _make_game(mode: GameMode, tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=mode,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _give_loot(g: Game, gold: int = 50) -> list[int]:
    """Equip the hex-mode player with gold + two inventory items.
    Returns the item entity IDs."""
    player = g.world.get_component(g.player_id, "Player")
    assert player is not None
    player.gold = gold
    inv = g.world.get_component(g.player_id, "Inventory")
    assert inv is not None
    item_ids: list[int] = []
    for name in ("sword", "torch"):
        iid = g.world.create_entity({
            "Description": Description(name=name),
            "Renderable": Renderable(glyph="/", color="#c0c0c0"),
        })
        inv.slots.append(iid)
        item_ids.append(iid)
    return item_ids


# ---------------------------------------------------------------------------
# allows_cheat_death predicate
# ---------------------------------------------------------------------------


def test_cheat_death_allowed_in_hex_easy(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    assert g.allows_cheat_death_now()


def test_cheat_death_blocked_in_hex_survival(tmp_path) -> None:
    g = _make_game(GameMode.HEX_SURVIVAL, tmp_path)
    assert not g.allows_cheat_death_now()


def test_cheat_death_blocked_in_dungeon_mode(tmp_path) -> None:
    g = Game(
        client=_FakeClient(), backend=None, game_mode="classic",
        world_mode=GameMode.DUNGEON, save_dir=tmp_path, seed=1,
    )
    g.initialize(generate=True)
    assert not g.allows_cheat_death_now()


# ---------------------------------------------------------------------------
# cheat_death side effects
# ---------------------------------------------------------------------------


def test_cheat_death_zeros_gold(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    _give_loot(g, gold=250)
    g.cheat_death()
    player = g.world.get_component(g.player_id, "Player")
    assert player.gold == 0


def test_cheat_death_strips_inventory(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    items = _give_loot(g)
    g.cheat_death()
    inv = g.world.get_component(g.player_id, "Inventory")
    assert inv.slots == []
    # Dropped items are gone from the world too.
    for iid in items:
        assert iid not in g.world._entities


def test_cheat_death_disbands_expedition_party(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    # Fake henchman entities joined the party.
    h1 = g.world.create_entity({
        "Description": Description(name="Hench A"),
    })
    h2 = g.world.create_entity({
        "Description": Description(name="Hench B"),
    })
    g.hex_world.expedition_party = [h1, h2]
    g.cheat_death()
    assert g.hex_world.expedition_party == []
    assert h1 not in g.world._entities
    assert h2 not in g.world._entities


def test_cheat_death_teleports_to_last_hub(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    # Walk away from the hub so the teleport is observable.
    g.hex_player_position = HexCoord(
        g.hex_world.last_hub.q + 1, g.hex_world.last_hub.r,
    )
    g.cheat_death()
    assert g.hex_player_position == g.hex_world.last_hub


def test_cheat_death_advances_day_clock_by_one(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    day0 = g.hex_world.day
    time0 = g.hex_world.time
    g.cheat_death()
    # +1 full day: same time of day, day number +1.
    assert g.hex_world.day == day0 + 1
    assert g.hex_world.time is time0


def test_cheat_death_preserves_world_state(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    g.hex_world.revealed.add(HexCoord(3, 3))
    g.hex_world.cleared.add(HexCoord(4, 4))
    g.hex_world.visited.add(HexCoord(5, 5))
    g.cheat_death()
    assert HexCoord(3, 3) in g.hex_world.revealed
    assert HexCoord(4, 4) in g.hex_world.cleared
    assert HexCoord(5, 5) in g.hex_world.visited


def test_cheat_death_restores_player_hp(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    hp = g.world.get_component(g.player_id, "Health")
    hp.current = 0  # "killed"
    g.cheat_death()
    assert hp.current == hp.maximum


def test_cheat_death_raises_in_survival_mode(tmp_path) -> None:
    g = _make_game(GameMode.HEX_SURVIVAL, tmp_path)
    with pytest.raises(RuntimeError):
        g.cheat_death()


# ---------------------------------------------------------------------------
# hex-easy players have a real Player entity
# ---------------------------------------------------------------------------


def test_hex_easy_creates_player_entity(tmp_path) -> None:
    g = _make_game(GameMode.HEX_EASY, tmp_path)
    assert g.player_id != -1
    assert g.world.get_component(g.player_id, "Player") is not None
    assert g.world.get_component(g.player_id, "Inventory") is not None
