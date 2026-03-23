"""Potion identification system.

Each game session shuffles potion colors so players can't memorize
which color maps to which effect.  Potions are identified by quaffing
them — once identified, all potions of that type show their real name.
"""

from __future__ import annotations

import random
from typing import Any

from nhc.i18n import t

# All potion item IDs in the game
POTION_IDS = [
    "healing_potion",
    "potion_strength",
    "potion_frost",
    "potion_invisibility",
    "potion_levitation",
    "potion_liquid_flame",
    "potion_mind_vision",
    "potion_paralytic_gas",
    "potion_purification",
]

# Appearance descriptors — shuffled and assigned to potion types.
# Each entry is: (i18n_key_suffix, glyph_color)
POTION_APPEARANCES = [
    ("bubbly_red", "red"),
    ("murky_green", "green"),
    ("shimmering_blue", "bright_blue"),
    ("thick_yellow", "yellow"),
    ("fizzy_violet", "magenta"),
    ("dark_brown", "yellow"),
    ("glowing_white", "bright_white"),
    ("oily_black", "bright_black"),
    ("sparkling_cyan", "bright_cyan"),
]


class PotionKnowledge:
    """Tracks which potion types have been identified this game."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.identified: set[str] = set()
        # Shuffle appearances and assign to potion IDs
        appearances = list(POTION_APPEARANCES)
        if rng:
            rng.shuffle(appearances)
        else:
            random.shuffle(appearances)
        self._appearance: dict[str, tuple[str, str]] = {}
        for i, pid in enumerate(POTION_IDS):
            self._appearance[pid] = appearances[i % len(appearances)]

    def is_identified(self, potion_id: str) -> bool:
        return potion_id in self.identified

    def identify(self, potion_id: str) -> None:
        """Mark a potion type as identified."""
        self.identified.add(potion_id)

    def appearance(self, potion_id: str) -> tuple[str, str]:
        """Return (i18n_key_suffix, glyph_color) for an unidentified potion."""
        return self._appearance.get(potion_id, ("bubbly_red", "red"))

    def display_name(self, potion_id: str) -> str:
        """Return the name to show for a potion (real or color-based)."""
        if potion_id in self.identified:
            return t(f"items.{potion_id}.name")
        key_suffix, _ = self.appearance(potion_id)
        return t(f"potion_appearance.{key_suffix}")

    def display_short(self, potion_id: str) -> str:
        """Return the short description (real or color-based)."""
        if potion_id in self.identified:
            return t(f"items.{potion_id}.short")
        key_suffix, _ = self.appearance(potion_id)
        return t(f"potion_appearance.{key_suffix}_short")

    def glyph_color(self, potion_id: str) -> str:
        """Return the display color for this potion."""
        if potion_id in self.identified:
            # Use the real color from the factory (not available here,
            # so return the appearance color — it's fine)
            pass
        _, color = self.appearance(potion_id)
        return color
