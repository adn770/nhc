"""Combat AI and morale checks.

Implements the Knave / Basic D&D morale rule: roll 2d6, and the
creature holds its courage when the result is less than or equal
to its morale score. Higher morale = harder to break.
"""

from __future__ import annotations

import random

from nhc.utils.rng import roll_dice


def morale_check(morale: int, rng: random.Random | None = None) -> bool:
    """Roll 2d6 against a morale score.

    Returns True if the creature passes (2d6 ≤ morale) and holds,
    False if it fails and breaks.

    With morale ≥ 12 the check is auto-pass; with morale ≤ 1 it
    is auto-fail. These boundaries match Basic D&D where a morale
    of 12 is fearless and a morale of 2 is the lowest assignable
    score still capable of (rare) success.
    """
    if morale >= 12:
        return True
    if morale <= 1:
        return False
    return roll_dice("2d6", rng) <= morale
