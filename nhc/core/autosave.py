"""Autosave/restore system using pickle + zlib compression.

Saves complete game state (all floors, entities, identification,
messages) in a compact binary format.  Atomic writes via .tmp +
os.replace prevent corruption on crash.
"""

from __future__ import annotations

import logging
import os
import pickle
import threading
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nhc.core.events import (
    CreatureDied, GameWon, ItemUsed, LevelEntered, MessageEvent,
)
from nhc.entities.registry import EntityRegistry
from nhc.rules.identification import ItemKnowledge

if TYPE_CHECKING:
    from nhc.core.game import Game

logger = logging.getLogger(__name__)

_save_lock = threading.Lock()

_DEFAULT_DIR = Path.home() / ".nhc" / "saves"
_DEFAULT_PATH = _DEFAULT_DIR / "autosave.nhc"
AUTOSAVE_VERSION = 1


def _resolve(save_dir: Path | None) -> tuple[Path, Path]:
    """Return (directory, file) for the autosave location."""
    if save_dir is not None:
        return save_dir, save_dir / "autosave.nhc"
    return _DEFAULT_DIR, _DEFAULT_PATH


def has_autosave(save_dir: Path | None = None) -> bool:
    """Check if an autosave file exists."""
    _, path = _resolve(save_dir)
    exists = path.exists()
    logger.debug("has_autosave: %s (path=%s)", exists, path)
    return exists


def delete_autosave(save_dir: Path | None = None) -> None:
    """Remove autosave file and cached SVGs (on death, victory, or reset)."""
    save_dir_resolved, path = _resolve(save_dir)
    try:
        existed = path.exists()
        path.unlink(missing_ok=True)
        # Also purge SVG cache so a fresh game doesn't load stale maps
        for name in ("floor.svg", "hatch.svg"):
            (save_dir_resolved / name).unlink(missing_ok=True)
        logger.info("Autosave delete: existed=%s, path=%s", existed, path)
    except OSError:
        logger.error("Autosave delete FAILED", exc_info=True)


def autosave(
    game: "Game", save_dir: Path | None = None, *, blocking: bool = True,
) -> None:
    """Save complete game state to disk (fast binary format).

    Payload is snapshotted on the calling thread; pickle, compress,
    and write run in a background thread when *blocking* is False.
    """
    save_dir_resolved, save_path = _resolve(save_dir)
    try:
        payload = _build_payload(game)
        turn = game.turn
    except Exception:
        logger.error("Autosave payload build failed", exc_info=True)
        return

    def _write():
        try:
            with _save_lock:
                data = zlib.compress(
                    pickle.dumps(payload, protocol=5), level=1)
                save_dir_resolved.mkdir(parents=True, exist_ok=True)
                tmp_path = save_path.with_suffix(".tmp")
                tmp_path.write_bytes(data)
                os.replace(str(tmp_path), str(save_path))
            logger.debug("Autosave: %d bytes, turn %d", len(data), turn)
        except Exception:
            logger.error("Autosave failed", exc_info=True)

    if blocking:
        _write()
    else:
        threading.Thread(target=_write, daemon=True).start()


def auto_restore(game: "Game", save_dir: Path | None = None) -> bool:
    """Restore game state from autosave. Returns True if successful."""
    if not has_autosave(save_dir):
        return False

    _, save_path = _resolve(save_dir)
    try:
        data = save_path.read_bytes()
        payload = pickle.loads(zlib.decompress(data))

        if payload.get("version") != AUTOSAVE_VERSION:
            logger.warning("Autosave version mismatch, deleting")
            delete_autosave(save_dir)
            return False

        _restore_payload(game, payload)
        logger.info("Restored autosave: turn %d, depth %d",
                     game.turn, game.level.depth if game.level else 0)
        return True

    except Exception:
        logger.error("Autosave restore failed, deleting", exc_info=True)
        delete_autosave(save_dir)
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

        # SVG cache (floor SVGs keyed by depth)
        "svg_cache": dict(game._svg_cache),

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

    # SVG cache
    game._svg_cache = payload.get("svg_cache", {})

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


# ── SVG cache ───────────────────────────────────────────────

def save_svg_cache(
    floor_svg: str, hatch_svg: str, save_dir: Path | None = None,
) -> None:
    """Cache floor and hatch SVG alongside the autosave."""
    d, _ = _resolve(save_dir)
    d.mkdir(parents=True, exist_ok=True)
    try:
        (d / "floor.svg").write_text(floor_svg, encoding="utf-8")
        (d / "hatch.svg").write_text(hatch_svg, encoding="utf-8")
        logger.debug("SVG cache saved: floor=%d hatch=%d bytes",
                     len(floor_svg), len(hatch_svg))
    except Exception:
        logger.error("SVG cache save failed", exc_info=True)


def load_svg_cache(
    save_dir: Path | None = None,
) -> tuple[str, str] | None:
    """Load cached floor and hatch SVG.  Returns (floor, hatch) or None."""
    d, _ = _resolve(save_dir)
    floor_path = d / "floor.svg"
    hatch_path = d / "hatch.svg"
    if floor_path.exists() and hatch_path.exists():
        try:
            floor = floor_path.read_text(encoding="utf-8")
            hatch = hatch_path.read_text(encoding="utf-8")
            logger.debug("SVG cache loaded: floor=%d hatch=%d bytes",
                         len(floor), len(hatch))
            return floor, hatch
        except Exception:
            logger.error("SVG cache load failed", exc_info=True)
    return None
