"""``ShadowOp`` → ``V5OpEntry`` translator.

Shadow op shape is identical between v4 and v5 — both unions reach
the same ``ShadowOp`` FlatBuffer struct (per design/map_ir_v5.md
§3.5: "ShadowOp carries over from v4 unchanged"). The translator is
a mechanical wrap: each v4 ``ShadowOp`` becomes a ``V5OpEntry``
whose ``opType`` is ``V5Op.ShadowOp`` and whose ``op`` payload is
the same ``ShadowOpT`` the v4 builder produced.
"""

from __future__ import annotations

from typing import Any

from nhc.rendering.ir._fb.Op import Op
from nhc.rendering.ir._fb.V5Op import V5Op
from nhc.rendering.ir._fb.V5OpEntry import V5OpEntryT


def translate_shadow_ops(ops: list[Any]) -> list[V5OpEntryT]:
    """Wrap each v4 ``ShadowOp`` in a ``V5OpEntry``.

    The op payload carries over byte-for-byte; only the wrapping
    union tag flips from v4 ``Op.ShadowOp`` to v5 ``V5Op.ShadowOp``.
    """
    result: list[V5OpEntryT] = []
    for entry in ops:
        if getattr(entry, "opType", None) != Op.ShadowOp:
            continue
        wrapped = V5OpEntryT()
        wrapped.opType = V5Op.ShadowOp
        wrapped.op = entry.op
        result.append(wrapped)
    return result
