"""Pure dungeon generation pipeline.

This module exposes :func:`generate_level`, a self-contained function
that runs the complete generation pipeline (carve → room types →
terrain → populate) and returns a fully populated :class:`Level`.

Design rules:

* **No thread-local state.** A fresh :class:`random.Random` instance
  is created from ``params.seed`` and threaded through every step.
  The caller's thread-local RNG (``nhc.utils.rng``) is not touched,
  so concurrent pool workers never race on it.
* **Pure data in, pure data out.** The only inputs are a
  :class:`GenerationParams` dataclass; the only output is a
  :class:`Level` dataclass. Both are picklable, so this function can
  run inside a :class:`concurrent.futures.ProcessPoolExecutor`.
* **No Game / World / EventBus / LLM references.** Entity factories
  are not invoked here; the populator only records string IDs on
  :class:`EntityPlacement` objects. Factories run later in the main
  process when the game spawns entities from placements.
"""

from __future__ import annotations

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.generators.cellular import CellularGenerator
from nhc.dungeon.model import Level
from nhc.dungeon.populator import populate_level
from nhc.dungeon.room_types import assign_room_types
from nhc.dungeon.templates import TEMPLATES, apply_template
from nhc.dungeon.terrain import apply_terrain
from nhc.dungeon.transforms import TRANSFORM_REGISTRY


def generate_level(params: GenerationParams) -> Level:
    """Run the full generation pipeline and return a populated Level.

    Safe to call from a :class:`ProcessPoolExecutor` worker: uses only
    the seed from ``params`` and a local RNG, returns picklable data.
    """
    seed = params.seed if params.seed is not None else 0
    rng = random.Random(seed)

    # Apply structural template if specified
    tmpl = TEMPLATES.get(params.template) if params.template else None
    if tmpl:
        effective = apply_template(params, tmpl)
    else:
        effective = params

    if effective.theme == "cave":
        generator = CellularGenerator()
    else:
        generator = BSPGenerator()

    level = generator.generate(effective, rng=rng)

    # Run post-generation transforms from template
    if tmpl:
        for transform_name in tmpl.transforms:
            fn = TRANSFORM_REGISTRY.get(transform_name)
            if fn:
                fn(level, rng)

    assign_room_types(level, rng)
    # Fork a separate RNG for dressing so we don't shift the
    # downstream seed sequence (terrain, population).
    dressing_rng = random.Random(seed ^ 0x44524553)  # "DRES"
    _roll_room_dressing(level, dressing_rng)
    apply_terrain(level, rng)
    populate_level(level, rng=rng)
    return level


def _roll_room_dressing(level: "Level", rng: "random.Random") -> None:
    """Roll smell/sight/sound dressing for each room."""
    from nhc.i18n import current_lang
    from nhc.tables.registry import TableRegistry
    from nhc.tables.roller import NoMatchingEntriesError

    lang = current_lang()
    registry = TableRegistry.get_or_load(lang)

    for room in level.rooms:
        room_type = _primary_room_type(room.tags)
        ctx = {"room_type": room_type}
        for aspect in ("smell", "sight", "sound"):
            table_id = f"room.dressing.{aspect}"
            try:
                result = registry.roll(table_id, rng=rng, context=ctx)
                room.dressing[aspect] = result.text
            except (NoMatchingEntriesError, KeyError):
                pass


def _primary_room_type(tags: list[str]) -> str:
    """Pick the most specific room type tag for dressing context."""
    for tag in tags:
        if tag in (
            "crypt", "barracks", "armory", "library",
            "shrine", "temple", "lair", "nest",
            "treasury", "trap_room", "garden",
        ):
            return tag
    return "standard"
