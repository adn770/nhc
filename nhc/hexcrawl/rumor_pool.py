"""Rumor pool seeding and consumption.

Centralizes the logic for populating and consuming
HexWorld.active_rumors. Callers use seed_rumor_pool()
instead of calling generate_rumors directly.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.model import HexWorld, Rumor
from nhc.tables.effects import apply_effect
from nhc.tables.types import TableEffect


def seed_rumor_pool(
    world: HexWorld,
    seed: int,
    *,
    lang: str,
    count: int = 3,
    god_mode: bool = False,
) -> None:
    """Generate rumors via TableRegistry and append to the pool."""
    from nhc.hexcrawl.rumors import (
        generate_rumors,
        generate_rumors_god_mode,
    )

    gen = generate_rumors_god_mode if god_mode else generate_rumors
    world.active_rumors = gen(world, seed=seed, count=count, lang=lang)


def top_up_rumor_pool(
    world: HexWorld,
    seed: int,
    *,
    lang: str,
    count: int = 3,
    god_mode: bool = False,
) -> None:
    """Append fresh rumors onto an existing pool."""
    from nhc.hexcrawl.rumors import (
        generate_rumors,
        generate_rumors_god_mode,
    )

    gen = generate_rumors_god_mode if god_mode else generate_rumors
    fresh = gen(world, seed=seed, count=count, lang=lang)
    world.active_rumors.extend(fresh)


def consume_rumor(world: HexWorld) -> Rumor | None:
    """Pop the next rumor and apply its reveal effect.

    Returns the popped Rumor so the UI can narrate it, or None
    when the pool is empty.
    """
    if not world.active_rumors:
        return None
    rumor = world.active_rumors.pop(0)
    if rumor.reveals is not None:
        world.reveal(rumor.reveals)
    if rumor.source and rumor.source.context:
        effect = TableEffect(
            kind="reveal_hex",
            payload={"source": "context"},
        )
        # Effect already applied via world.reveal above;
        # structured effect dispatch is available for future use.
    return rumor
