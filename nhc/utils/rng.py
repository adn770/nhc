"""Seeded RNG and dice roller.

Supports standard dice notation: "1d6", "2d4+2", "3d8-1".

The default RNG is thread-local so concurrent game sessions
(each in its own thread) don't interfere with each other's
random state.
"""

from __future__ import annotations

import random
import re
import threading

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def roll_dice(notation: str, rng: random.Random | None = None) -> int:
    """Roll dice using standard notation (e.g. '2d6+3').

    Returns the total result.
    """
    rng = rng or get_rng()
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
    rng = rng or get_rng()
    return rng.randint(1, 20)


_local = threading.local()


def _get_state() -> tuple[random.Random, int | None]:
    """Return the thread-local (rng, seed) pair, creating if needed."""
    rng = getattr(_local, "rng", None)
    if rng is None:
        rng = random.Random()
        _local.rng = rng
        _local.seed = None
    return rng, getattr(_local, "seed", None)


def set_seed(seed: int) -> None:
    """Set the thread-local RNG seed for reproducibility."""
    rng, _ = _get_state()
    _local.seed = seed
    rng.seed(seed)


def get_seed() -> int:
    """Return the current seed. Auto-generates one if not set."""
    rng, seed = _get_state()
    if seed is None:
        seed = random.Random().randint(0, 2**31 - 1)
        _local.seed = seed
        rng.seed(seed)
    return seed


def get_rng() -> random.Random:
    """Get the thread-local RNG instance."""
    rng, _ = _get_state()
    return rng
