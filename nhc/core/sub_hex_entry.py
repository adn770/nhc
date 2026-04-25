"""Resolver that maps a SubHexCell's content to an entry route.

Used by the flower view's ``hex_enter`` handler to decide how to
enter the sub-hex the player is currently standing on. There are
four possible outcomes:

- ``("site", kind, tier)`` — every flower feature that produces
  a surface site (towns, keeps, mansions, towers, farms, cottages,
  ruins, temples, mage_residences, plus the sub-hex families
  wayside / clearing / sacred / den / graveyard / campsite /
  orchard). The caller routes through ``Game.enter_site``.
- ``("dungeon", template)`` — cave / hole. No surface site; the
  caller routes straight into the cellular dungeon system via
  ``Game.enter_dungeon``. Cave clusters share Floor 2 the same
  way they did before unification.
- ``("non-enterable", reason)`` — lake, river. Emit a
  feature-specific rejection message.
- ``None`` — the sub-hex is empty; "nothing to enter here."
"""

from __future__ import annotations

from nhc.hexcrawl.model import (
    HexFeatureType,
    MinorFeatureType,
    SubHexCell,
)
from nhc.sites._types import SiteTier


_NON_ENTERABLE_MAJOR: dict[HexFeatureType, str] = {
    HexFeatureType.LAKE: "lake",
    HexFeatureType.RIVER: "river",
}

# Cave / hole features dispatch to the dungeon system directly --
# no surface site (Q1 of the convergence plan). Template strings
# match the ones the dungeon path already keys off of.
_DUNGEON_MAJOR: dict[HexFeatureType, str] = {
    HexFeatureType.CAVE: "procedural:cave",
    HexFeatureType.HOLE: "procedural:cave",
}

# Macro features that produce a surface site. The ``kind`` value
# is the string the unified ``Game.enter_site`` switches on; the
# tier is the assembler's preferred footprint. Towns derive their
# tier from ``cell.dungeon.size_class`` so the four-step
# hamlet/village/town/city scale survives intact.
_MACRO_KIND: dict[HexFeatureType, str] = {
    HexFeatureType.CITY: "town",
    HexFeatureType.VILLAGE: "town",
    HexFeatureType.COMMUNITY: "town",
    HexFeatureType.KEEP: "keep",
    HexFeatureType.TOWER: "tower",
    HexFeatureType.MANSION: "mansion",
    HexFeatureType.FARM: "farm",
    HexFeatureType.COTTAGE: "cottage",
    HexFeatureType.TEMPLE: "temple",
    HexFeatureType.RUIN: "ruin",
    HexFeatureType.GRAVEYARD: "graveyard",
    HexFeatureType.CRYSTALS: "sacred",
    HexFeatureType.STONES: "sacred",
    HexFeatureType.WONDER: "sacred",
    HexFeatureType.PORTAL: "sacred",
}

_MACRO_TIER: dict[HexFeatureType, SiteTier] = {
    HexFeatureType.KEEP: SiteTier.MEDIUM,
    HexFeatureType.TOWER: SiteTier.TINY,
    HexFeatureType.MANSION: SiteTier.MEDIUM,
    HexFeatureType.FARM: SiteTier.SMALL,
    HexFeatureType.COTTAGE: SiteTier.TINY,
    HexFeatureType.TEMPLE: SiteTier.SMALL,
    HexFeatureType.RUIN: SiteTier.TINY,
    HexFeatureType.GRAVEYARD: SiteTier.SMALL,
    HexFeatureType.CRYSTALS: SiteTier.SMALL,
    HexFeatureType.STONES: SiteTier.SMALL,
    HexFeatureType.WONDER: SiteTier.SMALL,
    HexFeatureType.PORTAL: SiteTier.SMALL,
}

# Town size_class -> tier. The middle "town" size_class collapses
# onto HUGE (alongside city); the dispatcher continues to read
# size_class directly when it routes to ``assemble_town`` so the
# "town" gameplay variant is still reachable.
_TOWN_SIZE_CLASS_TO_TIER: dict[str, SiteTier] = {
    "hamlet": SiteTier.MEDIUM,
    "village": SiteTier.LARGE,
    "town": SiteTier.HUGE,
    "city": SiteTier.HUGE,
}

_MINOR_KIND: dict[MinorFeatureType, str] = {
    # Wayside (TINY centerpiece)
    MinorFeatureType.WELL: "wayside",
    MinorFeatureType.SIGNPOST: "wayside",
    # Sacred (SMALL plaza)
    MinorFeatureType.SHRINE: "sacred",
    MinorFeatureType.STANDING_STONE: "sacred",
    MinorFeatureType.CAIRN: "sacred",
    # Settlement (TINY farm; SMALL campsite/orchard)
    MinorFeatureType.FARM: "farm",
    MinorFeatureType.CAMPSITE: "campsite",
    MinorFeatureType.ORCHARD: "orchard",
    # Natural curiosity (TINY clearing)
    MinorFeatureType.MUSHROOM_RING: "clearing",
    MinorFeatureType.HERB_PATCH: "clearing",
    MinorFeatureType.HOLLOW_LOG: "clearing",
    MinorFeatureType.BONE_PILE: "clearing",
    # Animal den (SMALL den-mouth + walled field)
    MinorFeatureType.ANIMAL_DEN: "den",
    MinorFeatureType.LAIR: "den",
    MinorFeatureType.NEST: "den",
    MinorFeatureType.BURROW: "den",
}

_MINOR_TIER: dict[MinorFeatureType, SiteTier] = {
    MinorFeatureType.WELL: SiteTier.TINY,
    MinorFeatureType.SIGNPOST: SiteTier.TINY,
    MinorFeatureType.SHRINE: SiteTier.SMALL,
    MinorFeatureType.STANDING_STONE: SiteTier.SMALL,
    MinorFeatureType.CAIRN: SiteTier.SMALL,
    MinorFeatureType.FARM: SiteTier.TINY,
    MinorFeatureType.CAMPSITE: SiteTier.SMALL,
    MinorFeatureType.ORCHARD: SiteTier.SMALL,
    MinorFeatureType.MUSHROOM_RING: SiteTier.TINY,
    MinorFeatureType.HERB_PATCH: SiteTier.TINY,
    MinorFeatureType.HOLLOW_LOG: SiteTier.TINY,
    MinorFeatureType.BONE_PILE: SiteTier.TINY,
    MinorFeatureType.ANIMAL_DEN: SiteTier.SMALL,
    MinorFeatureType.LAIR: SiteTier.SMALL,
    MinorFeatureType.NEST: SiteTier.SMALL,
    MinorFeatureType.BURROW: SiteTier.SMALL,
}


def resolve_sub_hex_entry(
    sub_cell: SubHexCell,
) -> tuple | None:
    """Map ``sub_cell`` to an entry route, or ``None`` if empty."""
    major = sub_cell.major_feature
    minor = sub_cell.minor_feature

    if major in _NON_ENTERABLE_MAJOR:
        return ("non-enterable", _NON_ENTERABLE_MAJOR[major])

    if major in _DUNGEON_MAJOR:
        return ("dungeon", _DUNGEON_MAJOR[major])

    if major in _MACRO_KIND:
        kind = _MACRO_KIND[major]
        # The DungeonRef on the feature_cell still carries the
        # generator-stamped site_kind for back-compat (e.g. the
        # macro pipeline overrides "town" with the specific site
        # kind for hub cities). When set, it wins.
        if sub_cell.dungeon is not None and sub_cell.dungeon.site_kind:
            kind = sub_cell.dungeon.site_kind
        if kind == "town":
            size_class: str | None = None
            if sub_cell.dungeon is not None:
                size_class = sub_cell.dungeon.size_class
            tier = _TOWN_SIZE_CLASS_TO_TIER.get(
                size_class or "village", SiteTier.LARGE,
            )
        else:
            tier = _MACRO_TIER.get(major, SiteTier.SMALL)
        return ("site", kind, tier)

    if minor in _MINOR_KIND:
        kind = _MINOR_KIND[minor]
        tier = _MINOR_TIER.get(minor, SiteTier.SMALL)
        return ("site", kind, tier)

    return None
