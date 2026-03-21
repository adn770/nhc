"""Seeded RNG and dice roller.

Supports standard dice notation: "1d6", "2d4+2", "3d8-1".
"""

from __future__ import annotations

import random
import re

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def roll_dice(notation: str, rng: random.Random | None = None) -> int:
    """Roll dice using standard notation (e.g. '2d6+3').

    Returns the total result.
    """
    rng = rng or _default_rng
    match = DICE_RE.match(notation.strip())
    if not match:
        raise ValueError(f"Invalid dice notation: {notation!r}")

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    total = sum(rng.randint(1, sides) for _ in range(count)) + modifier
    return total


def roll_dice_max(notation: str) -> int:
    """Return the maximum possible roll for a notation."""
    match = DICE_RE.match(notation.strip())
    if not match:
        raise ValueError(f"Invalid dice notation: {notation!r}")

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    return count * sides + modifier


def d20(rng: random.Random | None = None) -> int:
    """Roll a single d20."""
    rng = rng or _default_rng
    return rng.randint(1, 20)


_default_rng = random.Random()


def set_seed(seed: int) -> None:
    """Set the global RNG seed for reproducibility."""
    _default_rng.seed(seed)


def get_rng() -> random.Random:
    """Get the global RNG instance."""
    return _default_rng
