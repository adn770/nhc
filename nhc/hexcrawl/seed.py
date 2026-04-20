"""Deterministic dungeon seed derivation from hex context.

Mapping ``(world_seed, hex_coord, template_id) -> uint32 seed``.
Same inputs produce the same layout on every machine and replay,
so a hex's cave looks the same every time the player visits it.
"""

from __future__ import annotations

import hashlib

from nhc.hexcrawl.coords import HexCoord


_MASK_32 = (1 << 32) - 1


def dungeon_seed(
    world_seed: int,
    coord: HexCoord,
    template: str,
    sub: HexCoord | None = None,
) -> int:
    """Return a uint32 seed derived from the hex context.

    Uses SHA-256 for stability across Python versions (Python's
    built-in ``hash()`` is salted per-process). Only the low 32
    bits are kept so the seed fits any ``random.Random(seed)``
    consumer on 32-bit platforms.

    When ``sub`` is provided the sub-hex coord is mixed into the
    digest so the same ``(world_seed, macro, template)`` yields a
    distinct per-sub-hex seed — used to generate the small-site
    maps behind minor features in the flower view.
    """
    if sub is None:
        key = f"{int(world_seed)}|{coord.q}|{coord.r}|{template}"
    else:
        key = (
            f"{int(world_seed)}|{coord.q}|{coord.r}|{template}"
            f"|sub={sub.q},{sub.r}"
        )
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & _MASK_32
