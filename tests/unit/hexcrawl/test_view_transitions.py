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
