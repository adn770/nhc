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
# Feature variant slots (biome-keyed)
# ---------------------------------------------------------------------------

# ``_FEATURE_TILES[feature][biome]`` lists the tile slot candidates
# for a feature on a given biome. When a (feature, biome) pair is
# not present, ``feature_variants`` falls back to the first
# greenlands / hills / any-listed-biome entry — see the lookup
# rules at :func:`feature_variants`.
_FEATURE_TILES: dict[str, dict[str, list[int]]] = {
    "city":      {"greenlands": [12], "hills": [12]},
    "village":   {"greenlands": [11], "hills": [11],
                  "sandlands": [11], "drylands": [11],
                  "marsh": [11], "mountain": [75]},
    "community": {"greenlands": [14], "hills": [14],
                  "sandlands": [14], "drylands": [14],
                  "marsh": [14], "mountain": [74],
                  "forest": [53]},
    "farm":      {"greenlands": [26]},
    "mansion":   {"greenlands": [52], "hills": [52],
                  "marsh": [52]},
    "cottage":   {"forest": [52]},
    "temple":    {"mountain":  [80], "forest":   [58],
                  # Mysterious variants use the mountain- /
                  # forest-Temple foundation re-rendered onto a
                  # sandlands / icelands background. See
                  # tools/generate_missing_hextiles.py.
                  "sandlands": [80], "icelands":  [58]},
    "ruin":      {"forest":    [18, 55],  # 55 = overgrown-Ruins
                  "deadlands": [18], "marsh": [18],
                  "sandlands": [18], "icelands":  [18]},
    "tower":     {"greenlands": [13], "hills": [13],
                  "sandlands": [13], "drylands": [13],
                  "marsh": [13], "mountain": [76],
                  "forest": [54],
                  "icelands": [13], "deadlands": [13],
                  "swamp": [13]},
    "keep":      {"greenlands": [22], "hills": [22],
                  "drylands": [22]},
    # Dungeon features previously encoded via the
    # ``_EXTENDED_BIOMES`` frozenset: extended biomes list the
    # extra slot variant so rolls can hit it; non-extended biomes
    # stay on the base slot.
    "cave":      {"greenlands": [15, 49], "forest": [15, 49],
                  "mountain": [15, 49], "hills": [15, 49],
                  "marsh": [15, 49], "swamp": [15, 49],
                  "icelands": [15], "deadlands": [15],
                  "drylands": [15], "sandlands": [15]},
    "hole":      {"greenlands": [16, 44], "forest": [16, 44],
                  "mountain": [16, 44], "hills": [16, 44],
                  "marsh": [16, 44], "swamp": [16, 44],
                  "icelands": [16], "deadlands": [16],
                  "drylands": [16], "sandlands": [16]},
    "stones":    {"greenlands": [25, 51], "forest": [25, 51],
                  "mountain": [25, 51], "hills": [25, 51],
                  "marsh": [25, 51], "swamp": [25, 51],
                  "icelands": [25], "deadlands": [25],
                  "drylands": [25], "sandlands": [25]},
    "graveyard": {"greenlands": [19]},
    "crystals":  {"greenlands": [24]},
    "wonder":    {"greenlands": [23]},
    "portal":    {"greenlands": [8]},
    "lake":      {"greenlands": [10]},
    "river":     {"greenlands": [7]},
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
    """Return tile slot variants for a feature on a given biome.

    Lookup order:

    1. ``_FEATURE_TILES[feature][biome]`` when present.
    2. ``_FEATURE_TILES[feature]["greenlands"]`` as a biome-
       agnostic fallback, then ``"hills"``.
    3. The first listed biome entry for ``feature`` — deterministic
       because dicts preserve insertion order.

    Returns ``None`` when the feature is entirely unknown.
    """
    entry = _FEATURE_TILES.get(feature)
    if entry is None:
        return None
    specific = entry.get(biome)
    if specific is not None:
        return list(specific)
    for fallback_biome in ("greenlands", "hills"):
        fallback = entry.get(fallback_biome)
        if fallback is not None:
            return list(fallback)
    # Last resort: first listed biome slot. Entry is non-empty by
    # construction, so next(iter(...)) is safe.
    _, slots = next(iter(entry.items()))
    return list(slots)


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
