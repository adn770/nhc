"""Material / WallMaterial factories for the v5 emit pipeline.

Returns ``MaterialT`` / ``WallMaterialT`` populated with the
canonical ``(family, style, sub_pattern, tone, seed)`` tuple per
``design/map_ir_v5.md`` §4. Wall factories are named for the
canonical v5 role (``wall_material_plain_stroke``,
``wall_material_masonry``, ``wall_material_partition``,
``wall_material_palisade``, ``wall_material_fortification``) and
take v5 ``(family, style, treatment)`` directly — no v4 enum
translation involved.
"""

from __future__ import annotations

from nhc.rendering.ir._fb.CornerStyle import CornerStyle
from nhc.rendering.ir._fb.Material import MaterialT
from nhc.rendering.ir._fb.MaterialFamily import MaterialFamily
from nhc.rendering.ir._fb.WallMaterial import WallMaterialT
from nhc.rendering.ir._fb.WallTreatment import WallTreatment


# ── Style enum subtables (mirrors design/map_ir_v5.md §4) ──────

# Wood — species axis
WOOD_OAK = 0
WOOD_WALNUT = 1
WOOD_CHERRY = 2
WOOD_PINE = 3
WOOD_WEATHERED = 4
WOOD_MAHOGANY = 5
WOOD_EBONY = 6
WOOD_ASH = 7
WOOD_MAPLE = 8
WOOD_BIRCH = 9
WOOD_TEAK = 10
WOOD_BAMBOO = 11

# Wood — sub_pattern (layout)
WOOD_PLANK = 0
WOOD_BASKETWEAVE = 1
WOOD_PARQUET = 2
WOOD_HERRINGBONE = 3
WOOD_CHEVRON = 4
WOOD_BRICK = 5

# Wood — tone
WOOD_LIGHT = 0
WOOD_MEDIUM = 1
WOOD_DARK = 2
WOOD_CHARRED = 3
WOOD_BLEACHED = 4
WOOD_AGED = 5

# Cave — style
CAVE_LIMESTONE = 0
CAVE_GRANITE = 1
CAVE_SANDSTONE = 2
CAVE_BASALT = 3
CAVE_CRYSTAL = 4
CAVE_CORAL = 5
CAVE_ICE = 6
CAVE_LAVA_ROCK = 7

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
STONE_OPUS_RETICULATUM = 9
STONE_OPUS_SPICATUM = 10

# Stone — Cobblestone sub_pattern (per-style axis)
STONE_COBBLE_HERRINGBONE = 0
STONE_COBBLE_STACK = 1
STONE_COBBLE_RUBBLE = 2
STONE_COBBLE_MOSAIC = 3

# Stone — Brick sub_pattern
STONE_BRICK_RUNNING_BOND = 0
STONE_BRICK_ENGLISH_BOND = 1
STONE_BRICK_FLEMISH_BOND = 2
STONE_BRICK_HEADER_BOND = 3
STONE_BRICK_STACK_BOND = 4

# Stone — Ashlar sub_pattern
STONE_ASHLAR_EVEN_JOINT = 0
STONE_ASHLAR_STAGGERED_JOINT = 1

# Earth — style
EARTH_DIRT = 0
EARTH_GRASS = 1
EARTH_SAND = 2
EARTH_MUD = 3
EARTH_SNOW = 4
EARTH_GRAVEL = 5
EARTH_COBBLE_DIRT = 6
EARTH_CROP_FIELD = 7

# Liquid — style
LIQUID_WATER = 0
LIQUID_LAVA = 1
LIQUID_ACID = 2
LIQUID_SLIME = 3
LIQUID_TAR = 4
LIQUID_BRACKISH = 5

# Special — style
SPECIAL_CHASM = 0
SPECIAL_PIT = 1
SPECIAL_ABYSS = 2
SPECIAL_VOID = 3


def _make_material(
    family: int, style: int, sub_pattern: int, tone: int, seed: int
) -> MaterialT:
    m = MaterialT()
    m.family = family
    m.style = style
    m.subPattern = sub_pattern
    m.tone = tone
    m.seed = seed
    return m


def material_plain(seed: int = 0) -> MaterialT:
    """Plain parchment-white fill (default canvas)."""
    return _make_material(MaterialFamily.Plain, 0, 0, 0, seed)


def material_cave(*, style: int = CAVE_LIMESTONE, seed: int = 0) -> MaterialT:
    return _make_material(MaterialFamily.Cave, style, 0, 0, seed)


def material_wood(
    *,
    species: int = WOOD_OAK,
    layout: int = WOOD_PLANK,
    tone: int = WOOD_MEDIUM,
    seed: int = 0,
) -> MaterialT:
    return _make_material(MaterialFamily.Wood, species, layout, tone, seed)


def material_stone(
    *,
    style: int = STONE_COBBLESTONE,
    sub_pattern: int = 0,
    tone: int = 0,
    seed: int = 0,
) -> MaterialT:
    return _make_material(MaterialFamily.Stone, style, sub_pattern, tone, seed)


def material_earth(*, style: int = EARTH_DIRT, seed: int = 0) -> MaterialT:
    return _make_material(MaterialFamily.Earth, style, 0, 0, seed)


def material_liquid(*, style: int = LIQUID_WATER, seed: int = 0) -> MaterialT:
    return _make_material(MaterialFamily.Liquid, style, 0, 0, seed)


def material_special(*, style: int = SPECIAL_CHASM, seed: int = 0) -> MaterialT:
    return _make_material(MaterialFamily.Special, style, 0, 0, seed)


# ── WallMaterial factories ─────────────────────────────────────


def _make_wall_material(
    family: int,
    style: int,
    treatment: int,
    *,
    corner_style: int = CornerStyle.Merlon,
    tone: int = 0,
    seed: int = 0,
) -> WallMaterialT:
    wm = WallMaterialT()
    wm.family = family
    wm.style = style
    wm.treatment = treatment
    wm.cornerStyle = corner_style
    wm.tone = tone
    wm.seed = seed
    return wm


def wall_material_plain_stroke(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_ASHLAR,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Plain-stroke wall (DungeonInk / CaveInk role)."""
    return _make_wall_material(
        family, style, WallTreatment.PlainStroke,
        corner_style=corner_style, seed=seed,
    )


def wall_material_masonry(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_ASHLAR,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Masonry wall (MasonryStone / MasonryBrick role)."""
    return _make_wall_material(
        family, style, WallTreatment.Masonry,
        corner_style=corner_style, seed=seed,
    )


def wall_material_partition(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_ASHLAR,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Partition wall (PartitionStone / PartitionBrick / PartitionWood)."""
    return _make_wall_material(
        family, style, WallTreatment.Partition,
        corner_style=corner_style, seed=seed,
    )


def wall_material_palisade(
    *,
    family: int = MaterialFamily.Wood,
    style: int = WOOD_OAK,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Palisade enclosure (vertical stake-poles)."""
    return _make_wall_material(
        family, style, WallTreatment.Palisade,
        corner_style=corner_style, seed=seed,
    )


def wall_material_fortification(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_ASHLAR,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Fortification enclosure (crenellated battlement)."""
    return _make_wall_material(
        family, style, WallTreatment.Fortification,
        corner_style=corner_style, seed=seed,
    )


def wall_material_drystone(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_FIELDSTONE,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Drystone wall — fall-through stroke at chunky width."""
    return _make_wall_material(
        family, style, WallTreatment.Drystone,
        corner_style=corner_style, seed=seed,
    )


def wall_material_adobe(
    *,
    family: int = MaterialFamily.Earth,
    style: int = EARTH_DIRT,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Adobe wall — fall-through stroke at medium width with
    earth-toned palette."""
    return _make_wall_material(
        family, style, WallTreatment.Adobe,
        corner_style=corner_style, seed=seed,
    )


def wall_material_wattle_and_daub(
    *,
    family: int = MaterialFamily.Earth,
    style: int = EARTH_MUD,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """WattleAndDaub wall — daub stroke with woven tick overlay."""
    return _make_wall_material(
        family, style, WallTreatment.WattleAndDaub,
        corner_style=corner_style, seed=seed,
    )


def wall_material_iron(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_ASHLAR,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Iron wall — fall-through stroke at thinner width; caller
    picks a metallic-looking family palette for the visual."""
    return _make_wall_material(
        family, style, WallTreatment.Iron,
        corner_style=corner_style, seed=seed,
    )


def wall_material_post_and_rail(
    *,
    family: int = MaterialFamily.Wood,
    style: int = WOOD_OAK,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """PostAndRail farm fence — squared posts at fixed pitch +
    thin connecting rails."""
    return _make_wall_material(
        family, style, WallTreatment.PostAndRail,
        corner_style=corner_style, seed=seed,
    )


def wall_material_hedge(
    *,
    family: int = MaterialFamily.Earth,
    style: int = EARTH_GRASS,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """Hedge fence — chain of foliage circles along the edges."""
    return _make_wall_material(
        family, style, WallTreatment.Hedge,
        corner_style=corner_style, seed=seed,
    )


def wall_material_drystone_low_wall(
    *,
    family: int = MaterialFamily.Stone,
    style: int = STONE_FIELDSTONE,
    corner_style: int = CornerStyle.Merlon,
    seed: int = 0,
) -> WallMaterialT:
    """DrystoneLowWall — short stacked stones along the polygon
    edges; pasture / garden boundary scale."""
    return _make_wall_material(
        family, style, WallTreatment.DrystoneLowWall,
        corner_style=corner_style, seed=seed,
    )
