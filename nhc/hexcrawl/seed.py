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
    world_seed: int, coord: HexCoord, template: str,
) -> int:
    """Return a uint32 seed derived from the triple.

    Uses SHA-256 for stability across Python versions (Python's
    built-in ``hash()`` is salted per-process). Only the low 32
    bits are kept so the seed fits any ``random.Random(seed)``
    consumer on 32-bit platforms.
    """
    key = f"{int(world_seed)}|{coord.q}|{coord.r}|{template}".encode(
        "utf-8",
    )
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:4], "big") & _MASK_32
