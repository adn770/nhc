"""Layer abstraction + ordered registry for the SVG floor pipeline.

The floor renderer used to be a hardcoded sequence of nine direct
calls in ``render_floor_svg``. Phase 5 of the rendering refactor
replaces that with a sortable :class:`Layer` registry: each pass
declares its name, ``order``, an ``is_active`` predicate against
the :class:`RenderContext`, and a ``paint`` callable.

Adding a new pass becomes one tuple entry in :data:`_LAYERS`.
Adding a per-tile decorator behind an existing pass becomes one
entry in the relevant :class:`TileWalkLayer`'s decorator list. No
orchestrator edit is needed for either.

Bespoke layers (shadows, hatching, walls, terrain tints, grid,
stairs) wrap the existing geometry-aware passes; tile-walk layers
(floor_detail, terrain_detail, surface_features) pull decorators
through the unified :func:`walk_and_paint` helper.

Extension recipe:
    1. Decide whether the new pass paints geometry uniformly
       (bespoke) or per-tile (decorator). Geometry-uniform: write
       a Layer with a custom ``paint``. Per-tile: write a
       :class:`TileDecorator` and add it to the matching
       ``TileWalkLayer`` decorator tuple.
    2. Pick an ``order`` int that slots between the existing
       layers. The numbering uses gaps of 100 (shadows=100,
       hatching=200, ...) so inserts have room.
    3. If the new pass needs a context flag (``ctx.shadows_enabled``
       and friends) drop a one-line check into ``is_active``.
    4. Append the layer to :data:`_LAYERS`. The renderer picks it
       up automatically.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from nhc.rendering._decorators import TileDecorator, walk_and_paint
from nhc.rendering._render_context import RenderContext


logger = logging.getLogger(__name__)

_OPEN_TAG = re.compile(r"<[a-zA-Z]")


@dataclass(frozen=True)
class Layer:
    """One pass in the floor renderer.

    ``order`` decides the emit order; lower fires first. Two
    layers with the same order break ties on registry position.

    ``is_active`` is a single boolean read against the context;
    an inactive layer contributes nothing to the SVG.
    """

    name: str
    order: int
    is_active: Callable[[RenderContext], bool]
    paint: Callable[[RenderContext], Iterable[str]]


@dataclass(frozen=True)
class TileWalkLayer(Layer):
    """A layer whose paint runs the unified per-tile walk.

    ``decorators`` registers a tuple of :class:`TileDecorator`
    instances that share the same row-major walk, the same
    optional ``tile_bucket`` classifier, and the same optional
    ``room_clip_id``. The Layer's ``paint`` field is built by
    :func:`make_tile_walk_layer` so callers don't need to wire it
    up by hand.
    """

    decorators: tuple[TileDecorator, ...] = field(default_factory=tuple)
    tile_bucket: Callable | None = None
    room_clip_id: str | None = None


def make_tile_walk_layer(
    *,
    name: str,
    order: int,
    decorators: tuple[TileDecorator, ...],
    is_active: Callable[[RenderContext], bool] | None = None,
    tile_bucket: Callable | None = None,
    room_clip_id: str | None = None,
) -> TileWalkLayer:
    """Factory for :class:`TileWalkLayer` instances.

    Wires the layer's ``paint`` to :func:`walk_and_paint` with the
    declared decorators / classifier / clip id so callers stay
    declarative.
    """

    def paint(ctx: RenderContext) -> Iterable[str]:
        return walk_and_paint(
            ctx,
            decorators,
            layer_name=name,
            tile_bucket=tile_bucket,
            room_clip_id=room_clip_id,
        )

    return TileWalkLayer(
        name=name,
        order=order,
        is_active=is_active or (lambda ctx: True),
        paint=paint,
        decorators=decorators,
        tile_bucket=tile_bucket,
        room_clip_id=room_clip_id,
    )


def render_layers(
    ctx: RenderContext, layers: Iterable[Layer],
) -> list[str]:
    """Order the layers by ``order`` and emit each active layer.

    Returned as a flat list of SVG fragment strings the
    orchestrator concatenates with ``"\\n".join(...)``.

    Each active layer's fragments are prefixed by a stats
    comment of the form
    ``<!-- layer.NAME: N elements, M bytes -->`` so the rendered
    SVG is self-describing for size analysis. A summary line at
    DEBUG level (logger ``nhc.rendering._pipeline``) lists the
    breakdown for every render so log scrapes can profile what
    the floor is spending bytes on.
    """
    sorted_layers = sorted(
        enumerate(layers), key=lambda pair: (pair[1].order, pair[0]),
    )
    out: list[str] = []
    breakdown: list[tuple[str, int, int]] = []
    for _, layer in sorted_layers:
        if not layer.is_active(ctx):
            continue
        layer_frags = list(layer.paint(ctx))
        joined = "".join(layer_frags)
        n_elements = len(_OPEN_TAG.findall(joined))
        n_bytes = len(joined)
        breakdown.append((layer.name, n_elements, n_bytes))
        out.append(
            f"<!-- layer.{layer.name}: {n_elements} elements, "
            f"{n_bytes} bytes -->"
        )
        out.extend(layer_frags)
    if logger.isEnabledFor(logging.DEBUG):
        total_bytes = sum(b for _, _, b in breakdown)
        total_elements = sum(n for _, n, _ in breakdown)
        per_layer = " ".join(
            f"{name}={b}b/{n}el"
            for name, n, b in breakdown
        )
        logger.debug(
            "render_layers: total=%db/%del [%s]",
            total_bytes, total_elements, per_layer,
        )
    return out
