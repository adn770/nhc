"""Encounter rolling and Fight / Flee / Talk choice shapes.

The overland step handler calls :func:`roll_encounter` for each
completed hex move. When it returns an :class:`Encounter` the
caller stages it on ``Game.pending_encounter`` and prompts the
player; the player's choice flows through
:meth:`Game.resolve_encounter`, which this module ships an enum
for.

The actual ECS dispatch lives in :mod:`nhc.core.game` because
the resolver needs access to the world / renderer / floor cache.
Keeping the data shapes here keeps the core game module a little
less entangled with hex-specific vocabulary.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from nhc.hexcrawl.encounter import DEFAULT_BIOME_POOLS
from nhc.hexcrawl.model import Biome


# Default chance per hex step that an encounter fires. Kept as a
# module constant (not per-biome) in v1 -- tunable per-biome
# rates land with proper wilderness-travel rules in a later
# milestone.
DEFAULT_ENCOUNTER_RATE = 0.2


class EncounterChoice(Enum):
    """Player response to an overland encounter prompt."""

    FIGHT = "fight"
    FLEE = "flee"
    TALK = "talk"


@dataclass
class Encounter:
    """A rolled-but-unresolved overland encounter.

    Held on :attr:`Game.pending_encounter` between the roll and
    the player's Fight / Flee / Talk choice.
    """

    biome: Biome
    creatures: list[str] = field(default_factory=list)


def roll_encounter(
    biome: Biome,
    rng: random.Random,
    encounter_rate: float = DEFAULT_ENCOUNTER_RATE,
) -> Encounter | None:
    """Roll an encounter check for a single hex step.

    Returns an :class:`Encounter` with a 2-4 creature pack drawn
    from :data:`DEFAULT_BIOME_POOLS` when the rate check passes,
    :data:`None` otherwise. The RNG is taken from the caller so
    the roll is reproducible under a seeded hex traversal.
    """
    if encounter_rate <= 0.0:
        return None
    if encounter_rate < 1.0 and rng.random() > encounter_rate:
        return None
    pool = DEFAULT_BIOME_POOLS.get(
        biome, DEFAULT_BIOME_POOLS[Biome.GREENLANDS],
    )
    size = rng.randint(2, 4)
    creatures = [rng.choice(pool) for _ in range(size)]
    return Encounter(biome=biome, creatures=creatures)
