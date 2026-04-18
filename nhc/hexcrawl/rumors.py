"""Overland rumor pool generator and consumption helper.

Rumors are short intel nuggets the player gathers at settlement
inns; they point at a named hex on the overland and, when acted
upon, reveal that hex on the fog-of-war map. Some of them are
deliberately misleading -- a ``truth=False`` rumor still reveals
its ``reveals`` coord but points at a non-feature tile, so the
player has travelled for nothing.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import HexFeatureType, HexWorld, Rumor, RumorSource
from nhc.i18n import current_lang
from nhc.tables.registry import TableRegistry

_TRUE_TABLE = "rumor.true_feature"
_FALSE_TABLE = "rumor.false_lead"


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


def _roll_rumor_text(
    table_id: str,
    rng: random.Random,
    coord: HexCoord,
    lang: str,
) -> tuple[str, RumorSource]:
    """Roll a rumor table and return (rendered_text, source)."""
    ctx = {"q": coord.q, "r": coord.r}
    registry = TableRegistry.get_or_load(lang)
    result = registry.roll(table_id, rng=rng, context=ctx)
    source = RumorSource(
        table_id=table_id,
        entry_id=result.entry_id,
        context=ctx,
        lang=lang,
    )
    return result.text, source


def generate_rumors(
    world: HexWorld,
    seed: int,
    count: int = 3,
    lang: str | None = None,
) -> list[Rumor]:
    """Seed a ``count``-sized rumor pool from the current world.

    Half are true (pick a random feature hex) and half are false
    (pick a random non-feature hex). Odd ``count`` rounds toward
    one extra true rumor so the pool skews useful.

    The sort + seeded RNG guarantees the same ``(world_state,
    seed, count)`` tuple always produces the same rumor list --
    save games serialize the pool verbatim.
    """
    if lang is None:
        lang = current_lang()
    rng = random.Random(seed)
    features = _feature_coords(world)
    plains = _plain_coords(world)

    true_n = (count + 1) // 2
    false_n = count - true_n

    rumors: list[Rumor] = []
    idx = 0
    for _ in range(true_n):
        if not features:
            break
        coord = rng.choice(features)
        text, source = _roll_rumor_text(
            _TRUE_TABLE, rng, coord, lang,
        )
        rumors.append(Rumor(
            id=f"rumor_{seed}_{idx}",
            text=text,
            truth=True,
            reveals=coord,
            source=source,
        ))
        idx += 1
    for _ in range(false_n):
        if not plains:
            break
        coord = rng.choice(plains)
        text, source = _roll_rumor_text(
            _FALSE_TABLE, rng, coord, lang,
        )
        rumors.append(Rumor(
            id=f"rumor_{seed}_{idx}",
            text=text,
            truth=False,
            reveals=coord,
            source=source,
        ))
        idx += 1

    return rumors


def generate_rumors_god_mode(
    world: HexWorld,
    seed: int,
    count: int = 3,
    lang: str | None = None,
) -> list[Rumor]:
    """God-mode variant: all rumors are truthful."""
    rumors = generate_rumors(world, seed, count=count, lang=lang)
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
    narrate it, or ``None`` when the pool is empty.
    """
    del rng  # reserved
    if not world.active_rumors:
        return None
    rumor = world.active_rumors.pop(0)
    if rumor.reveals is not None:
        world.reveal(rumor.reveals)
    return rumor


def refresh_rumor_language(
    rumor: Rumor,
    new_lang: str,
) -> Rumor:
    """Re-render a rumor's text in a different language.

    Requires ``rumor.source`` to be set (table-backed rumor).
    Returns a new Rumor with updated text and source lang.
    Legacy rumors without source are returned unchanged.
    """
    if rumor.source is None:
        return rumor
    registry = TableRegistry.get_or_load(new_lang)
    result = registry.render(
        rumor.source.table_id,
        entry_id=rumor.source.entry_id,
        context=rumor.source.context,
    )
    new_source = RumorSource(
        table_id=rumor.source.table_id,
        entry_id=rumor.source.entry_id,
        context=rumor.source.context,
        lang=new_lang,
    )
    return Rumor(
        id=rumor.id,
        text=result.text,
        truth=rumor.truth,
        reveals=rumor.reveals,
        source=new_source,
    )
