"""Interactive henchman-pick dialog on dungeon entry.

When the player enters a non-settlement dungeon with more than
:data:`MAX_HENCHMEN` hired followers, the game asks which of
them to bring along via the renderer's ``show_selection_menu``.
The selected henchmen follow into the dungeon; the rest stay on
the overland tile as left-behinds (:attr:`Position.level_id`
stays ``"overland"``).

Settlements skip the dialog: towns are social hubs so everyone
comes inside. Parties that already fit under the cap skip it
too -- no point asking when all candidates come along anyway.
"""

from __future__ import annotations

import pytest

from nhc.core.actions._henchman import MAX_HENCHMEN
from nhc.core.game import Game
from nhc.entities.components import Henchman, Position
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.i18n import init as i18n_init


class _FakeClient:
    """Renderer stub with a programmable selection-menu queue."""

    game_mode = "classic"
    lang = "en"
    edge_doors = False

    def __init__(self) -> None:
        self.messages: list[str] = []
        # (title, options) tuples captured so tests can inspect
        # the sequence of prompts.
        self.menu_calls: list[tuple] = []
        # IDs the fake renderer returns in order of calls.
        self.menu_picks: list = []

    def show_selection_menu(self, title, options):
        self.menu_calls.append((title, list(options)))
        if not self.menu_picks:
            # Falling through with no scripted pick => default to
            # the first option so tests that don't prime the queue
            # still make progress.
            return options[0][0] if options else None
        return self.menu_picks.pop(0)

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


def _make_hex_game(tmp_path, client: _FakeClient) -> Game:
    g = Game(
        client=client,
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _stub_hired(g: Game, count: int) -> list[int]:
    """Create ``count`` already-hired henchmen on the overland."""
    ids: list[int] = []
    for _ in range(count):
        eid = g.world.create_entity({
            "Henchman": Henchman(
                level=1, hired=True, owner=g.player_id,
            ),
            "Position": Position(x=-1, y=-1, level_id="overland"),
        })
        ids.append(eid)
    return ids


def _seed_cave(g: Game):
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave")
    return coord


def _seed_town(g: Game):
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CITY
    cell.dungeon = DungeonRef(template="procedural:settlement")
    return coord


# ---------------------------------------------------------------------------
# Dialog fires when it matters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dungeon_entry_prompts_when_party_exceeds_cap(tmp_path) -> None:
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    hench_ids = _stub_hired(g, MAX_HENCHMEN + 2)
    # Pick the last two hired to come along (reverse of default
    # first-N behaviour so we can tell the dialog ran).
    client.menu_picks = [hench_ids[-1], hench_ids[-2]]

    _seed_cave(g)
    await g.enter_hex_feature()

    assert client.menu_calls, (
        "entering a cave with > MAX_HENCHMEN hired must open the "
        "selection dialog"
    )
    # Two prompts = MAX_HENCHMEN picks.
    assert len(client.menu_calls) == MAX_HENCHMEN
    # The two scripted picks are in the dungeon; the others are
    # left on overland.
    level_id = g.level.id
    in_dungeon = {
        eid for eid in hench_ids
        if g.world.get_component(eid, "Position").level_id == level_id
    }
    assert in_dungeon == {hench_ids[-1], hench_ids[-2]}
    left_behind = {
        eid for eid in hench_ids
        if g.world.get_component(eid, "Position").level_id == "overland"
    }
    assert left_behind == {hench_ids[0], hench_ids[1]}


# ---------------------------------------------------------------------------
# Skip when there's nothing to ask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dungeon_entry_skips_dialog_when_party_under_cap(tmp_path) -> None:
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    _stub_hired(g, MAX_HENCHMEN)  # exactly at cap
    _seed_cave(g)
    await g.enter_hex_feature()
    assert client.menu_calls == [], (
        "no prompt when all hired henchmen fit under the cap"
    )


@pytest.mark.asyncio
async def test_settlement_entry_skips_dialog(tmp_path) -> None:
    """Towns are a social hub -- everyone comes inside, no pick."""
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    _stub_hired(g, MAX_HENCHMEN + 2)
    _seed_town(g)
    await g.enter_hex_feature()
    assert client.menu_calls == [], (
        "settlement entry must not open the party dialog"
    )


@pytest.mark.asyncio
async def test_cancelled_dialog_falls_back_to_first_n(tmp_path) -> None:
    """If the player bails out (menu returns None), the game
    falls back to the deterministic first-MAX_HENCHMEN picker
    so entry never blocks."""
    client = _FakeClient()

    # Override the renderer to return None (cancel) for every
    # menu call.
    def cancel(_title, _options):
        client.menu_calls.append((_title, list(_options)))
        return None
    client.show_selection_menu = cancel

    g = _make_hex_game(tmp_path, client)
    hench_ids = _stub_hired(g, MAX_HENCHMEN + 1)
    _seed_cave(g)
    await g.enter_hex_feature()

    level_id = g.level.id
    in_dungeon = [
        eid for eid in hench_ids
        if g.world.get_component(eid, "Position").level_id == level_id
    ]
    assert len(in_dungeon) == MAX_HENCHMEN
    # Fallback uses sorted-by-eid order, so the first two hired
    # come along.
    assert in_dungeon == hench_ids[:MAX_HENCHMEN]
