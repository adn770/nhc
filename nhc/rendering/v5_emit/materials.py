"""Material / WallMaterial factories for v5 emit.

Returns ``V5MaterialT`` / ``V5WallMaterialT`` populated with the
canonical ``(family, style, sub_pattern, tone, seed)`` tuple per
``design/map_ir_v5.md`` §4. The
:func:`wall_material_from_wall_style` helper still maps from a v4
``WallStyle`` enum value because :mod:`stroke` consumes one for
the deferred site / building-floor branches; the floor-style and
cobble-pattern v4 → v5 helpers retired with the per-module emit
refactor.
"""

from __future__ import annotations

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.V5Material import V5MaterialT
from nhc.rendering.ir._fb.V5MaterialFamily import V5MaterialFamily
from nhc.rendering.ir._fb.V5WallMaterial import V5WallMaterialT
from nhc.rendering.ir._fb.V5WallTreatment import V5WallTreatment
from nhc.rendering.ir._fb.WallStyle import WallStyle


# ── Style enum subtables (mirrors design/map_ir_v5.md §4) ──────

# Wood — species axis
WOOD_OAK = 0
WOOD_WALNUT = 1
WOOD_CHERRY = 2
WOOD_PINE = 3
WOOD_WEATHERED = 4

# Wood — sub_pattern (layout)
WOOD_PLANK = 0
WOOD_BASKETWEAVE = 1
WOOD_PARQUET = 2
WOOD_HERRINGBONE = 3

# Wood — tone
WOOD_LIGHT = 0
WOOD_MEDIUM = 1
WOOD_DARK = 2
WOOD_CHARRED = 3

# Cave — style
CAVE_LIMESTONE = 0
CAVE_GRANITE = 1
CAVE_SANDSTONE = 2
CAVE_BASALT = 3

# Stone — style
STONE_COBBLESTONE = 0
STONE_BRICK = 1
STONE_FLAGSTONE = 2
STONE_OPUS_ROMANO = 3
STONE_FIELDSTONE = 4
STONE_PINWHEEL = 5
STONE_HOPSCOTCH = 6
STONE_CRAZY_PAVING = 7
STONE_ASHLAR = 8

# Stone — Cobblestone sub_pattern (per-style axis)
STONE_COBBLE_HERRINGBONE = 0
STONE_COBBLE_STACK = 1
STONE_COBBLE_RUBBLE = 2
STONE_COBBLE_MOSAIC = 3

# Stone — Brick sub_pattern
STONE_BRICK_RUNNING_BOND = 0
STONE_BRICK_ENGLISH_BOND = 1
STONE_BRICK_FLEMISH_BOND = 2

# Earth — style
EARTH_DIRT = 0
EARTH_GRASS = 1
EARTH_SAND = 2
EARTH_MUD = 3

# Liquid — style
LIQUID_WATER = 0
LIQUID_LAVA = 1

# Special — style
SPECIAL_CHASM = 0
SPECIAL_PIT = 1
SPECIAL_ABYSS = 2
SPECIAL_VOID = 3


def _make_material(
    family: int, style: int, sub_pattern: int, tone: int, seed: int
) -> V5MaterialT:
    m = V5MaterialT()
    m.family = family
    m.style = style
    m.subPattern = sub_pattern
    m.tone = tone
    m.seed = seed
    return m


def material_plain(seed: int = 0) -> V5MaterialT:
    """Plain parchment-white fill (default canvas)."""
    return _make_material(V5MaterialFamily.Plain, 0, 0, 0, seed)


def material_cave(*, style: int = CAVE_LIMESTONE, seed: int = 0) -> V5MaterialT:
    return _make_material(V5MaterialFamily.Cave, style, 0, 0, seed)


def material_wood(
    *,
    species: int = WOOD_OAK,
    layout: int = WOOD_PLANK,
    tone: int = WOOD_MEDIUM,
    seed: int = 0,
) -> V5MaterialT:
    return _make_material(V5MaterialFamily.Wood, species, layout, tone, seed)


def material_stone(
    *,
    style: int = STONE_COBBLESTONE,
    sub_pattern: int = 0,
    tone: int = 0,
    seed: int = 0,
) -> V5MaterialT:
    return _make_material(V5MaterialFamily.Stone, style, sub_pattern, tone, seed)


def material_earth(*, style: int = EARTH_DIRT, seed: int = 0) -> V5MaterialT:
    return _make_material(V5MaterialFamily.Earth, style, 0, 0, seed)


def material_liquid(*, style: int = LIQUID_WATER, seed: int = 0) -> V5MaterialT:
    return _make_material(V5MaterialFamily.Liquid, style, 0, 0, seed)


def material_special(*, style: int = SPECIAL_CHASM, seed: int = 0) -> V5MaterialT:
    return _make_material(V5MaterialFamily.Special, style, 0, 0, seed)


# ── WallMaterial factories ─────────────────────────────────────


def _make_wall_material(
    family: int,
    style: int,
    treatment: int,
    *,
    corner_style: int = CornerStyle.Merlon,
    tone: int = 0,
    seed: int = 0,
) -> V5WallMaterialT:
    wm = V5WallMaterialT()
    wm.family = family
    wm.style = style
    wm.treatment = treatment
    wm.cornerStyle = corner_style
    wm.tone = tone
    wm.seed = seed
    return wm


def wall_material_from_wall_style(
    style: int, *, corner_style: int = CornerStyle.Merlon, seed: int = 0
) -> V5WallMaterialT:
    """Translate a v4 ``WallStyle`` enum value into a ``V5WallMaterial``.

    Closest mapping:
    - ``DungeonInk`` / ``CaveInk`` → Stone family + PlainStroke
    - ``MasonryStone``             → Stone family + Masonry
    - ``MasonryBrick``             → Stone Brick + Masonry
    - ``Partition*``               → respective family + Partition
    - ``Palisade``                 → Wood family + Palisade
    - ``FortificationMerlon``      → Stone family + Fortification
    """
    if style == WallStyle.MasonryBrick:
        return _make_wall_material(
            V5MaterialFamily.Stone,
            STONE_BRICK,
            V5WallTreatment.Masonry,
            corner_style=corner_style,
            seed=seed,
        )
    if style == WallStyle.MasonryStone:
        return _make_wall_material(
            V5MaterialFamily.Stone,
            STONE_ASHLAR,
            V5WallTreatment.Masonry,
            corner_style=corner_style,
            seed=seed,
        )
    if style == WallStyle.PartitionStone:
        return _make_wall_material(
            V5MaterialFamily.Stone,
            STONE_ASHLAR,
            V5WallTreatment.Partition,
            corner_style=corner_style,
            seed=seed,
        )
    if style == WallStyle.PartitionBrick:
        return _make_wall_material(
            V5MaterialFamily.Stone,
            STONE_BRICK,
            V5WallTreatment.Partition,
            corner_style=corner_style,
            seed=seed,
        )
    if style == WallStyle.PartitionWood:
        return _make_wall_material(
            V5MaterialFamily.Wood,
            WOOD_OAK,
            V5WallTreatment.Partition,
            corner_style=corner_style,
            seed=seed,
        )
    if style == WallStyle.Palisade:
        return _make_wall_material(
            V5MaterialFamily.Wood,
            WOOD_OAK,
            V5WallTreatment.Palisade,
            corner_style=corner_style,
            seed=seed,
        )
    if style == WallStyle.FortificationMerlon:
        return _make_wall_material(
            V5MaterialFamily.Stone,
            STONE_ASHLAR,
            V5WallTreatment.Fortification,
            corner_style=corner_style,
            seed=seed,
        )
    # DungeonInk / CaveInk → PlainStroke under Stone family.
    return _make_wall_material(
        V5MaterialFamily.Stone,
        STONE_ASHLAR,
        V5WallTreatment.PlainStroke,
        corner_style=corner_style,
        seed=seed,
    )
