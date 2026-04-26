"""Per-tile painter contract for the SVG floor pipeline.

Phase 2 of the rendering refactor. A :class:`TileDecorator` packs
the four pieces every per-tile renderer used to reimplement: a
predicate that decides which tiles match, a paint callable that
emits SVG fragments, optional ``requires`` / ``forbids`` flag gates
against the :class:`RenderContext`, and a group wrapper to emit
once when at least one fragment was produced.

:func:`walk_and_paint` does one row-major tile walk per call,
dispatches each matching decorator, and emits its group only when
the decorator produced fragments. This collapses the half-dozen
near-identical loops in the renderer (``_render_street_cobblestone``,
``_render_field_surface``, ``_render_garden_surface``,
``_render_cart_tracks``, ``_render_ore_deposits``, ...) into one.

See ``rendering_refactor_plan.md`` for the migration list and the
roadmap for biome / theme variants.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal

from nhc.dungeon.model import Level, Tile
from nhc.rendering._render_context import RenderContext
from nhc.rendering._svg_helpers import CELL


Bucket = Literal["any", "room", "corridor"]


@dataclass(frozen=True)
class PaintArgs:
    """Inputs every paint callable receives.

    ``rng`` is the per-decorator deterministic random source --
    seeded from the context seed plus the decorator name -- so two
    decorators sharing a predicate don't entangle their RNG state.
    """

    rng: random.Random
    x: int
    y: int
    px: float
    py: float
    ctx: RenderContext
    tile: Tile


@dataclass(frozen=True)
class TileDecorator:
    """One unit of per-tile painting.

    ``predicate`` reads the level and tile and decides whether to
    paint. ``paint`` returns an iterable of SVG fragment strings.
    ``requires`` / ``forbids`` gate the whole decorator on resolved
    :class:`RenderContext` flags (``shadows_enabled``,
    ``hatching_enabled``, ``atmospherics_enabled``,
    ``macabre_detail``, plus arbitrary string flags introduced by
    later phases such as ``"interior_finish_wood"``).

    ``group_open`` (when set) is emitted once before the
    decorator's fragments and ``group_close`` once after them --
    but only when at least one fragment was produced. Setting
    ``group_open`` to ``None`` means the decorator's fragments are
    appended raw.

    ``z_order`` controls intra-layer ordering when several
    decorators share the same layer name; lower fires first.

    ``bucket`` selects how the emitted fragments wrap:
      * ``"any"``   — single group, no clipping (the default; town
        surface decorators).
      * ``"room"``  — single group clipped to ``ctx.dungeon_poly``
        (indoor floor detail).
      * ``"corridor"`` — single group, no clip (corridor detail
        bypasses the dungeon-polygon clip).
    """

    name: str
    layer: str
    predicate: Callable[[Level, int, int], bool]
    paint: Callable[[PaintArgs], Iterable[str]]
    requires: frozenset[str] = field(default_factory=frozenset)
    forbids: frozenset[str] = field(default_factory=frozenset)
    group_open: str | None = None
    group_close: str = "</g>"
    z_order: int = 0
    bucket: Bucket = "any"


def _flag_value(ctx: RenderContext, name: str) -> bool:
    """Resolve a flag name on the render context.

    Looks up known boolean attributes
    (``shadows_enabled``, ``hatching_enabled``,
    ``atmospherics_enabled``, ``macabre_detail``) and synthetic
    string flags such as ``"interior_finish_wood"`` -> True iff
    ``ctx.interior_finish == "wood"``. Unknown flag names default
    to False so a typo never silently passes a ``requires`` gate.
    """
    if name.startswith("interior_finish_"):
        wanted = name.removeprefix("interior_finish_")
        return ctx.interior_finish == wanted
    if hasattr(ctx, name):
        value = getattr(ctx, name)
        return bool(value)
    return False


def _flags_satisfy(ctx: RenderContext, dec: TileDecorator) -> bool:
    """True iff every ``requires`` flag is True and no ``forbids``
    flag is True for the supplied context."""
    for flag in dec.requires:
        if not _flag_value(ctx, flag):
            return False
    for flag in dec.forbids:
        if _flag_value(ctx, flag):
            return False
    return True


def _seeded_rng(ctx: RenderContext, name: str) -> random.Random:
    """Per-decorator deterministic RNG.

    Seeded by ``(ctx.seed, decorator_name)`` so two different
    decorators called in the same layer never share a state vector.
    Python's ``hash()`` is salted between interpreter runs (the
    PYTHONHASHSEED), so we use a stable name-derived integer to
    keep the SVG output reproducible.
    """
    name_seed = sum(
        (ord(c) * 31 ** i) for i, c in enumerate(name)
    ) & 0xFFFF_FFFF
    return random.Random((ctx.seed * 1_000_003) ^ name_seed)


def walk_and_paint(
    ctx: RenderContext,
    decorators: Iterable[TileDecorator],
    layer_name: str = "",
) -> list[str]:
    """One row-major walk that dispatches every decorator.

    Returns a flat list of SVG fragment strings the caller appends
    to its output buffer. Decorators that produced no fragments
    contribute nothing -- their group wrappers stay suppressed.

    Output order is deterministic: decorators are emitted in their
    ``z_order``-then-input order; within a decorator, fragments
    appear in row-major tile order.
    """
    active = [d for d in decorators if _flags_satisfy(ctx, d)]
    if not active:
        return []

    active_sorted = sorted(
        enumerate(active),
        key=lambda pair: (pair[1].z_order, pair[0]),
    )

    rngs = {d.name: _seeded_rng(ctx, d.name) for _, d in active_sorted}

    fragments: dict[str, list[str]] = {
        d.name: [] for _, d in active_sorted
    }

    level = ctx.level
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            for _, dec in active_sorted:
                if not dec.predicate(level, x, y):
                    continue
                args = PaintArgs(
                    rng=rngs[dec.name],
                    x=x, y=y,
                    px=x * CELL, py=y * CELL,
                    ctx=ctx, tile=tile,
                )
                produced = dec.paint(args)
                if produced is None:
                    continue
                fragments[dec.name].extend(produced)

    out: list[str] = []
    for _, dec in active_sorted:
        frags = fragments[dec.name]
        if not frags:
            continue
        if dec.group_open is not None:
            out.append(dec.group_open)
        out.extend(frags)
        if dec.group_open is not None:
            out.append(dec.group_close)
    return out
