"""Post-generation transforms for structural templates.

Each transform is a pure function that modifies a Level in
place. Transforms are applied after the base generator runs
but before room types and terrain.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level


def add_cart_tracks(level: Level, rng: random.Random) -> None:
    """Add mine cart track markings along corridors."""
    pass  # Phase 2 implementation


def narrow_corridors(level: Level, rng: random.Random) -> None:
    """Narrow corridor passages for crypt-style layouts."""
    pass  # Phase 2 implementation


def add_battlements(level: Level, rng: random.Random) -> None:
    """Add battlement decorations to keep outer walls."""
    pass  # Phase 3 implementation


def add_gate(level: Level, rng: random.Random) -> None:
    """Add fortified gate entry points."""
    pass  # Phase 3 implementation


def add_ore_deposits(level: Level, rng: random.Random) -> None:
    """Place ore resource markers in mine corridors."""
    pass  # Phase 2 implementation


TRANSFORM_REGISTRY: dict[str, callable] = {
    "add_cart_tracks": add_cart_tracks,
    "narrow_corridors": narrow_corridors,
    "add_battlements": add_battlements,
    "add_gate": add_gate,
    "add_ore_deposits": add_ore_deposits,
}
