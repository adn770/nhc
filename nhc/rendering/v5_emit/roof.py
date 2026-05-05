"""Builder / regions walk → ``V5OpEntry(V5RoofOp)``.

Phase 4.3a entry point. :func:`emit_roofs` walks ``builder.regions``
for Building regions and synthesises a ``V5RoofOp`` per building
using the same seed / tint algorithm as
:func:`nhc.rendering.ir_emitter.emit_building_roofs`. Building-floor
IRs (where ``builder.site`` is set but ``level is not site.surface``)
are gated out so they don't pick up a spurious roof from their own
Building region.

:func:`translate_roof_ops` is retained as a back-compat shim for
:func:`translate_all` and walks ``builder.ops`` for v4 ``RoofOp``
entries.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5RoofOp import V5RoofOpT
from nhc.rendering.ir._fb.V5RoofStyle import V5RoofStyle


# Mirrors :data:`nhc.rendering.ir_emitter._ROOF_TINTS`. Duplicated
# rather than imported so the v5 emit pipeline has no upward
# dependency on the v4 emit module.
_ROOF_TINTS: tuple[str, ...] = (
    "#8A8A8A",
    "#8A7A5A",
    "#8A5A3A",
    "#5A5048",
    "#7A5A3A",
)

_SM64_GOLDEN = 0x9E3779B97F4A7C15
_SM64_C1 = 0xBF58476D1CE4E5B9
_SM64_C2 = 0x94D049BB133111EB
_SM64_MASK = 0xFFFFFFFFFFFFFFFF


def _splitmix64_first(seed: int) -> int:
    state = (seed + _SM64_GOLDEN) & _SM64_MASK
    z = ((state ^ (state >> 30)) * _SM64_C1) & _SM64_MASK
    z = ((z ^ (z >> 27)) * _SM64_C2) & _SM64_MASK
    return z ^ (z >> 31)


def _wrap(roof_op: V5RoofOpT) -> V5OpEntryT:
    entry = V5OpEntryT()
    entry.opType = V5Op.V5RoofOp
    entry.op = roof_op
    return entry


def _decode_id(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else (value or "")


def emit_roofs(builder: Any) -> list[V5OpEntryT]:
    """Walk builder.regions for Building regions and emit V5RoofOps.

    Gate: only fire on surface IRs (``ctx.floor_kind == "surface"``).
    Building-floor IRs and dungeon / cave / non-site IRs skip the
    layer entirely — matches :func:`emit_site_overlays` running
    :func:`emit_building_roofs` only for the site surface, and
    :func:`emit_building_overlays` not running it for individual
    building floors.
    """
    if getattr(builder.ctx, "floor_kind", "") != "surface":
        return []

    base_seed = builder.ctx.seed
    result: list[V5OpEntryT] = []
    for region in builder.regions:
        rid = _decode_id(getattr(region, "id", ""))
        if not rid.startswith("building."):
            continue
        try:
            i = int(rid.split(".", 1)[1])
        except ValueError:
            continue
        rng_seed = (base_seed + 0xCAFE + i) & _SM64_MASK
        tint_seed = (rng_seed ^ 0xC0FFEE) & _SM64_MASK
        tint = _ROOF_TINTS[_splitmix64_first(tint_seed) % len(_ROOF_TINTS)]
        v5 = V5RoofOpT()
        v5.regionRef = f"building.{i}"
        v5.style = V5RoofStyle.Simple
        v5.tone = 1
        v5.tint = tint
        v5.seed = rng_seed
        result.append(_wrap(v5))
    return result


def _v4_to_v5_roof_style(v4_style: int) -> int:
    if v4_style == RoofStyle.Dome:
        return V5RoofStyle.Dome
    if v4_style == RoofStyle.WitchHat:
        return V5RoofStyle.WitchHat
    return V5RoofStyle.Simple


def translate_roof_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Walk v4 ``RoofOp`` entries and wrap them as ``V5OpEntry``.

    Retained for back-compat with :func:`translate_all`.
    """
    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.RoofOp:
            continue
        roof = entry.op
        v5 = V5RoofOpT()
        v5.regionRef = roof.regionRef or ""
        v5.style = _v4_to_v5_roof_style(roof.style)
        v5.tone = 1
        v5.tint = roof.tint or ""
        v5.seed = int(getattr(roof, "rngSeed", 0) or 0)
        result.append(_wrap(v5))
    return result
