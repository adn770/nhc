"""Resolver that maps a SubHexCell's content to an entry route.

Used by the flower view's ``hex_enter`` handler to decide how to
enter the sub-hex the player is currently standing on. There are
four possible outcomes:

- ``("bespoke", site_kind)`` — the feature has a hand-tuned macro
  generator (town, keep, tower, mansion, farm, cottage, ruin,
  temple, cave). Route through the existing macro site pipeline.
- ``("family", family_name, feature)`` — handled by one of the six
  family generators in ``nhc/hexcrawl/sub_hex_sites.py``.
- ``("non-enterable", reason)`` — lake, river. The caller should
  emit a feature-specific rejection message.
- ``None`` — the sub-hex is empty; "nothing to enter here."
"""

from __future__ import annotations

from nhc.hexcrawl.model import (
    HexFeatureType,
    MinorFeatureType,
    SubHexCell,
)


# Macro features with hand-tuned bespoke generators. ``site_kind``
# is the string the existing macro pipeline passes to
# ``Game._enter_walled_site`` / sibling methods.
_BESPOKE_MAJOR: dict[HexFeatureType, str] = {
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
    HexFeatureType.CAVE: "cave",
    HexFeatureType.HOLE: "cave",
}

_NON_ENTERABLE_MAJOR: dict[HexFeatureType, str] = {
    HexFeatureType.LAKE: "lake",
    HexFeatureType.RIVER: "river",
}

# Major features that route through a family generator (no bespoke
# path). ``graveyard`` is handled by the new Undead family;
# ``crystals/stones/wonder/portal`` by Sacred.
_FAMILY_MAJOR: dict[HexFeatureType, str] = {
    HexFeatureType.GRAVEYARD: "undead",
    HexFeatureType.CRYSTALS: "sacred",
    HexFeatureType.STONES: "sacred",
    HexFeatureType.WONDER: "sacred",
    HexFeatureType.PORTAL: "sacred",
}

_FAMILY_MINOR: dict[MinorFeatureType, str] = {
    # Wayside
    MinorFeatureType.WELL: "wayside",
    MinorFeatureType.SIGNPOST: "wayside",
    # Sacred
    MinorFeatureType.SHRINE: "sacred",
    MinorFeatureType.STANDING_STONE: "sacred",
    MinorFeatureType.CAIRN: "sacred",
    # Inhabited settlement
    MinorFeatureType.FARM: "inhabited_settlement",
    MinorFeatureType.CAMPSITE: "inhabited_settlement",
    MinorFeatureType.ORCHARD: "inhabited_settlement",
    # Natural curiosity
    MinorFeatureType.MUSHROOM_RING: "natural_curiosity",
    MinorFeatureType.HERB_PATCH: "natural_curiosity",
    MinorFeatureType.HOLLOW_LOG: "natural_curiosity",
    MinorFeatureType.BONE_PILE: "natural_curiosity",
    # Animal den
    MinorFeatureType.ANIMAL_DEN: "animal_den",
    MinorFeatureType.LAIR: "animal_den",
    MinorFeatureType.NEST: "animal_den",
    MinorFeatureType.BURROW: "animal_den",
}


def resolve_sub_hex_entry(
    sub_cell: SubHexCell,
) -> tuple | None:
    """Map ``sub_cell`` to an entry route, or ``None`` if empty."""
    major = sub_cell.major_feature
    minor = sub_cell.minor_feature

    if major in _NON_ENTERABLE_MAJOR:
        return ("non-enterable", _NON_ENTERABLE_MAJOR[major])

    if major in _BESPOKE_MAJOR:
        # The ref on the sub-hex tells the pipeline the site_kind,
        # but we keep the resolver a pure function of major so the
        # dispatcher doesn't need a dungeon to dispatch.
        site_kind = _BESPOKE_MAJOR[major]
        if sub_cell.dungeon is not None and sub_cell.dungeon.site_kind:
            site_kind = sub_cell.dungeon.site_kind
        return ("bespoke", site_kind)

    if major in _FAMILY_MAJOR:
        return ("family", _FAMILY_MAJOR[major], major)

    if minor in _FAMILY_MINOR:
        return ("family", _FAMILY_MINOR[minor], minor)

    return None
