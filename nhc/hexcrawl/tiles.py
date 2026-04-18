"""Tile slot selection for hexcrawl cells.

Single source of truth for which tile PNG each hex displays.
Called during world generation so the backend controls tile
art — the frontend just builds URLs from the slot it receives.

When a hex carries a river or road, dense canopy slots are
excluded so waterways remain visible on lighter terrain tiles
(sparse trees, clearings, tundra, etc.).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Slot → filename stem (must match hextiles/ on disk)
# ---------------------------------------------------------------------------

SLOT_NAME: dict[int, str] = {
    1: "vulcano", 2: "forest", 3: "tundra", 4: "trees", 5: "water",
    6: "hills", 7: "river", 8: "portal", 9: "mountains", 10: "lake",
    11: "village", 12: "city", 13: "tower", 14: "community",
    15: "cave", 16: "hole", 17: "dead-Trees", 18: "ruins",
    19: "graveyard", 20: "swamp", 21: "floating-Island",
    22: "keep", 23: "wonder", 24: "cristals", 25: "stones",
    26: "farms", 27: "fog",
    41: "dense-Forest", 42: "sparse-Trees", 43: "clearing",
    44: "rift", 45: "wild-Bushes", 46: "spider-Lair",
    47: "great-Tree", 48: "mushrooms", 49: "cave-Mouth",
    50: "hillock", 51: "standing-Stones", 52: "cottage",
    53: "hamlet", 54: "watchtower", 55: "overgrown-Ruins",
    56: "blast-Site", 57: "forest-Road", 58: "forest-Temple",
    61: "mountain-Range", 62: "scattered-Peaks", 63: "plateau",
    64: "active-Vulcano", 65: "mountain-Rift", 66: "foothills",
    67: "rock-Spikes", 68: "mountain-Gates", 69: "summit",
    70: "stone-Bridge", 71: "mountain-Cave", 72: "alpine-Forest",
    73: "obelisk", 74: "mountain-Lodge", 75: "mountain-Village",
    76: "mountain-Tower", 77: "mountain-Ruins", 78: "mountain-Blast",
    79: "mountain-Pass", 80: "mountain-Temple",
}


# ---------------------------------------------------------------------------
# Weighted base-tile palettes per biome
# ---------------------------------------------------------------------------

BIOME_BASE_SLOTS: dict[str, list[tuple[int, int]]] = {
    "greenlands": [
        (42, 20), (4, 18), (43, 15), (45, 12), (26, 10), (2, 8),
        (41, 5), (50, 4), (20, 3), (55, 3), (10, 2),
    ],
    "forest": [
        (2, 20), (41, 18), (4, 15), (42, 12), (47, 8), (45, 7),
        (43, 5), (6, 4), (48, 3), (50, 3), (20, 3), (55, 2),
    ],
    "mountain": [
        (9, 18), (61, 15), (62, 14), (69, 10), (66, 8), (79, 7),
        (67, 6), (63, 5), (6, 5), (72, 4), (65, 4), (70, 4),
    ],
    "hills": [
        (6, 22), (45, 16), (50, 14), (4, 12), (42, 10), (3, 10),
        (43, 8), (9, 8),
    ],
    "marsh": [
        (20, 25), (3, 18), (17, 14), (6, 12), (42, 9), (45, 7),
        (10, 1), (19, 5), (55, 4),
    ],
    "swamp": [
        (20, 28), (17, 18), (3, 12), (45, 10), (42, 8), (10, 1),
        (6, 6), (55, 5), (19, 5),
    ],
    "drylands": [
        (3, 30), (6, 20), (17, 15), (20, 12), (9, 10), (4, 8),
        (10, 5),
    ],
    "sandlands": [
        (3, 30), (6, 20), (17, 15), (20, 12), (9, 10), (18, 5),
        (19, 4), (4, 4),
    ],
    "icelands": [
        (3, 30), (6, 20), (17, 15), (20, 12), (27, 10), (9, 5),
        (10, 4), (18, 4),
    ],
    "deadlands": [
        (3, 30), (6, 20), (20, 15), (9, 12), (17, 10), (18, 5),
        (19, 4), (1, 4),
    ],
    "water": [(5, 1)],
}


# ---------------------------------------------------------------------------
# Feature variant slots
# ---------------------------------------------------------------------------

_EXTENDED_BIOMES: frozenset[str] = frozenset({
    "greenlands", "forest", "mountain", "hills", "marsh", "swamp",
})

# (base_slots, extended_slots) per feature.
_FEATURE_BASE: dict[str, tuple[list[int], list[int]]] = {
    "cave":      ([15], [49]),
    "ruin":      ([18], [55]),
    "tower":     ([13], [54]),
    "village":   ([11], [53]),
    "stones":    ([25], [51]),
    "hole":      ([16], [44]),
    "keep":      ([22], []),
    "city":      ([12], []),
    "graveyard": ([19], []),
    "crystals":  ([24], []),
    "wonder":    ([23], []),
    "portal":    ([8],  []),
    "lake":      ([10], []),
    "river":     ([7],  []),
}


# ---------------------------------------------------------------------------
# Dense canopy slots (excluded on waterway hexes)
# ---------------------------------------------------------------------------

DENSE_SLOTS: frozenset[int] = frozenset({
    2,   # forest
    41,  # dense-Forest
    47,  # great-Tree
    50,  # hillock (trees on rock)
    72,  # alpine-Forest
})


# ---------------------------------------------------------------------------
# Core algorithms
# ---------------------------------------------------------------------------


def hex_hash(q: int, r: int) -> int:
    """Deterministic hash for tile selection. Same (q, r) always
    produces the same value."""
    h = (q * 7919 + r * 104729) & 0x7FFFFFFF
    h = ((h >> 16) ^ h) * 0x45D9F3B
    return ((h >> 16) ^ h) & 0x7FFFFFFF


def weighted_slot(
    q: int, r: int, pairs: list[tuple[int, int]],
) -> int:
    """Pick a slot from weighted (slot, weight) pairs using a
    deterministic hash of (q, r)."""
    if len(pairs) == 1:
        return pairs[0][0]
    total = sum(w for _, w in pairs)
    roll = hex_hash(q, r) % total
    acc = 0
    for slot, w in pairs:
        acc += w
        if roll < acc:
            return slot
    return pairs[-1][0]


def feature_variants(
    feature: str, biome: str,
) -> list[int] | None:
    """Return tile slot variants for a feature, gated by biome.

    Non-extended biomes only get base slots. Returns None if the
    feature is unknown.
    """
    entry = _FEATURE_BASE.get(feature)
    if entry is None:
        return None
    base, ext = entry
    if biome in _EXTENDED_BIOMES and ext:
        return base + ext
    return list(base)


def assign_tile_slot(
    biome: str,
    feature: str,
    q: int,
    r: int,
    has_waterway: bool = False,
) -> int:
    """Assign the tile slot for a hex cell.

    Called during world generation after rivers/roads are routed.
    When *has_waterway* is True, dense canopy slots are excluded
    so waterways remain visible.
    """
    # Water is a single-tile biome.
    if biome == "water":
        return 5

    # Feature hexes use feature-specific slots.
    if feature and feature != "none":
        variants = feature_variants(feature, biome)
        if variants:
            idx = hex_hash(q, r) % len(variants)
            return variants[idx]

    # Featureless hexes use weighted base palette.
    pairs = BIOME_BASE_SLOTS.get(biome, [(4, 1)])
    if has_waterway:
        open_pairs = [(s, w) for s, w in pairs if s not in DENSE_SLOTS]
        if open_pairs:
            pairs = open_pairs
    return weighted_slot(q, r, pairs)


def tile_url(biome: str, slot: int) -> str:
    """Build the /hextiles/ URL path for a biome + slot."""
    stem = SLOT_NAME[slot]
    return f"/hextiles/{biome}/{slot}-{biome}_{stem}.png"
