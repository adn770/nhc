"""Game-level tests for surface <-> building door crossings.

When the player is on a site's surface level and walks across a
door registered in ``site.building_doors``, the engine swaps the
active level to the target building's ground floor (and vice
versa). Mansions additionally support building <-> building
crossings through ``site.interior_doors`` for the shared
perimeter doors between adjacent mansion buildings.

These tests drive the ``Game._maybe_traverse_building_door``
handler by moving the player onto the relevant door tile and
asserting that ``game.level`` swaps to the expected target.
"""

from __future__ import annotations

import pytest

from nhc.core.actions import WaitAction
from nhc.core.actions._movement import MoveAction
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
    from tests.unit.hexcrawl.test_enter_exit import _make_game as mk
    return mk(tmp_path, mode)


def _attach_keep_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.KEEP
    cell.dungeon = DungeonRef(
        template="procedural:keep",
        depth=1,
        site_kind="keep",
    )
    g.hex_player_position = coord


def _attach_mansion_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.MANSION
    cell.dungeon = DungeonRef(
        template="procedural:mansion",
        depth=1,
        site_kind="mansion",
    )
    g.hex_player_position = coord


def _place_player(g: Game, x: int, y: int) -> None:
    pos = g.world.get_component(g.player_id, "Position")
    pos.x = x
    pos.y = y
    pos.level_id = g.level.id


async def _move_onto(g: Game, tx: int, ty: int) -> None:
    """Teleport the player next to (tx, ty) then step onto it via
    MoveAction so the door-crossing handler fires."""
    pos = g.world.get_component(g.player_id, "Position")
    pos.x = tx - 1
    pos.y = ty
    pos.level_id = g.level.id
    action = MoveAction(actor=g.player_id, dx=1, dy=0)
    await g._resolve(action)


@pytest.mark.asyncio
async def test_keep_surface_to_building_via_door(tmp_path) -> None:
    """Player on keep surface crosses a building entry door and
    the active level switches to that building's ground floor."""
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    site = g._active_site
    surface = site.surface
    assert g.level is surface
    # Pick any registered surface door entry.
    (sx, sy), (bid, bx, by) = next(iter(site.building_doors.items()))
    # Position the player on the door tile and pre-open the door
    # (the assembler places `door_closed`; the Game-side handler
    # fires on a stepped cross, so we directly trigger the swap
    # via an attempt onto an adjacent tile that opens and crosses
    # the door in one go).
    surface.tiles[sy][sx].feature = "door_open"
    _place_player(g, sx, sy)
    # Dispatch the swap by calling the handler directly.
    g._maybe_traverse_building_door()
    assert g.level is not surface
    assert g.level.building_id == bid
    pos = g.world.get_component(g.player_id, "Position")
    assert (pos.x, pos.y) == (bx, by)


@pytest.mark.asyncio
async def test_building_to_surface_via_reverse_door(tmp_path) -> None:
    """Player on a keep building ground floor crosses the same
    perimeter door back to the surface."""
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    site = g._active_site
    surface = site.surface
    (sx, sy), (bid, bx, by) = next(iter(site.building_doors.items()))
    target_building = next(b for b in site.buildings if b.id == bid)
    g.level = target_building.ground
    # Mark the building-side door open and stand on it.
    g.level.tiles[by][bx].feature = "door_open"
    _place_player(g, bx, by)
    g._maybe_traverse_building_door()
    assert g.level is surface
    pos = g.world.get_component(g.player_id, "Position")
    assert (pos.x, pos.y) == (sx, sy)


@pytest.mark.asyncio
async def test_mansion_shared_interior_door(tmp_path) -> None:
    """Player on a mansion building crosses an interior shared
    door and the active level switches to the sibling building."""
    g = _make_game(tmp_path)
    _attach_mansion_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    site = g._active_site
    if not site.interior_doors:
        pytest.skip("mansion seed produced no interior doors")
    (fid, fx, fy), (tid, tx, ty) = next(
        iter(site.interior_doors.items()),
    )
    source = next(b for b in site.buildings if b.id == fid)
    target = next(b for b in site.buildings if b.id == tid)
    g.level = source.ground
    g.level.tiles[fy][fx].feature = "door_open"
    _place_player(g, fx, fy)
    g._maybe_traverse_building_door()
    assert g.level is target.ground
    pos = g.world.get_component(g.player_id, "Position")
    assert (pos.x, pos.y) == (tx, ty)


@pytest.mark.asyncio
async def test_closed_door_does_not_trigger_crossing(tmp_path) -> None:
    """Door crossing only fires on an already-open door -- the
    bump-to-open step should precede the cross."""
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    site = g._active_site
    surface = site.surface
    (sx, sy), _ = next(iter(site.building_doors.items()))
    # Door remains closed.
    surface.tiles[sy][sx].feature = "door_closed"
    _place_player(g, sx, sy)
    g._maybe_traverse_building_door()
    assert g.level is surface


@pytest.mark.asyncio
async def test_resolve_does_not_call_door_traversal_hook(tmp_path) -> None:
    """Regression: ``_resolve`` must not invoke the door-traversal
    hook. Each player turn fires several ``_resolve`` calls
    (player action, haste, every creature action, henchman
    catch-up). The hook reads the *player's* position regardless
    of the actor, so if it runs at the end of every ``_resolve``,
    the first call correctly swaps the player out of a building
    onto the paired surface door tile -- and the second call
    (from a neighbouring villager's action) sees the player on a
    surface door and swaps them right back in. The player sees a
    flip-flop at every building entrance on any surface with
    NPCs. Fix: keep the hook a member of ``Game`` (so existing
    tests and typed-mode callers can still trigger it on demand)
    but make the per-turn player-action path the sole trigger.
    """
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    site = g._active_site
    surface = site.surface
    # Stand the player on a surface door tile in the exact state
    # left by a just-completed building exit.
    (sx, sy), _ = next(iter(site.building_doors.items()))
    surface.tiles[sy][sx].feature = "door_open"
    g.level = surface
    _place_player(g, sx, sy)
    # Spy on the hook.
    calls = []
    original_hook = g._maybe_traverse_building_door

    def _spy() -> None:
        calls.append(True)
        original_hook()

    g._maybe_traverse_building_door = _spy  # type: ignore[method-assign]
    # Resolve any action through ``_resolve`` -- before the fix
    # this triggered the hook; after the fix it must not.
    await g._resolve(WaitAction(actor=g.player_id))
    assert calls == [], (
        "_resolve called _maybe_traverse_building_door; move the "
        "hook into the per-turn player-action path instead."
    )
    # And the player must still be on the surface (no sneaky
    # implicit traversal slipped in via some other path).
    assert g.level is surface
