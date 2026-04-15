"""Autosave/restore system using pickle + zlib compression.

Saves complete game state (all floors, entities, identification,
messages) in a compact binary format.  Atomic writes via .tmp +
os.replace prevent corruption on crash.

Autosaves are wrapped in an HMAC-SHA256 signature so
``pickle.loads`` is only ever applied to bytes this process wrote.
The key lives next to the save file (``.autosave.key``, mode
0600) and is created lazily on the first save.  Legacy unsigned
saves are rejected by default; set
``NHC_AUTOSAVE_ALLOW_LEGACY=1`` to permit a one-time migration.
"""

from __future__ import annotations

import hmac
import logging
import os
import pickle
import secrets
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

# Binary framing: signed payloads start with this 4-byte magic
# followed by a 32-byte HMAC-SHA256 digest, then the compressed
# pickle bytes.  Anything else is legacy / corrupt.
_MAGIC = b"NHC1"
_DIGEST_LEN = 32
_HEADER_LEN = len(_MAGIC) + _DIGEST_LEN

# Name of the per-save-dir HMAC key file.  Each player has its own
# key so a leak of one save does not taint others, and so the
# keys live on the same persistent volume as the saves (simplifies
# backup / migration).
_KEY_FILENAME = ".autosave.key"

# Per-process cache of loaded HMAC keys, keyed on the resolved key
# file path.  Autosave runs every few turns; re-reading 32 bytes
# from disk each time is wasted I/O, and the key never changes
# without the path itself changing.
_key_cache: dict[Path, bytes] = {}
_key_cache_lock = threading.Lock()


def _resolve(save_dir: Path | None) -> tuple[Path, Path]:
    """Return (directory, file) for the autosave location."""
    if save_dir is not None:
        return save_dir, save_dir / "autosave.nhc"
    return _DEFAULT_DIR, _DEFAULT_PATH


def _key_path(save_dir: Path | None) -> Path:
    """Return the path of the HMAC key file for *save_dir*."""
    dir_, _ = _resolve(save_dir)
    return dir_ / _KEY_FILENAME


def _load_or_create_key(save_dir: Path | None) -> bytes:
    """Read the HMAC key for *save_dir*, creating it if missing.

    The key file is 32 random bytes written with mode 0600 and an
    atomic replace so interrupted writes never leave a partial
    key on disk.  The result is cached per-path for the life of
    the process so the autosave hot path does not re-read the key
    on every turn.
    """
    path = _key_path(save_dir)
    with _key_cache_lock:
        cached = _key_cache.get(path)
        if cached is not None:
            return cached
    try:
        key = path.read_bytes()
    except FileNotFoundError:
        key = b""
    if len(key) == _DIGEST_LEN:
        with _key_cache_lock:
            _key_cache[path] = key
        return key
    if key:
        logger.warning(
            "Autosave key %s has unexpected length %d — "
            "generating a fresh key; any existing save will be "
            "unreadable and removed.",
            path, len(key),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    new_key = secrets.token_bytes(_DIGEST_LEN)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Use os.open so we can set permissions before any bytes land
    # on disk (write_bytes would briefly leave a world-readable
    # file).
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, 0o600)
    try:
        os.write(fd, new_key)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))
    with _key_cache_lock:
        _key_cache[path] = new_key
    return new_key


def _sign(key: bytes, compressed: bytes) -> bytes:
    """Prepend the magic + HMAC-SHA256 digest to *compressed*."""
    digest = hmac.new(key, compressed, "sha256").digest()
    return _MAGIC + digest + compressed


def _verify_and_strip(key: bytes, blob: bytes) -> bytes | None:
    """Return the compressed payload if *blob* is a valid signed
    save, ``None`` if *blob* is not in the signed format.

    Raises :class:`ValueError` on signature mismatch — the caller
    is responsible for deleting corrupt/tampered files.
    """
    if not blob.startswith(_MAGIC):
        return None
    if len(blob) < _HEADER_LEN:
        raise ValueError("autosave too short to be valid")
    digest = blob[len(_MAGIC):_HEADER_LEN]
    compressed = blob[_HEADER_LEN:]
    expected = hmac.new(key, compressed, "sha256").digest()
    if not hmac.compare_digest(digest, expected):
        raise ValueError("autosave signature mismatch")
    return compressed


def _legacy_loads_allowed() -> bool:
    """Return True if legacy (unsigned) autosaves may be loaded.

    Defaults to False.  Operators can flip this once during the
    migration window from the unsigned format.
    """
    value = os.environ.get("NHC_AUTOSAVE_ALLOW_LEGACY", "").strip()
    return value.lower() in {"1", "true", "yes"}


def read_autosave_payload(path: Path) -> dict[str, Any] | None:
    """Decompress and unpickle an autosave file for inspection.

    Verifies the HMAC signature when a key file sits next to the
    save (the normal case for saves produced after the signing
    rollout).  Returns ``None`` for missing files, signature
    mismatches, or legacy-format saves the current environment
    is not allowed to read.

    This is the forensic entry point for the debug tooling; game
    code should keep using :func:`auto_restore` which performs a
    full restore cycle and deletes tampered files.
    """
    if not path.exists():
        return None
    raw = path.read_bytes()
    save_dir = path.parent
    if (save_dir / _KEY_FILENAME).exists():
        key = _load_or_create_key(save_dir)
        try:
            compressed = _verify_and_strip(key, raw)
        except ValueError:
            logger.warning(
                "read_autosave_payload: signature mismatch at %s",
                path,
            )
            return None
    else:
        compressed = None
    if compressed is None:
        if not _legacy_loads_allowed():
            return None
        compressed = raw
    return pickle.loads(zlib.decompress(compressed))


def has_autosave(save_dir: Path | None = None) -> bool:
    """Check if an autosave file exists."""
    _, path = _resolve(save_dir)
    return path.exists()


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
                save_dir_resolved.mkdir(parents=True, exist_ok=True)
                key = _load_or_create_key(save_dir)
                compressed = zlib.compress(
                    pickle.dumps(payload, protocol=5), level=1,
                )
                data = _sign(key, compressed)
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
        raw = save_path.read_bytes()
        key = _load_or_create_key(save_dir)
        try:
            compressed = _verify_and_strip(key, raw)
        except ValueError:
            logger.error(
                "Autosave signature mismatch — refusing to load",
            )
            delete_autosave(save_dir)
            return False

        if compressed is None:
            # Legacy unsigned save — the payload is raw
            # zlib(pickle).  Never execute pickle on untrusted
            # bytes unless the operator has explicitly opted in.
            if not _legacy_loads_allowed():
                logger.error(
                    "Unsigned legacy autosave refused "
                    "(set NHC_AUTOSAVE_ALLOW_LEGACY=1 to migrate)",
                )
                delete_autosave(save_dir)
                return False
            compressed = raw
            logger.warning(
                "Loading unsigned legacy autosave — next save "
                "will be signed.",
            )

        payload = pickle.loads(zlib.decompress(compressed))

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
        "seed": game.seed,
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
    game.seed = payload.get("seed", game.seed)
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
