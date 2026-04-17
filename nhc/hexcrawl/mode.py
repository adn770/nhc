"""Game mode, world type, and difficulty enums.

The game has two orthogonal axes:

* **WorldType** — hexcrawl (overland exploration) or dungeon
  (classic dungeon-only).
* **Difficulty** — easy (cheat death + double gold), medium
  (double gold), or survival (permadeath, normal gold).

:class:`GameMode` is the 2×3 cross product, kept as a single
enum for save-file serialization and CLI compatibility.
"""

from __future__ import annotations

import argparse
from enum import Enum


class WorldType(Enum):
    HEXCRAWL = "hexcrawl"
    DUNGEON = "dungeon"

    @classmethod
    def from_str(cls, name: str) -> "WorldType":
        try:
            return cls(name)
        except ValueError as exc:
            raise ValueError(
                f"unknown world type {name!r}; "
                f"expected one of {[w.value for w in cls]}"
            ) from exc


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    SURVIVAL = "survival"

    @classmethod
    def from_str(cls, name: str) -> "Difficulty":
        try:
            return cls(name)
        except ValueError as exc:
            raise ValueError(
                f"unknown difficulty {name!r}; "
                f"expected one of {[d.value for d in cls]}"
            ) from exc

    @property
    def allows_cheat_death(self) -> bool:
        return self is Difficulty.EASY

    @property
    def double_gold(self) -> bool:
        return self in (Difficulty.EASY, Difficulty.MEDIUM)


class GameMode(Enum):
    """Combined world-type + difficulty.

    Six values cover the full matrix. Legacy save values
    (``"dungeon"``, ``"hex-easy"``, ``"hex-survival"``) are
    accepted by :meth:`from_str` for backward compatibility.
    """

    # Hexcrawl modes
    HEX_EASY = "hex-easy"
    HEX_MEDIUM = "hex-medium"
    HEX_SURVIVAL = "hex-survival"
    # Dungeon modes
    DUNGEON_EASY = "dungeon-easy"
    DUNGEON_MEDIUM = "dungeon-medium"
    DUNGEON_SURVIVAL = "dungeon-survival"

    # Legacy alias — existing code references GameMode.DUNGEON
    DUNGEON = "dungeon-medium"

    @classmethod
    def default(cls) -> "GameMode":
        return cls.DUNGEON_MEDIUM

    @classmethod
    def from_str(cls, name: str) -> "GameMode":
        # Legacy mapping
        legacy = {
            "dungeon": cls.DUNGEON_MEDIUM,
            "hex-easy": cls.HEX_EASY,
            "hex-survival": cls.HEX_SURVIVAL,
        }
        if name in legacy:
            return legacy[name]
        try:
            return cls(name)
        except ValueError as exc:
            raise ValueError(
                f"unknown game mode {name!r}; "
                f"expected one of {[m.value for m in cls]}"
            ) from exc

    @classmethod
    def from_world_difficulty(
        cls,
        world: WorldType,
        difficulty: Difficulty,
    ) -> "GameMode":
        key = f"{world.value.split('crawl')[0] if world is WorldType.HEXCRAWL else world.value}-{difficulty.value}"
        # Build the lookup from (world, difficulty) pairs
        lookup = {
            (WorldType.HEXCRAWL, Difficulty.EASY): cls.HEX_EASY,
            (WorldType.HEXCRAWL, Difficulty.MEDIUM): cls.HEX_MEDIUM,
            (WorldType.HEXCRAWL, Difficulty.SURVIVAL): cls.HEX_SURVIVAL,
            (WorldType.DUNGEON, Difficulty.EASY): cls.DUNGEON_EASY,
            (WorldType.DUNGEON, Difficulty.MEDIUM): cls.DUNGEON_MEDIUM,
            (WorldType.DUNGEON, Difficulty.SURVIVAL): cls.DUNGEON_SURVIVAL,
        }
        return lookup[(world, difficulty)]

    @property
    def is_hex(self) -> bool:
        return self in (
            GameMode.HEX_EASY,
            GameMode.HEX_MEDIUM,
            GameMode.HEX_SURVIVAL,
        )

    @property
    def is_dungeon_only(self) -> bool:
        return not self.is_hex

    @property
    def allows_cheat_death(self) -> bool:
        return self.difficulty.allows_cheat_death

    @property
    def double_gold(self) -> bool:
        return self.difficulty.double_gold

    @property
    def world_type(self) -> WorldType:
        if self.is_hex:
            return WorldType.HEXCRAWL
        return WorldType.DUNGEON

    @property
    def difficulty(self) -> Difficulty:
        _map = {
            GameMode.HEX_EASY: Difficulty.EASY,
            GameMode.HEX_MEDIUM: Difficulty.MEDIUM,
            GameMode.HEX_SURVIVAL: Difficulty.SURVIVAL,
            GameMode.DUNGEON_EASY: Difficulty.EASY,
            GameMode.DUNGEON_MEDIUM: Difficulty.MEDIUM,
            GameMode.DUNGEON_SURVIVAL: Difficulty.SURVIVAL,
        }
        return _map[self]


# ---------------------------------------------------------------------------
# CLI plumbing -- shared by nhc.py and nhc_web.py
# ---------------------------------------------------------------------------


def add_world_arg(
    parser: argparse._ActionsContainer,
) -> argparse.Action:
    """Register the ``--world`` flag on ``parser``."""
    return parser.add_argument(
        "--world",
        choices=[m.value for m in GameMode],
        default=GameMode.default().value,
        help=(
            "World mode: dungeon-easy, dungeon-medium (default), "
            "dungeon-survival, hex-easy, hex-medium, hex-survival. "
            "Legacy values 'dungeon' and 'hex-easy'/'hex-survival' "
            "are also accepted."
        ),
    )


def gamemode_from_args(ns: argparse.Namespace) -> GameMode:
    """Translate the parsed ``--world`` string."""
    return GameMode.from_str(ns.world)
