"""``Region`` → ``V5Region`` translator.

The v5 Region differs from v4:
- Drops ``kind`` (tooling reads ``id`` to infer role).
- Adds ``parent_id`` (sub-zone nesting; empty == top-level).
- Adds ``cuts`` (openings on perimeter; empty in this scaffold —
  Phase 1.4 doesn't lift cuts off the wall ops onto regions).

Phase 1.5's parity gate validates that the resulting v5 op
pipeline produces equivalent visual output. Phase 1.6+ migrates
the cut-resolution logic so ``V5Region.cuts`` is populated from
the wall ops' cut data.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.V5Region import V5RegionT


def translate_region(region: Any) -> V5RegionT:
    """Translate one v4 ``RegionT`` into a ``V5RegionT``.

    Preserves ``id``, ``shape_tag``, and ``outline``. Drops
    ``kind``. ``parent_id`` is empty (Phase 1.4 doesn't infer
    parent chains; sub-zones are added later as v5 emit grows).
    ``cuts`` is empty until Phase 1.6.
    """
    out = V5RegionT()
    out.id = region.id
    out.outline = region.outline
    # parent_id: empty in the scaffold. Phase 2 / future emit
    # passes will populate this when sub-region emission grows
    # (e.g. aisle.1 within temple.5).
    out.parentId = ""
    out.cuts = []
    out.shapeTag = region.shapeTag or ""
    return out
