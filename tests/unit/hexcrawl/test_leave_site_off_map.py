"""Off-map leave-site mechanic.

Walking off the edge of a walled-site surface (keep courtyard,
town streets, farm exterior) is treated as an intent to leave.
The game pops back to the overland, restores ``exploring_sub_hex``
to the feature_cell of the flower that was under exploration
when the player entered, and emits a narration message.

The mechanic is implemented via :class:`LeaveSiteAction` and a
:class:`LeaveSiteRequested` event; ``_intent_to_action`` routes
edge-exit moves onto the action instead of a :class:`BumpAction`.

Extended for sub-hex family sites in A2 and per-feature narration
in D3.
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


def _make_game(tmp_path, mode: GameMode = GameMode.HEX_EASY) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=mode.world_type,
        difficulty=mode.difficulty,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _regen_flower(g: Game, coord: HexCoord) -> None:
    """Regenerate the flower for ``coord`` so the newly stamped
    feature lands on a feature_cell."""
    from nhc.hexcrawl._flowers import generate_flower

    cell = g.hex_world.cells[coord]
    cell.flower = generate_flower(cell, g.hex_world.cells, seed=42)


def _attach_keep_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.KEEP
    cell.dungeon = DungeonRef(
        template="procedural:keep",
        depth=1,
        site_kind="keep",
    )
    _regen_flower(g, coord)
    g.hex_player_position = coord


def _attach_town_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.VILLAGE
    cell.dungeon = DungeonRef(
        template="procedural:settlement",
        depth=1,
        site_kind="town",
        size_class="village",
    )
    _regen_flower(g, coord)
    g.hex_player_position = coord


def _enter_flower(g: Game, coord: HexCoord) -> HexCoord:
    """Park the player inside the flower for ``coord`` and return the
    feature_cell sub-hex so tests can assert the exit restores it."""
    cell = g.hex_world.get_cell(coord)
    assert cell is not None and cell.flower is not None
    fc = cell.flower.feature_cell
    assert fc is not None
    g.hex_world.enter_flower(coord, fc)
    return fc


# ---------------------------------------------------------------------------
# LeaveSiteRequested / LeaveSiteAction wiring
# ---------------------------------------------------------------------------


def test_leave_site_event_exists() -> None:
    """``LeaveSiteRequested`` is a pub/sub Event the game subscribes
    to so the exit codepath is observable from tests."""
    from nhc.core.events import Event, LeaveSiteRequested

    assert issubclass(LeaveSiteRequested, Event)


def test_leave_site_action_importable() -> None:
    """``LeaveSiteAction`` lives next to the movement actions."""
    from nhc.core.actions import LeaveSiteAction
    from nhc.core.actions._base import Action

    assert issubclass(LeaveSiteAction, Action)


# ---------------------------------------------------------------------------
# _is_site_edge_exit helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_exit_helper_walled_site_off_map(tmp_path) -> None:
    """A move that would step off the Site.surface tilemap counts as
    an edge exit on a walled site."""
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    # Move the player to the top-left corner so stepping (-1, 0)
    # lands outside the tilemap.
    pos.x = 0
    pos.y = 0
    assert g._is_site_edge_exit(-1, 0) is True
    # An in-bounds step is not an edge exit.
    assert g._is_site_edge_exit(1, 0) is False


@pytest.mark.asyncio
async def test_edge_exit_helper_no_active_site(tmp_path) -> None:
    """Off-map moves from a cave floor (no active site) are not
    edge exits — the helper returns False so the bump collides
    with the wall the normal way."""
    g = _make_game(tmp_path)
    cell = g.hex_world.cells[HexCoord(0, 0)]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave", depth=1)
    g.hex_player_position = HexCoord(0, 0)
    await g.enter_hex_feature()
    assert g.level is not None
    # Force a position at the map edge so (-1, 0) is off-map.
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    pos.x = 0
    pos.y = 0
    assert g._active_site is None
    assert g._is_site_edge_exit(-1, 0) is False


@pytest.mark.asyncio
async def test_edge_exit_helper_building_interior(tmp_path) -> None:
    """Off-map from a building interior (level.building_id is set)
    is not an edge exit — the player must use a door."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g._active_site is not None
    building = g._active_site.buildings[0]
    # Find any walkable tile in the building ground floor.
    bx = by = 1
    for y, row in enumerate(building.ground.tiles):
        for x, tile in enumerate(row):
            if tile.terrain == Terrain.FLOOR:
                bx, by = x, y
                break
        if (bx, by) != (1, 1):
            break
    g._swap_to_building(building, bx, by)
    # Force to corner so an off-map step is available.
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    pos.x = 0
    pos.y = 0
    assert g._is_site_edge_exit(-1, 0) is False


# ---------------------------------------------------------------------------
# Intent routing: move → LeaveSiteAction at the edge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_move_routes_to_leave_site_at_edge(tmp_path) -> None:
    from nhc.core.actions import LeaveSiteAction

    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    pos.x = 0
    pos.y = 0
    action = g._intent_to_action("move", (-1, 0))
    assert isinstance(action, LeaveSiteAction)


@pytest.mark.asyncio
async def test_intent_move_is_bump_in_bounds(tmp_path) -> None:
    from nhc.core.actions import BumpAction

    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    # Use the tile the entry helper placed us on; stepping away
    # toward the interior must stay in-bounds.
    action = g._intent_to_action("move", (0, 1))
    assert isinstance(action, BumpAction)


# ---------------------------------------------------------------------------
# Full exit path: off-map move on a walled-site surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_map_move_exits_walled_site_to_flower(tmp_path) -> None:
    """Executing the edge-exit action drops the level, moves the
    player to the overland sentinel, and restores ``exploring_sub_hex``
    to the feature_cell of the flower the player entered from."""
    from nhc.core.actions import LeaveSiteAction

    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    fc = _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    pos.x = 0
    pos.y = 0
    action = LeaveSiteAction(actor=g.player_id, dx=-1, dy=0)
    assert await action.validate(g.world, g.level) is True
    await action.execute(g.world, g.level)
    # Give the event bus a chance to dispatch the subscribed
    # handler on the newly emitted LeaveSiteRequested.
    import asyncio
    from nhc.core.events import LeaveSiteRequested
    await g.event_bus.emit(LeaveSiteRequested(
        actor=g.player_id,
    ))
    # LeaveSiteAction already emits the request itself through
    # the event bus within execute(), so re-emitting above is
    # harmless (idempotent exit). Primary assertion: the level
    # is gone and the flower is restored.
    assert g.level is None
    assert g._active_site is None
    assert g.hex_world.exploring_sub_hex == fc
    assert pos.x == -1 and pos.y == -1 and pos.level_id == "overland"


@pytest.mark.asyncio
async def test_leave_site_emits_narration(tmp_path) -> None:
    """The action emits a MessageEvent with ``leave_site.exit``."""
    from nhc.core.events import MessageEvent
    from nhc.core.actions import LeaveSiteAction
    from nhc.i18n import t

    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    pos.x = 0
    pos.y = 0
    action = LeaveSiteAction(actor=g.player_id, dx=-1, dy=0)
    events = await action.execute(g.world, g.level)
    narr = [e for e in events if isinstance(e, MessageEvent)]
    assert narr, "expected a MessageEvent from LeaveSiteAction"
    assert narr[0].text == t("leave_site.exit")


# ---------------------------------------------------------------------------
# A2: sub-hex family sites exit via the same off-map edge
# ---------------------------------------------------------------------------


def _sub_hex_fixture(tmp_path, feature):
    """Game positioned inside a flower on a sub-hex carrying ``feature``,
    ready for ``enter_sub_hex_family_site``. Mirrors ``_flower_fixture``
    in ``test_sub_hex_entry.py`` to keep test setup close to the live
    code path."""
    from nhc.hexcrawl.model import MinorFeatureType

    g = _make_game(tmp_path)
    macro = g.hex_player_position
    cell = g.hex_world.get_cell(macro)
    pick = next(
        c for c, sc in cell.flower.cells.items()
        if sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HexFeatureType.NONE
    )
    cell.flower.cells[pick].minor_feature = feature
    g.hex_world.enter_flower(macro, pick)
    return g, macro, pick


@pytest.mark.asyncio
async def test_sub_hex_site_edge_exit_detected(tmp_path) -> None:
    """Off-map move from a sub-hex site surface counts as an edge
    exit. After wayside unified onto the site assembler, the path
    also parks a :class:`Site` wrapper on ``_active_site`` so the
    walled-site surface check fires alongside the sub-hex check."""
    from nhc.hexcrawl.model import Biome, MinorFeatureType
    from nhc.sites._types import SiteTier

    g, macro, sub = _sub_hex_fixture(tmp_path, MinorFeatureType.WELL)
    ok = await g.enter_sub_hex_family_site(
        macro, sub, "wayside", MinorFeatureType.WELL,
        SiteTier.SMALL, Biome.GREENLANDS,
    )
    assert ok is True
    assert g._active_site_sub == sub
    assert g._active_site is not None
    assert g._active_site.kind == "wayside"
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    pos.x = 0
    pos.y = 0
    assert g._is_site_edge_exit(-1, 0) is True


@pytest.mark.asyncio
async def test_sub_hex_exit_restores_entry_sub_hex(tmp_path) -> None:
    """Exiting a sub-hex family site restores ``exploring_sub_hex``
    to the sub-coord the player entered from, NOT the feature_cell."""
    from nhc.core.actions import LeaveSiteAction
    from nhc.hexcrawl.model import Biome, MinorFeatureType
    from nhc.sites._types import SiteTier

    g, macro, sub = _sub_hex_fixture(tmp_path, MinorFeatureType.WELL)
    # feature_cell for the flower should differ from ``sub`` (the
    # wayside well we stamped onto a non-feature ring-1 sub-hex).
    cell = g.hex_world.get_cell(macro)
    fc = cell.flower.feature_cell
    assert fc != sub, (
        "test precondition: sub must differ from the feature_cell"
    )
    await g.enter_sub_hex_family_site(
        macro, sub, "wayside", MinorFeatureType.WELL,
        SiteTier.SMALL, Biome.GREENLANDS,
    )
    pos = g.world.get_component(g.player_id, "Position")
    pos.x = 0
    pos.y = 0
    action = LeaveSiteAction(actor=g.player_id, dx=-1, dy=0)
    assert await action.validate(g.world, g.level) is True
    events = await action.execute(g.world, g.level)
    # LeaveSiteAction emits LeaveSiteRequested; dispatch it so the
    # Game exit handler runs.
    from nhc.core.events import LeaveSiteRequested
    for ev in events:
        if isinstance(ev, LeaveSiteRequested):
            await g.event_bus.emit(ev)
    assert g.level is None
    assert g._active_site_sub is None
    assert g.hex_world.exploring_sub_hex == sub


@pytest.mark.asyncio
async def test_sub_hex_re_entry_reuses_cached_level(tmp_path) -> None:
    """After leaving and re-entering, the sub-hex site returns the
    same cached Level instance (no regeneration)."""
    from nhc.hexcrawl.model import Biome, MinorFeatureType
    from nhc.sites._types import SiteTier

    g, macro, sub = _sub_hex_fixture(tmp_path, MinorFeatureType.WELL)
    await g.enter_sub_hex_family_site(
        macro, sub, "wayside", MinorFeatureType.WELL,
        SiteTier.SMALL, Biome.GREENLANDS,
    )
    first = g.level
    # Exit via the bus event.
    from nhc.core.events import LeaveSiteRequested
    await g.event_bus.emit(LeaveSiteRequested(actor=g.player_id))
    assert g.level is None
    # Re-enter.
    await g.enter_sub_hex_family_site(
        macro, sub, "wayside", MinorFeatureType.WELL,
        SiteTier.SMALL, Biome.GREENLANDS,
    )
    assert g.level is first


@pytest.mark.asyncio
async def test_sub_hex_active_sub_hex_cleared_on_exit(tmp_path) -> None:
    """After the exit fires, ``_active_site_sub`` is back to None."""
    from nhc.core.events import LeaveSiteRequested
    from nhc.hexcrawl.model import Biome, MinorFeatureType
    from nhc.sites._types import SiteTier

    g, macro, sub = _sub_hex_fixture(tmp_path, MinorFeatureType.WELL)
    await g.enter_sub_hex_family_site(
        macro, sub, "wayside", MinorFeatureType.WELL,
        SiteTier.SMALL, Biome.GREENLANDS,
    )
    assert g._active_site_sub == sub
    await g.event_bus.emit(LeaveSiteRequested(actor=g.player_id))
    assert g._active_site_sub is None


# ---------------------------------------------------------------------------
# D3: per-feature leave-site narration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leave_walled_town_uses_exit_town(tmp_path) -> None:
    """Leaving a town fires the ``leave_site.exit_town`` key."""
    from nhc.core.actions import LeaveSiteAction
    from nhc.core.events import MessageEvent
    from nhc.i18n import t

    g = _make_game(tmp_path)
    _attach_town_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = 0, 0
    action = g._intent_to_action("move", (-1, 0))
    assert isinstance(action, LeaveSiteAction)
    events = await action.execute(g.world, g.level)
    msgs = [e.text for e in events if isinstance(e, MessageEvent)]
    assert t("leave_site.exit_town") in msgs
    assert t("leave_site.exit_town") != "leave_site.exit_town", (
        "precondition: exit_town is localized"
    )


@pytest.mark.asyncio
async def test_leave_wayside_well_uses_exit_well(tmp_path) -> None:
    """Leaving a sub-hex wayside well fires ``leave_site.exit_well``."""
    from nhc.core.actions import LeaveSiteAction
    from nhc.core.events import MessageEvent
    from nhc.hexcrawl.model import MinorFeatureType
    from nhc.sites._types import SiteTier
    from nhc.i18n import t

    g = _make_game(tmp_path)
    # Build a flower with a WELL sub-hex.
    macro = g.hex_player_position
    cell = g.hex_world.get_cell(macro)
    from nhc.hexcrawl.model import HexFeatureType as HFT

    pick = next(
        c for c, sc in cell.flower.cells.items()
        if sc.minor_feature is MinorFeatureType.NONE
        and sc.major_feature is HFT.NONE
    )
    cell.flower.cells[pick].minor_feature = MinorFeatureType.WELL
    g.hex_world.enter_flower(macro, pick)
    from nhc.hexcrawl.model import Biome as B

    await g.enter_sub_hex_family_site(
        macro, pick, "wayside", MinorFeatureType.WELL,
        SiteTier.SMALL, B.GREENLANDS,
    )
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = 0, 0
    action = g._intent_to_action("move", (-1, 0))
    assert isinstance(action, LeaveSiteAction)
    events = await action.execute(g.world, g.level)
    msgs = [e.text for e in events if isinstance(e, MessageEvent)]
    assert t("leave_site.exit_well") in msgs
    assert t("leave_site.exit_well") != "leave_site.exit_well", (
        "precondition: exit_well is localized"
    )


@pytest.mark.asyncio
async def test_leave_site_falls_back_to_generic(tmp_path) -> None:
    """A LeaveSiteAction constructed without a narration hint emits
    the generic leave_site.exit message."""
    from nhc.core.actions import LeaveSiteAction
    from nhc.core.events import MessageEvent
    from nhc.i18n import t

    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    _enter_flower(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = 0, 0
    # Construct without going through _intent_to_action — no hint.
    action = LeaveSiteAction(actor=g.player_id, dx=-1, dy=0)
    events = await action.execute(g.world, g.level)
    msgs = [e.text for e in events if isinstance(e, MessageEvent)]
    assert t("leave_site.exit") in msgs


@pytest.mark.asyncio
async def test_leave_site_per_feature_locale_keys_present() -> None:
    """Per-feature leave-site keys exist in all three locales."""
    import yaml
    from pathlib import Path

    required = ("exit", "exit_town", "exit_keep", "exit_well")
    root = Path("nhc/i18n/locales")
    for lang in ("en", "ca", "es"):
        data = yaml.safe_load((root / f"{lang}.yaml").read_text())
        leave = data.get("leave_site", {})
        for key in required:
            assert leave.get(key), (
                f"missing leave_site.{key} in {lang}"
            )


@pytest.mark.asyncio
async def test_leave_site_locale_keys_present() -> None:
    """``leave_site.exit`` is defined in every locale."""
    import yaml
    from pathlib import Path

    root = Path("nhc/i18n/locales")
    for lang in ("en", "ca", "es"):
        data = yaml.safe_load((root / f"{lang}.yaml").read_text())
        assert "leave_site" in data, f"missing leave_site in {lang}"
        assert "exit" in data["leave_site"], (
            f"missing leave_site.exit in {lang}"
        )
        assert data["leave_site"]["exit"].strip(), (
            f"empty leave_site.exit in {lang}"
        )
