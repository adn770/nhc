"""Autosave/restore system using pickle + zlib compression.

Saves complete game state (all floors, entities, identification,
messages) in a compact binary format.  Atomic writes via .tmp +
os.replace prevent corruption on crash.
"""

from __future__ import annotations

import logging
import os
import pickle
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nhc.core.game import Game

logger = logging.getLogger(__name__)

AUTOSAVE_DIR = Path.home() / ".nhc" / "saves"
AUTOSAVE_PATH = AUTOSAVE_DIR / "autosave.nhc"
AUTOSAVE_VERSION = 1


def has_autosave() -> bool:
    """Check if an autosave file exists."""
    return AUTOSAVE_PATH.exists()


def delete_autosave() -> None:
    """Remove autosave file (on death or victory)."""
    try:
        AUTOSAVE_PATH.unlink(missing_ok=True)
        logger.info("Autosave deleted")
    except OSError:
        pass


def autosave(game: "Game") -> None:
    """Save complete game state to disk (fast binary format)."""
    try:
        payload = _build_payload(game)
        data = zlib.compress(pickle.dumps(payload, protocol=5), level=1)

        AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = AUTOSAVE_PATH.with_suffix(".tmp")
        tmp_path.write_bytes(data)
        os.replace(str(tmp_path), str(AUTOSAVE_PATH))

        logger.debug("Autosave: %d bytes, turn %d", len(data), game.turn)
    except Exception:
        logger.error("Autosave failed", exc_info=True)


def auto_restore(game: "Game") -> bool:
    """Restore game state from autosave. Returns True if successful."""
    if not has_autosave():
        return False

    try:
        data = AUTOSAVE_PATH.read_bytes()
        payload = pickle.loads(zlib.decompress(data))

        if payload.get("version") != AUTOSAVE_VERSION:
            logger.warning("Autosave version mismatch, deleting")
            delete_autosave()
            return False

        _restore_payload(game, payload)
        logger.info("Restored autosave: turn %d, depth %d",
                     game.turn, game.level.depth if game.level else 0)
        return True

    except Exception:
        logger.error("Autosave restore failed, deleting", exc_info=True)
        delete_autosave()
        return False


def _build_payload(game: "Game") -> dict[str, Any]:
    """Extract complete game state into a picklable dict."""
    world = game.world

    return {
        "version": AUTOSAVE_VERSION,
        "turn": game.turn,
        "player_id": game.player_id,
        "god_mode": game.god_mode,
        "mode": game.mode,

        # ECS world
        "world_next_id": world._next_id,
        "world_entities": set(world._entities),
        "world_components": {
            comp_type: dict(store)
            for comp_type, store in world._components.items()
        },

        # Current level
        "level": game.level,

        # Floor cache (all visited floors)
        "floor_cache": dict(game._floor_cache),

        # Identification state
        "knowledge_identified": set(game._knowledge.identified)
            if game._knowledge else set(),
        "knowledge_appearance": dict(game._knowledge._appearance)
            if game._knowledge else {},

        # Character sheet (for intro/narration)
        "character": game._character,

        # Messages
        "messages": list(game.renderer.messages),

        # Seen creatures
        "seen_creatures": set(game._seen_creatures),
    }


def _restore_payload(game: "Game", payload: dict[str, Any]) -> None:
    """Rebuild game state from a saved payload."""
    from nhc.entities.registry import EntityRegistry
    from nhc.rules.identification import ItemKnowledge

    EntityRegistry.discover_all()

    # Core state
    game.turn = payload["turn"]
    game.player_id = payload["player_id"]
    game.god_mode = payload.get("god_mode", False)
    game.mode = payload.get("mode", "classic")
    game.renderer.game_mode = game.mode

    # ECS world
    world = game.world
    world._next_id = payload["world_next_id"]
    world._entities = payload["world_entities"]
    world._components = payload["world_components"]

    # Level
    game.level = payload["level"]

    # Floor cache
    game._floor_cache = payload.get("floor_cache", {})

    # Identification
    knowledge = ItemKnowledge.__new__(ItemKnowledge)
    knowledge.identified = payload.get("knowledge_identified", set())
    knowledge._appearance = payload.get("knowledge_appearance", {})
    game._knowledge = knowledge

    # Character sheet
    game._character = payload.get("character")

    # Messages
    game.renderer.messages = payload.get("messages", [])

    # Seen creatures
    game._seen_creatures = payload.get("seen_creatures", set())

    # Resubscribe event handlers (they're method refs, not persisted)
    from nhc.core.events import (
        CreatureDied, GameWon, ItemUsed, LevelEntered, MessageEvent,
    )
    game.event_bus.subscribe(MessageEvent, game._on_message)
    game.event_bus.subscribe(GameWon, game._on_game_won)
    game.event_bus.subscribe(CreatureDied, game._on_creature_died)
    game.event_bus.subscribe(LevelEntered, game._on_level_entered)
    game.event_bus.subscribe(ItemUsed, game._on_item_used)

    # Recompute FOV
    game._update_fov()

    # Initialize renderer
    game.renderer.initialize()
    game.running = True
