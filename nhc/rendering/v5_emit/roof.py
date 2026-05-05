"""``RoofOp`` → ``V5RoofOp`` translator.

The v4 ``RoofOp`` carries (region_ref, style, tint, rng_seed). The
v5 ``V5RoofOp`` keeps the same surface but renames ``rng_seed`` →
``seed`` and adds an explicit ``tone`` axis (uint8). The v5 enum
``V5RoofStyle`` extends v4 with Pyramid / Gable variants; the
existing v4 styles (Simple / Dome / WitchHat) carry over with the
same numeric values, so the translation is mechanical.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT
from nhc.rendering.ir._fb.V5RoofOp import V5RoofOpT
from nhc.rendering.ir._fb.V5RoofStyle import V5RoofStyle


def _v4_to_v5_roof_style(v4_style: int) -> int:
    if v4_style == RoofStyle.Dome:
        return V5RoofStyle.Dome
    if v4_style == RoofStyle.WitchHat:
        return V5RoofStyle.WitchHat
    # Simple (default) maps to Simple. Pyramid/Gable in v5 are not
    # produced by the v4 emitter (no v4 enum slot exists for
    # them); the v5 Phase 2.x emitter widens this when the
    # building shape_tag dispatch lands.
    return V5RoofStyle.Simple


def translate_roof_ops(ops: list[Any]) -> list[V5OpEntryT]:
    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.RoofOp:
            continue
        roof = entry.op
        v5 = V5RoofOpT()
        v5.regionRef = roof.regionRef or ""
        v5.style = _v4_to_v5_roof_style(roof.style)
        v5.tone = 1  # default Medium tone (Phase 2.x widens)
        v5.tint = roof.tint or ""
        v5.seed = int(getattr(roof, "rngSeed", 0) or 0)

        wrapped = V5OpEntryT()
        wrapped.opType = V5Op.V5RoofOp
        wrapped.op = v5
        result.append(wrapped)
    return result
