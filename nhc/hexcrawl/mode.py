"""GameMode enum for the overland hexcrawl mode.

Three modes coexist with the existing dungeon crawler:

* ``DUNGEON`` -- the original dungeon-only experience. Default.
* ``HEX_EASY`` -- hexcrawl wrapper, hub-start, cheat-death allowed.
* ``HEX_SURVIVAL`` -- hexcrawl wrapper, random start, permadeath only.

Selected via the ``--world`` CLI flag (see ``nhc.py`` /
``nhc_web.py``). Note that this is orthogonal to the pre-existing
``--mode {typed,classic}`` flag which controls input style.
"""

from __future__ import annotations

import argparse
from enum import Enum


class GameMode(Enum):
    DUNGEON = "dungeon"
    HEX_EASY = "hex-easy"
    HEX_SURVIVAL = "hex-survival"

    @classmethod
    def default(cls) -> "GameMode":
        return cls.DUNGEON

    @classmethod
    def from_str(cls, name: str) -> "GameMode":
        try:
            return cls(name)
        except ValueError as exc:
            raise ValueError(
                f"unknown game mode {name!r}; "
                f"expected one of {[m.value for m in cls]}"
            ) from exc

    @property
    def is_hex(self) -> bool:
        return self in (GameMode.HEX_EASY, GameMode.HEX_SURVIVAL)

    @property
    def is_dungeon_only(self) -> bool:
        return self is GameMode.DUNGEON

    @property
    def allows_cheat_death(self) -> bool:
        """Easy mode offers the cheat-death dialog. Survival is
        permadeath only. Dungeon mode keeps its existing behaviour
        (this property is consulted only by the hex-mode death
        handler)."""
        return self is GameMode.HEX_EASY


# ---------------------------------------------------------------------------
# CLI plumbing -- shared by nhc.py and nhc_web.py
# ---------------------------------------------------------------------------


def add_world_arg(
    parser: argparse._ActionsContainer,
) -> argparse.Action:
    """Register the ``--world`` flag on ``parser``.

    ``parser`` may be an :class:`argparse.ArgumentParser` or an
    argument group (both share the same ``add_argument`` interface).
    Default is ``"dungeon"`` so existing CLI invocations behave
    exactly as before.
    """
    return parser.add_argument(
        "--world",
        choices=[m.value for m in GameMode],
        default=GameMode.default().value,
        help=(
            "World mode: dungeon (default, classic dungeon-only), "
            "hex-easy (overland with hub start), or hex-survival "
            "(overland with random start). Orthogonal to --mode."
        ),
    )


def gamemode_from_args(ns: argparse.Namespace) -> GameMode:
    """Translate the parsed ``--world`` string into a :class:`GameMode`."""
    return GameMode.from_str(ns.world)
