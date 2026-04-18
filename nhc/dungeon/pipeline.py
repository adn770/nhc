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
    apply_terrain(level, rng)
    populate_level(level, rng=rng)
    return level
