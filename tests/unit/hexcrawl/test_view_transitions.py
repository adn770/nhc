"""End-to-end: ``Game.current_view`` follows a real play session.

``test_current_view`` pins the classifier's return value for hand-
built game shells -- unit-style, every branch covered. This test
complements it by driving an actual ``Game`` through the five
views via the public API (``enter_hex_feature``, flower mode,
``_swap_to_building``) and asserting the classifier agrees with
the gameplay-layer intent at each transition.

See ``design/views.md`` for the five-view definitions.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
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


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=GameMode.HEX_EASY.world_type,
        difficulty=GameMode.HEX_EASY.difficulty,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _attach_keep(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.KEEP
    cell.dungeon = DungeonRef(
        template="procedural:keep", depth=1, site_kind="keep",
    )
    g.hex_player_position = coord


@pytest.mark.asyncio
async def test_full_transition_hex_flower_site_structure_dungeon(
    tmp_path,
) -> None:
    """A single game sees all five views as the player walks:

    hex -> flower -> site -> structure -> dungeon

    and the classifier stays in lockstep with the gameplay state
    at every hop. If one of these transitions silently lands
    ``current_view`` on the wrong name, the client will route
    the state frame to the wrong handler and show the wrong
    toolbar -- the exact drift this test guards against.
    """
    g = _make_game(tmp_path)

    # 1) HEX_EASY initial state places the player inside the
    #    hub's sub-hex flower, so the classifier starts on
    #    "flower". This mirrors what the first render() call
    #    sees live.
    assert g.current_view() == "flower", (
        "freshly initialised HEX_EASY game should start in the "
        "hub's sub-hex flower"
    )

    # 2) Leaving flower drops us onto the macro hex map.
    g.hex_world.exit_flower()
    assert g.current_view() == "hex", (
        "after exit_flower() we're standing on the macro map"
    )

    # Re-enter flower to exercise that branch explicitly.
    start = g.hex_player_position
    g.hex_world.enter_flower(start, HexCoord(0, 0))
    assert g.current_view() == "flower"
    g.hex_world.exit_flower()
    assert g.current_view() == "hex"

    # 3) Attach a keep to the current hex and enter it -> site.
    _attach_keep(g, start)
    ok = await g.enter_hex_feature()
    assert ok
    site = g._active_site
    assert site is not None
    assert g.level is site.surface
    assert g.current_view() == "site", (
        "standing on a keep's surface level is the canonical "
        "'site' view"
    )

    # 4) Swap into the keep's first building -> structure.
    assert site.buildings, "keep assembler must produce at least one building"
    building = site.buildings[0]
    # Pick any interior tile; the helper takes (bx, by) but the
    # classifier only reads level.building_id, so exact landing
    # doesn't matter for this assertion.
    g._swap_to_building(building, building.ground.width // 2, building.ground.height // 2)
    assert g.current_view() == "structure", (
        "a level with building_id set is always 'structure' "
        "regardless of how we got there"
    )

    # 5) Simulate entering a dungeon from the building by
    #    clearing building_id on the active level. That's the
    #    shape a descent stair produces: same active_site, same
    #    game, but the level is no longer inside a building.
    g.level.building_id = None
    assert g.current_view() == "dungeon", (
        "level without building_id and not equal to site.surface "
        "classifies as 'dungeon', covering both standalone and "
        "site-descent dungeons"
    )

    # 6) Back up the hierarchy: flip building_id back -> structure,
    #    swap to surface -> site, exit to overland -> hex.
    g.level.building_id = building.id
    assert g.current_view() == "structure"
    g.level = site.surface
    assert g.current_view() == "site"
    g.level = None
    g._active_site = None
    assert g.current_view() == "hex"


@pytest.mark.asyncio
async def test_reentering_walled_site_keeps_site_classifier(
    tmp_path,
) -> None:
    """Regression: re-entering a keep/town via the floor cache
    must still land the classifier on ``"site"``.

    Production debug bundle (2026-04-24) showed a second
    ``enter_hex_feature`` on the same town producing
    ``state_dungeon`` frames instead of ``state_site``. Root
    cause: ``_enter_walled_site``'s cache-hit branch
    (``game.py`` ~line 1192) reassigns ``self.level`` but
    never re-populates ``self._active_site``. The classifier
    reads ``_active_site is None`` and falls through its final
    branch -> ``"dungeon"``. Downstream consequences were bigger
    than "wrong view label": the tile-layer dispatcher uses
    ``site.building_doors`` to traverse into buildings, so
    cache-hit re-entries silently broke building entry.

    The fix ships with this test; both the cold-cache and
    warm-cache paths must return ``"site"``.
    """
    g = _make_game(tmp_path)
    start = g.hex_player_position
    assert g.hex_world.exploring_hex is not None
    _attach_keep(g, start)

    # First entry: cold cache -- assembler builds the Site from
    # scratch and stamps _active_site. This leg has always worked.
    ok = await g.enter_hex_feature()
    assert ok
    assert g.current_view() == "site", (
        "first entry should classify as site -- if this fails "
        "the cold-cache path is also broken, not just the cache "
        "hit"
    )
    first_site = g._active_site
    assert first_site is not None

    # Leave the site back to the flower view. _active_site is
    # cleared by _exit_to_overland_sync.
    g._exit_to_overland_sync()
    assert g._active_site is None

    # Second entry: warm cache -- the surface level is pulled
    # straight out of _floor_cache. _active_site must be
    # restored too, otherwise current_view() classifies the
    # surface level as "dungeon".
    ok2 = await g.enter_hex_feature()
    assert ok2
    assert g._active_site is not None, (
        "warm-cache re-entry left _active_site unset; the "
        "classifier can't distinguish the site surface from a "
        "standalone dungeon level and every dispatcher that "
        "reads _active_site (building-door traversal, etc) "
        "breaks too"
    )
    assert g.current_view() == "site"


@pytest.mark.asyncio
async def test_leave_site_intent_returns_player_to_flower(
    tmp_path,
) -> None:
    """Regression: pressing Leave (**L**) on a site surface must
    transition the player back to the flower view of the macro
    hex the site lives on -- not strand them on the site.

    Production debug bundle (2026-04-24) showed the intent
    ``flower_exit`` arriving on the server while the player was
    on a site surface, followed immediately by another
    ``state_site`` frame: the tile-layer input dispatcher
    silently dropped the intent because ``flower_exit`` is only
    wired in the flower-mode input path. The fix introduces a
    distinct ``leave_site`` intent handled in the tile-layer
    dispatcher, which calls ``_exit_to_overland_sync`` -- the
    same helper that powers site-edge-exit, so the post-leave
    state ends up in the flower view (the path the player came
    in on) rather than the bare overland map.
    """
    from unittest.mock import AsyncMock

    g = _make_game(tmp_path)
    # HEX_EASY places the player inside the hub's flower, so
    # ``hex_world.exploring_hex`` is already set -- that's the
    # signal ``_exit_to_overland_sync`` reads to route back to
    # flower instead of the bare overland. We preserve that
    # state and just attach a keep to the current hex before
    # entering it.
    start = g.hex_player_position
    assert g.hex_world.exploring_hex is not None, (
        "fixture precondition: entering a feature from flower "
        "mode must preserve exploring_hex so the return path "
        "knows where to restore the player to"
    )
    _attach_keep(g, start)
    ok = await g.enter_hex_feature()
    assert ok
    assert g.current_view() == "site", (
        "fixture should land the player on a keep surface "
        "before exercising the leave_site dispatch"
    )

    # Fire the intent through the real dispatcher. Mock
    # renderer.get_input to return the intent we want; the real
    # implementation would have picked this up from a Shift-L
    # keypress via input.js.
    g.renderer.get_input = AsyncMock(return_value=("leave_site", None))
    actions = await g._get_classic_actions()
    assert actions == [], (
        "leave_site is handled directly in the dispatcher and "
        "should short-circuit with an empty action list"
    )
    assert g.current_view() == "flower", (
        "pressing Leave (L) on the site must drop us back in "
        "the flower view, not leave the site state unchanged"
    )
    # Sanity: the level and active site are cleared, just like
    # the equivalent site-edge-exit flow.
    assert g.level is None
    assert g._active_site is None
