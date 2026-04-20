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
_WILDERNESS_TABLE = "rumor.wilderness"

_SETTLEMENT_FEATURES = frozenset({
    HexFeatureType.VILLAGE,
    HexFeatureType.CITY,
    HexFeatureType.COMMUNITY,
    HexFeatureType.KEEP,
})


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
        variant=result.variant_index,
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


def has_settlement_in_reach(
    world: HexWorld,
    macro: HexCoord,
    radius: int = 3,
) -> bool:
    """True when any cell within ``radius`` hexes of ``macro``
    carries a settlement-class feature (VILLAGE / CITY / COMMUNITY
    / KEEP).

    Used by the wilderness-signpost fallback to decide whether a
    bumped signpost should seed a generic nature-travel pool or
    collapse to the town come-back-later beat.
    """
    from nhc.hexcrawl.coords import distance as hex_distance

    for coord, cell in world.cells.items():
        if cell.feature not in _SETTLEMENT_FEATURES:
            continue
        if hex_distance(coord, macro) <= radius:
            return True
    return False


def seed_wilderness_rumor_pool(
    world: HexWorld,
    world_seed: int,
    macro_coord: HexCoord,
    *,
    lang: str | None = None,
    count: int = 2,
) -> list[Rumor]:
    """Append ``count`` wilderness-pool rumours to ``active_rumors``.

    Entries are drawn from the ``rumor.wilderness`` table with a
    per-hex RNG seeded off ``(world_seed, macro_coord)`` so every
    visit to the same macro sees the same pool. No reveal effect
    is attached — these are flavor only, not leads.
    """
    if lang is None:
        lang = current_lang()
    # Stable per-hex seed. XORs mix the macro coord into the world
    # seed without zero-collisions at the origin (the large primes
    # diverge both axes).
    seed = (
        world_seed
        ^ ((macro_coord.q & 0xFFFFFFFF) * 1000003)
        ^ ((macro_coord.r & 0xFFFFFFFF) * 97)
    ) & 0xFFFFFFFF
    rng = random.Random(seed)
    registry = TableRegistry.get_or_load(lang)
    rumors: list[Rumor] = []
    for i in range(count):
        result = registry.roll(
            _WILDERNESS_TABLE, rng=rng, context={},
        )
        rumors.append(Rumor(
            id=f"wild_{macro_coord.q}_{macro_coord.r}_{i}",
            text=result.text,
            truth=True,
            reveals=None,
            source=RumorSource(
                table_id=_WILDERNESS_TABLE,
                entry_id=result.entry_id,
                context={},
                lang=lang,
                variant=result.variant_index,
            ),
        ))
    world.active_rumors.extend(rumors)
    return rumors


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
        variant=rumor.source.variant,
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
            variant=rumor.source.variant,
        ),
    )
