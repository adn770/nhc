"""Builder.regions → ``V5Region`` list.

Phase 4.3a entry point. :func:`emit_regions` walks
``builder.regions`` and translates each :class:`RegionT` into a
:class:`RegionT`. The v5 Region differs from v4:

- Drops ``kind`` (tooling reads ``id`` to infer role).
- Adds ``parent_id`` (sub-zone nesting; empty == top-level).
- Adds ``cuts`` (openings on perimeter; empty in this scaffold —
  Phase 1.6+ migrates the cut-resolution logic so ``V5Region.cuts``
  is populated from the wall ops' cut data).

:func:`translate_region` is retained for back-compat with the
legacy :func:`translate_all` entry point and for callers that
hand-build a single Region.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Region import RegionT


def emit_regions(builder: Any) -> list[RegionT]:
    """Walk ``builder.regions`` and translate each into a RegionT."""
    return [translate_region(r) for r in builder.regions]


def translate_region(region: Any) -> RegionT:
    """Translate one v4 ``RegionT`` into a ``RegionT``.

    Preserves ``id``, ``shape_tag``, and ``outline``. Drops
    ``kind``. ``parent_id`` is empty (Phase 1.4 doesn't infer
    parent chains; sub-zones are added later as v5 emit grows).
    ``cuts`` is empty until Phase 1.6.
    """
    out = RegionT()
    out.id = region.id
    out.outline = region.outline
    # parent_id: empty in the scaffold. Phase 2 / future emit
    # passes will populate this when sub-region emission grows
    # (e.g. aisle.1 within temple.5).
    out.parentId = ""
    out.cuts = []
    out.shapeTag = region.shapeTag or ""
    return out
