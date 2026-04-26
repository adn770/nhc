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
    *,
    tile_bucket: Callable[[Level, int, int], str] | None = None,
    room_clip_id: str | None = None,
) -> list[str]:
    """One row-major walk that dispatches every decorator.

    Returns a flat list of SVG fragment strings the caller appends
    to its output buffer. Decorators that produced no fragments
    contribute nothing -- their group wrappers stay suppressed.

    Output order is deterministic: decorators are emitted in their
    ``z_order``-then-input order; within a decorator, fragments
    appear in row-major tile order.

    When ``tile_bucket`` is supplied each matching tile is
    classified into a bucket name (``"room"`` or ``"corridor"`` by
    convention). Per-decorator fragments are then split by bucket
    so the emitter can wrap room fragments inside a clip group
    while corridor fragments stay unclipped -- mirroring the
    legacy behaviour where dungeon-poly clipping only applies to
    room-classified detail.

    When ``room_clip_id`` is set and the context carries a non-empty
    ``dungeon_poly``, the room bucket is wrapped in
    ``<g clip-path="url(#{room_clip_id})">`` and a matching
    ``<defs><clipPath/></defs>`` block is emitted before it. This
    lets the helper own the clip lifecycle so callers don't have to
    duplicate the ``_dungeon_interior_clip`` boilerplate.
    """
    active = [d for d in decorators if _flags_satisfy(ctx, d)]
    if not active:
        return []

    active_sorted = sorted(
        enumerate(active),
        key=lambda pair: (pair[1].z_order, pair[0]),
    )

    rngs = {d.name: _seeded_rng(ctx, d.name) for _, d in active_sorted}

    if tile_bucket is None:
        fragments_any: dict[str, list[str]] = {
            d.name: [] for _, d in active_sorted
        }
    else:
        fragments_buckets: dict[str, dict[str, list[str]]] = {
            d.name: {"room": [], "corridor": []}
            for _, d in active_sorted
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
                if tile_bucket is None:
                    fragments_any[dec.name].extend(produced)
                else:
                    bucket_name = tile_bucket(level, x, y)
                    fragments_buckets[dec.name][bucket_name].extend(
                        produced,
                    )

    out: list[str] = []
    if tile_bucket is None:
        for _, dec in active_sorted:
            frags = fragments_any[dec.name]
            if not frags:
                continue
            if dec.group_open is not None:
                out.append(dec.group_open)
            out.extend(frags)
            if dec.group_open is not None:
                out.append(dec.group_close)
        return out

    # Bucketed emission: room first (clipped), corridor after.
    has_any_room = any(
        fragments_buckets[d.name]["room"] for _, d in active_sorted
    )
    use_clip = (
        has_any_room
        and room_clip_id is not None
        and ctx.dungeon_poly is not None
        and not ctx.dungeon_poly.is_empty
    )
    if use_clip:
        out.append(_clip_defs(ctx.dungeon_poly, room_clip_id))
        out.append(f'<g clip-path="url(#{room_clip_id})">')
    for _, dec in active_sorted:
        frags = fragments_buckets[dec.name]["room"]
        if not frags:
            continue
        if dec.group_open is not None:
            out.append(dec.group_open)
        out.extend(frags)
        if dec.group_open is not None:
            out.append(dec.group_close)
    if use_clip:
        out.append("</g>")
    for _, dec in active_sorted:
        frags = fragments_buckets[dec.name]["corridor"]
        if not frags:
            continue
        if dec.group_open is not None:
            out.append(dec.group_open)
        out.extend(frags)
        if dec.group_open is not None:
            out.append(dec.group_close)
    return out


def _clip_defs(dungeon_poly, clip_id: str) -> str:
    """Build a ``<defs><clipPath/></defs>`` block from the
    dungeon polygon. Mirrors :func:`_dungeon_interior_clip` from
    ``_floor_detail`` so this module stays free of cross-imports."""
    geoms = (
        dungeon_poly.geoms
        if hasattr(dungeon_poly, "geoms")
        else [dungeon_poly]
    )
    clip_d = ""
    for geom in geoms:
        coords = list(geom.exterior.coords)
        clip_d += f'M{coords[0][0]:.0f},{coords[0][1]:.0f} '
        clip_d += " ".join(
            f"L{x:.0f},{y:.0f}" for x, y in coords[1:]
        )
        clip_d += " Z "
        for hole in geom.interiors:
            h = list(hole.coords)
            clip_d += f'M{h[0][0]:.0f},{h[0][1]:.0f} '
            clip_d += " ".join(
                f"L{x:.0f},{y:.0f}" for x, y in h[1:]
            )
            clip_d += " Z "
    return (
        f'<defs><clipPath id="{clip_id}">'
        f'<path d="{clip_d}" fill-rule="evenodd"/>'
        "</clipPath></defs>"
    )
