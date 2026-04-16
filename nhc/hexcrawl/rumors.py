"""Overland rumor pool generator and consumption helper.

Rumors are short intel nuggets the player gathers at settlement
inns; they point at a named hex on the overland and, when acted
upon, reveal that hex on the fog-of-war map. Some of them are
deliberately misleading -- a ``truth=False`` rumor still reveals
its ``reveals`` coord but points at a non-feature tile, so the
player has travelled for nothing.

The actual settlement wiring (innkeeper NPC + "listen" action)
is a later UI pass; this module ships the pool generator and a
pop-and-apply helper so higher layers can plug in straight
away.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import HexFeatureType, HexWorld, Rumor


# Per-rumor text keys are resolved from the i18n layer by the
# narrator at dialogue time. v1 just carries opaque slugs --
# ``rumor.true_feature``/``rumor.false_lead`` bundle well enough
# for a placeholder rendering.
_TRUE_KEY = "rumor.true_feature"
_FALSE_KEY = "rumor.false_lead"


def _feature_coords(world: HexWorld) -> list[HexCoord]:
    """Return coords of every cell with a non-NONE feature,
    sorted for deterministic output under seeding."""
    return sorted(
        (c for c, cell in world.cells.items()
         if cell.feature is not HexFeatureType.NONE),
        key=lambda c: (c.q, c.r),
    )


def _plain_coords(world: HexWorld) -> list[HexCoord]:
    """Return coords of every cell WITHOUT a feature (candidates
    for ``truth=False`` rumors)."""
    return sorted(
        (c for c, cell in world.cells.items()
         if cell.feature is HexFeatureType.NONE),
        key=lambda c: (c.q, c.r),
    )


def generate_rumors(
    world: HexWorld,
    seed: int,
    count: int = 3,
) -> list[Rumor]:
    """Seed a ``count``-sized rumor pool from the current world.

    Half are true (pick a random feature hex) and half are false
    (pick a random non-feature hex). Odd ``count`` rounds toward
    one extra true rumor so the pool skews useful.

    The sort + seeded RNG guarantees the same ``(world_state,
    seed, count)`` tuple always produces the same rumor list --
    save games serialize the pool verbatim.
    """
    rng = random.Random(seed)
    features = _feature_coords(world)
    plains = _plain_coords(world)

    # Split count into (true_n, false_n), true-favoured on odd.
    true_n = (count + 1) // 2
    false_n = count - true_n

    rumors: list[Rumor] = []
    idx = 0
    # Sample WITH replacement -- small worlds may have fewer
    # feature hexes than rumors, and repeats of "a cave at (5,3)"
    # still read plausibly when both innkeepers repeat a story.
    for _ in range(true_n):
        if not features:
            break
        coord = rng.choice(features)
        rumors.append(Rumor(
            id=f"rumor_{seed}_{idx}",
            text_key=_TRUE_KEY,
            truth=True,
            reveals=coord,
        ))
        idx += 1
    for _ in range(false_n):
        if not plains:
            break
        coord = rng.choice(plains)
        rumors.append(Rumor(
            id=f"rumor_{seed}_{idx}",
            text_key=_FALSE_KEY,
            truth=False,
            reveals=coord,
        ))
        idx += 1

    return rumors


def generate_rumors_god_mode(
    world: HexWorld,
    seed: int,
    count: int = 3,
) -> list[Rumor]:
    """God-mode variant of :func:`generate_rumors`.

    Delegates to the regular generator, then flips every rumor's
    ``truth`` field to ``True`` so the player never gets a false
    lead. Cheaper than maintaining a parallel code path and keeps
    the coord-selection logic in lockstep.
    """
    rumors = generate_rumors(world, seed, count=count)
    for r in rumors:
        r.truth = True
    return rumors


def gather_rumor_at(
    world: HexWorld,
    rng: random.Random,
) -> Rumor | None:
    """Pop the next rumor off ``world.active_rumors`` and apply
    its reveal side-effect.

    Returns the popped :class:`Rumor` so the settlement UI can
    narrate it, or ``None`` when the pool is empty. The RNG
    parameter is reserved for future shuffle / pick-from-pool
    variants; v1 always consumes from the head of the list.
    """
    del rng  # reserved
    if not world.active_rumors:
        return None
    rumor = world.active_rumors.pop(0)
    if rumor.reveals is not None:
        world.reveal(rumor.reveals)
    return rumor
