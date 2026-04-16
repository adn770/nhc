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


# Fallback chance per hex step when no biome-specific rate is
# configured. Per-biome tuning in :data:`BIOME_ENCOUNTER_RATES`
# usually wins -- this constant only kicks in if the biome is
# missing from both the pack override and the default table.
DEFAULT_ENCOUNTER_RATE = 0.2


# Per-biome encounter rates. Tuned so frontier biomes feel more
# dangerous than the safe heartlands, without making any biome
# either trivial or a constant fight. A settlement-bound player
# rarely gets jumped; a mountain pass is a gamble every step.
BIOME_ENCOUNTER_RATES: dict[Biome, float] = {
    Biome.GREENLANDS: 0.10,   # safest (usually near settlements)
    Biome.DRYLANDS:   0.15,
    Biome.FOREST:     0.25,
    Biome.SANDLANDS:  0.25,
    Biome.ICELANDS:   0.30,
    Biome.MOUNTAIN:   0.35,   # packs + terrain = nasty
    Biome.DEADLANDS:  0.40,   # undead wastes; highest rate
    # Hills sit between forest and mountain. Marsh is wet
    # ambush country; swamp is strictly worse -- denser cover
    # and heavier undead presence push it past mountain.
    Biome.HILLS:      0.22,
    Biome.MARSH:      0.28,
    Biome.SWAMP:      0.33,
    Biome.WATER:      0.00,   # impassable; rate is moot
}


def rate_for_biome(
    biome: Biome,
    override: dict[Biome, float] | None = None,
) -> float:
    """Look up the encounter rate for ``biome``.

    ``override`` (e.g. from a pack manifest) wins when it
    contains the biome; otherwise the packaged
    :data:`BIOME_ENCOUNTER_RATES` default applies; and
    :data:`DEFAULT_ENCOUNTER_RATE` is the final fallback for a
    biome missing from both tables.
    """
    if override is not None and biome in override:
        return override[biome]
    return BIOME_ENCOUNTER_RATES.get(biome, DEFAULT_ENCOUNTER_RATE)


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
