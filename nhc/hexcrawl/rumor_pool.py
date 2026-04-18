"""Rumor pool seeding, consumption, and language refresh.

Centralizes the logic for populating and consuming
HexWorld.active_rumors via the TableRegistry subsystem.
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
    for truth=False rumors)."""
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
    return result.text, RumorSource(
        table_id=table_id,
        entry_id=result.entry_id,
        context=ctx,
        lang=lang,
    )


def _generate_rumors(
    world: HexWorld,
    seed: int,
    count: int,
    lang: str,
) -> list[Rumor]:
    """Build a count-sized rumor list from the current world.

    Half are true (pick a random feature hex) and half are false
    (pick a random non-feature hex). Odd count rounds toward one
    extra true rumor so the pool skews useful.
    """
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


def generate_rumors(
    world: HexWorld,
    seed: int,
    count: int = 3,
    lang: str | None = None,
) -> list[Rumor]:
    """Generate a rumor list (public API for tests and callers)."""
    if lang is None:
        lang = current_lang()
    return _generate_rumors(world, seed, count, lang)


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
    """Legacy API: pop + reveal. Prefer consume_rumor()."""
    del rng
    return consume_rumor(world)


def seed_rumor_pool(
    world: HexWorld,
    seed: int,
    *,
    lang: str | None = None,
    count: int = 3,
    god_mode: bool = False,
) -> None:
    """Generate rumors via TableRegistry and set the pool."""
    if lang is None:
        lang = current_lang()
    rumors = _generate_rumors(world, seed, count, lang)
    if god_mode:
        for r in rumors:
            r.truth = True
    world.active_rumors = rumors


def top_up_rumor_pool(
    world: HexWorld,
    seed: int,
    *,
    lang: str | None = None,
    count: int = 3,
    god_mode: bool = False,
) -> None:
    """Append fresh rumors onto an existing pool."""
    if lang is None:
        lang = current_lang()
    fresh = _generate_rumors(world, seed, count, lang)
    if god_mode:
        for r in fresh:
            r.truth = True
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
    return rumor


def refresh_rumor_language(
    rumor: Rumor,
    new_lang: str,
) -> Rumor:
    """Re-render a rumor's text in a different language.

    Requires rumor.source to be set (table-backed rumor).
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
    return Rumor(
        id=rumor.id,
        text=result.text,
        truth=rumor.truth,
        reveals=rumor.reveals,
        source=RumorSource(
            table_id=rumor.source.table_id,
            entry_id=rumor.source.entry_id,
            context=rumor.source.context,
            lang=new_lang,
        ),
    )
