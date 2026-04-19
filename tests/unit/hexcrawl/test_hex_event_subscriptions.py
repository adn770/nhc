"""Hex-mode Game must wire event handlers during initialize.

The dungeon-only branch of Game.initialize previously ran the
subscribe block; hex mode returned early and left the EventBus
without any handlers. That meant descending stairs inside a cave
fired LevelEntered into a void and the floor transition never
happened. Subscribing the shared handlers in both modes closes
the gap.
"""

from __future__ import annotations

import pytest

from nhc.core.events import (
    CreatureDied, GameWon, ItemUsed, LevelEntered, MessageEvent,
    VisualEffect,
)
from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.i18n import init as i18n_init


class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False

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
        style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _is_subscribed(g: Game, event_type: type, handler) -> bool:
    return handler in g.event_bus._handlers.get(event_type, [])


def test_hex_mode_subscribes_level_entered(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    assert _is_subscribed(g, LevelEntered, g._on_level_entered)


def test_hex_mode_subscribes_all_core_handlers(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    pairs = [
        (MessageEvent, g._on_message),
        (GameWon, g._on_game_won),
        (CreatureDied, g._on_creature_died),
        (LevelEntered, g._on_level_entered),
        (ItemUsed, g._on_item_used),
        (VisualEffect, g._on_visual_effect),
    ]
    for event_type, handler in pairs:
        assert _is_subscribed(g, event_type, handler), (
            f"{event_type.__name__} not subscribed in hex mode"
        )


@pytest.mark.asyncio
async def test_hex_mode_level_entered_fires_handler_via_emit(
    tmp_path,
) -> None:
    """Emitting LevelEntered in hex mode must invoke the handler."""
    g = _make_hex_game(tmp_path)
    # Attach a cave so enter_hex_feature can produce a level
    cell = g.hex_world.cells[HexCoord(0, 0)]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(
        template="procedural:cave", depth=1,
    )
    g.hex_player_position = HexCoord(0, 0)
    await g.enter_hex_feature()
    assert g.level is not None
    start_depth = g.level.depth

    # Emit a LevelEntered through the bus. If the subscribe
    # worked, _on_level_entered will run and change the level.
    await g.event_bus.emit(LevelEntered(
        entity=g.player_id, level_id=g.level.id,
        depth=start_depth + 1,
    ))
    assert g.level.depth == start_depth + 1
