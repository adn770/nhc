"""Tests for backend tile slot selection.

The tiles module is the single source of truth for which tile
PNG each hex displays. It replaces the frontend-side selection
that previously lived in hex_map.js.
"""

from __future__ import annotations

from nhc.hexcrawl.tiles import (
    BIOME_BASE_SLOTS,
    DENSE_SLOTS,
    SLOT_NAME,
    _FEATURE_TILES,
    assign_tile_slot,
    feature_variants,
    hex_hash,
    weighted_slot,
)


# ---------------------------------------------------------------------------
# Deterministic hash
# ---------------------------------------------------------------------------


def test_hex_hash_deterministic() -> None:
    assert hex_hash(3, 5) == hex_hash(3, 5)


def test_hex_hash_varies_with_input() -> None:
    assert hex_hash(0, 0) != hex_hash(1, 0)
    assert hex_hash(0, 0) != hex_hash(0, 1)


# ---------------------------------------------------------------------------
# Weighted slot selection
# ---------------------------------------------------------------------------


def test_weighted_slot_deterministic() -> None:
    pairs = [(3, 30), (6, 20), (25, 10)]
    a = weighted_slot(5, 7, pairs)
    b = weighted_slot(5, 7, pairs)
    assert a == b


def test_weighted_slot_returns_valid_slot() -> None:
    pairs = [(3, 30), (6, 20), (25, 10)]
    valid = {s for s, _ in pairs}
    for q in range(10):
        for r in range(10):
            assert weighted_slot(q, r, pairs) in valid


def test_weighted_slot_single_entry() -> None:
    assert weighted_slot(0, 0, [(5, 1)]) == 5


# ---------------------------------------------------------------------------
# Feature variants
# ---------------------------------------------------------------------------


def test_feature_variants_base_only_for_non_extended() -> None:
    """Biomes without a custom tower tile should fall back to the
    greenlands slot."""
    variants = feature_variants("tower", "icelands")
    assert variants == [13]


def test_feature_variants_forest_swaps_to_forest_tower() -> None:
    """Forest replaces the generic tower tile with the watchtower
    tile; biome-keyed lookup returns only the biome-specific slot."""
    variants = feature_variants("tower", "forest")
    assert variants == [54]


def test_feature_variants_mountain_swaps_to_mountain_tower() -> None:
    """Mountain replaces the generic tower tile with the
    mountain-Tower slot."""
    variants = feature_variants("tower", "mountain")
    assert variants == [76]


def test_feature_variants_unknown_returns_none() -> None:
    assert feature_variants("nonexistent", "greenlands") is None


# ---------------------------------------------------------------------------
# assign_tile_slot
# ---------------------------------------------------------------------------


def test_assign_tile_slot_deterministic() -> None:
    a = assign_tile_slot("greenlands", "none", 3, 5, False)
    b = assign_tile_slot("greenlands", "none", 3, 5, False)
    assert a == b


def test_assign_tile_slot_returns_valid_slot_name() -> None:
    slot = assign_tile_slot("forest", "none", 0, 0, False)
    assert slot in SLOT_NAME


def test_assign_tile_slot_excludes_dense_on_waterway() -> None:
    """When has_waterway is True, dense canopy slots must not
    be selected."""
    dense_count = 0
    for q in range(20):
        for r in range(20):
            slot = assign_tile_slot(
                "greenlands", "none", q, r, has_waterway=True,
            )
            if slot in DENSE_SLOTS:
                dense_count += 1
    assert dense_count == 0, (
        f"dense slots appeared {dense_count} times on waterway hexes"
    )


def test_assign_tile_slot_allows_dense_without_waterway() -> None:
    """Without waterway, dense slots should appear sometimes."""
    dense_count = 0
    for q in range(20):
        for r in range(20):
            slot = assign_tile_slot(
                "greenlands", "none", q, r, has_waterway=False,
            )
            if slot in DENSE_SLOTS:
                dense_count += 1
    assert dense_count > 0, "dense slots should appear sometimes"


def test_assign_tile_slot_all_biomes() -> None:
    """Every biome should produce a valid slot."""
    for biome in BIOME_BASE_SLOTS:
        slot = assign_tile_slot(biome, "none", 0, 0, False)
        assert slot in SLOT_NAME, f"{biome} produced invalid slot {slot}"


def test_assign_tile_slot_feature_overrides_base() -> None:
    """When a feature is present, the slot should come from the
    feature variant list, not the base slots."""
    slot = assign_tile_slot("greenlands", "cave", 0, 0, False)
    assert slot in (15, 49)  # cave base + ext


def test_assign_tile_slot_water_ignores_feature() -> None:
    """Water biome always uses slot 5 regardless of feature."""
    slot = assign_tile_slot("water", "tower", 0, 0, False)
    assert slot == 5


def test_assign_tile_slot_minor_farm_in_greenlands_uses_farm_art() -> None:
    """A sub-cell whose ``major`` is none and whose ``minor`` is
    ``farm`` should render with slot 26 (``farms.png``) so the
    flower art advertises the feature the player can enter."""
    slot = assign_tile_slot(
        "greenlands", "none", 0, 0, False, minor_feature="farm",
    )
    assert slot == 26


def test_assign_tile_slot_minor_mushroom_ring_uses_mushrooms_art() -> None:
    slot = assign_tile_slot(
        "forest", "none", 0, 0, False,
        minor_feature="mushroom_ring",
    )
    assert slot == 48


def test_assign_tile_slot_minor_standing_stone_uses_standing_stones_art() -> None:
    slot = assign_tile_slot(
        "hills", "none", 0, 0, False,
        minor_feature="standing_stone",
    )
    assert slot == 51


def test_assign_tile_slot_minor_cairn_uses_stones_art() -> None:
    """CAIRN minor reuses slot 25 (``stones.png``) — the same art
    the ``stones`` major may pick. Semantically consistent: the
    player sees a pile of stones either way and the entry
    dispatcher routes to a sacred-site generator in both cases."""
    slot = assign_tile_slot(
        "mountain", "none", 0, 0, False, minor_feature="cairn",
    )
    assert slot == 25


def test_assign_tile_slot_major_overrides_minor() -> None:
    """When both are set, the major feature wins — otherwise a
    bespoke site like a town would be hidden behind a minor-farm
    tile."""
    slot = assign_tile_slot(
        "greenlands", "city", 0, 0, False, minor_feature="farm",
    )
    assert slot == 12  # city


def test_assign_tile_slot_unmapped_minor_falls_back_to_base_palette() -> None:
    """Minors without tile art (well, shrine, signpost, ...)
    leave the tile as a neutral biome texture. The flower
    renderer is free to add glyph overlays later without the
    backend lying about the tile."""
    slot = assign_tile_slot(
        "greenlands", "none", 0, 0, False, minor_feature="well",
    )
    # WELL has no _FEATURE_TILES entry, so slot comes from the
    # greenlands base palette.
    assert slot in {s for s, _ in BIOME_BASE_SLOTS["greenlands"]}


def test_base_palettes_do_not_alias_feature_slots() -> None:
    """Regression: user reported a ``farm`` tile in the flower that
    actually housed a ``well``. Root cause: ``greenlands`` base
    palette included slot 26 (farms) at 10 % weight. Any slot used
    as a primary feature tile must NOT appear in a biome's base
    palette — otherwise a featureless sub-hex can display tile art
    that advertises a feature the gameplay code never generated."""
    feature_slots: set[int] = set()
    for slots_by_biome in _FEATURE_TILES.values():
        for slots in slots_by_biome.values():
            feature_slots.update(slots)
    offenders: dict[str, list[int]] = {}
    for biome, pairs in BIOME_BASE_SLOTS.items():
        bad = sorted({s for s, _ in pairs} & feature_slots)
        if bad:
            offenders[biome] = bad
    assert not offenders, (
        "base-palette slots shadow feature slots — featureless "
        f"cells would render as features: {offenders}"
    )
