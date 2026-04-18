"""Site composition: Buildings + walkable surface + optional enclosure.

See ``design/building_generator.md`` section 5 for the full site
vocabulary. A ``Site`` is the hex-level exploration unit returned
by each site assembler (``tower``, ``farm``, ``mansion``, ``keep``,
``town``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nhc.dungeon.building import Building
from nhc.dungeon.model import Level


@dataclass
class Enclosure:
    """Closed outer wall around a Site.

    ``kind`` is ``"fortification"`` for keep-style walls and
    ``"palisade"`` for town-style. ``polygon`` is the enclosure
    vertex list in tile coordinates. ``gates`` is a list of
    ``(x, y, length_tiles)`` specifying gate midpoints along the
    polygon edges.
    """

    kind: str
    polygon: list[tuple[int, int]]
    gates: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class Site:
    """A hex-level exploration site.

    ``buildings`` is the list of :class:`Building` instances that
    make up the site. ``surface`` is the outdoor walkable level
    (street / field / garden tiles live here). ``enclosure`` is
    ``None`` for unwalled sites (tower, farm, mansion).
    """

    id: str
    kind: str
    buildings: list[Building]
    surface: Level
    enclosure: Enclosure | None = None


# ── Assembler dispatcher ─────────────────────────────────────

SITE_KINDS = ("tower", "farm", "mansion", "keep", "town")


def assemble_site(
    kind: str, site_id: str, rng: random.Random,
) -> Site:
    """Dispatch ``kind`` to the matching site assembler.

    Valid ``kind`` values are :data:`SITE_KINDS`. Any other value
    raises ``ValueError``.
    """
    # Deferred imports keep this module cheap to import and avoid
    # circular references back to Building / Level helpers.
    if kind == "tower":
        from nhc.dungeon.sites.tower import assemble_tower
        return assemble_tower(site_id, rng)
    if kind == "farm":
        from nhc.dungeon.sites.farm import assemble_farm
        return assemble_farm(site_id, rng)
    if kind == "mansion":
        from nhc.dungeon.sites.mansion import assemble_mansion
        return assemble_mansion(site_id, rng)
    if kind == "keep":
        from nhc.dungeon.sites.keep import assemble_keep
        return assemble_keep(site_id, rng)
    if kind == "town":
        from nhc.dungeon.sites.town import assemble_town
        return assemble_town(site_id, rng)
    raise ValueError(f"unknown site kind: {kind!r}")
