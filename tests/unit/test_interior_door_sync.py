"""Live-path ``sync_linked_door_state`` wiring (C1).

:func:`sync_linked_door_state` has unit-level coverage in
``test_interior_door_links``. These tests cover the *live* call
sites: :func:`nhc.core.game_ticks.tick_doors` and the
door-action event pipeline (open via bump / close via action).
Without this wiring, the two sides of an :class:`InteriorDoorLink`
drift out of sync during actual play.
"""

from __future__ import annotations

import asyncio

import pytest

from nhc.core.actions._interaction import CloseDoorAction
from nhc.core.ecs import World
from nhc.core.events import DoorClosed
from nhc.core.game_ticks import DOOR_CLOSE_TURNS, tick_doors
from nhc.dungeon.building import Building
from nhc.dungeon.model import Level, Rect, RectShape, Terrain, Tile
from nhc.sites._site import InteriorDoorLink, Site
from nhc.entities.components import Position
from nhc.i18n import init


class FakeRenderer:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def add_message(self, text: str) -> None:
        self.messages.append(text)


class FakeGame:
    """Minimal stand-in that exposes the attrs tick_doors + sync use."""

    def __init__(self, site: Site, world: World, turn: int = 0) -> None:
        self._active_site = site
        self.level = site.buildings[0].floors[0]
        self.world = world
        self.turn = turn
        self.renderer = FakeRenderer()


@pytest.fixture(autouse=True)
def _init_i18n() -> None:
    init("en")


def _building(bid: str, width: int = 8, height: int = 6) -> Building:
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    level = Level(
        id=f"{bid}_f0", name=f"{bid}_f0", depth=1,
        width=width, height=height, tiles=tiles,
        building_id=bid, floor_index=0,
    )
    return Building(
        id=bid, base_shape=RectShape(),
        base_rect=Rect(0, 0, width, height),
        floors=[level],
    )


def _linked_site() -> Site:
    a = _building("a")
    b = _building("b")
    a.floors[0].tiles[2][3].feature = "door_closed"
    b.floors[0].tiles[2][5].feature = "door_closed"
    site = Site(
        id="s", kind="town", buildings=[a, b],
        surface=Level.create_empty("surf", "surf", 0, 12, 8),
    )
    site.interior_door_links.append(InteriorDoorLink(
        from_building="a", to_building="b",
        floor=0, from_tile=(3, 2), to_tile=(5, 2),
    ))
    return site


class TestTickDoorsSyncsLinkedPair:
    def test_autoclose_syncs_mirrored_tile(self) -> None:
        site = _linked_site()
        a_tile = site.buildings[0].floors[0].tiles[2][3]
        b_tile = site.buildings[1].floors[0].tiles[2][5]
        for tile in (a_tile, b_tile):
            tile.feature = "door_open"
            tile.opened_at_turn = 0
        world = World()
        game = FakeGame(site, world, turn=DOOR_CLOSE_TURNS)

        tick_doors(game)

        assert a_tile.feature == "door_closed"
        assert a_tile.opened_at_turn is None
        assert b_tile.feature == "door_closed"
        assert b_tile.opened_at_turn is None

    def test_autoclose_works_without_active_site(self) -> None:
        """Legacy callers (dungeon levels) have ``_active_site=None``;
        tick_doors must not raise."""
        site = _linked_site()
        a_tile = site.buildings[0].floors[0].tiles[2][3]
        a_tile.feature = "door_open"
        a_tile.opened_at_turn = 0
        world = World()
        game = FakeGame(site, world, turn=DOOR_CLOSE_TURNS)
        game._active_site = None  # simulate dungeon mode

        tick_doors(game)

        assert a_tile.feature == "door_closed"


class TestCloseDoorActionEmitsEvent:
    def test_close_emits_door_closed_event(self) -> None:
        """CloseDoorAction must emit a DoorClosed event so the game
        loop can propagate the close to any linked pair."""
        site = _linked_site()
        a_floor = site.buildings[0].floors[0]
        a_tile = a_floor.tiles[2][3]
        a_tile.feature = "door_open"
        a_tile.opened_at_turn = 5

        world = World()
        actor = world.create_entity()
        world.add_component(
            actor, "Position",
            Position(x=2, y=2, level_id=a_floor.id),
        )

        action = CloseDoorAction(actor=actor, dx=1, dy=0)
        events = asyncio.run(action.execute(world, a_floor))

        close_events = [e for e in events if isinstance(e, DoorClosed)]
        assert len(close_events) == 1
        ev = close_events[0]
        assert (ev.x, ev.y) == (3, 2)
        assert ev.entity == actor
