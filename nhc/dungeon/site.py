"""Site composition: Buildings + walkable surface + optional enclosure.

See ``design/building_generator.md`` section 5 for the full site
vocabulary. A ``Site`` is the hex-level exploration unit returned
by each site assembler (``tower``, ``farm``, ``mansion``, ``keep``,
``town``).
"""

from __future__ import annotations

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
