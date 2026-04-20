"""Multi-floor Building primitive for the building generator.

See ``design/building_generator.md`` sections 3-4 for the full
design. A ``Building`` owns a list of ``Level`` floors that share a
single base shape, plus the cross-floor stair graph and an optional
ground-floor descent into a subterranean dungeon.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nhc.dungeon.model import Level, Rect, RoomShape
from nhc.hexcrawl.model import DungeonRef


@dataclass
class StairLink:
    """Connects a tile on one floor to a tile on another.

    ``to_floor`` is an ``int`` for in-building floors (index into
    ``Building.floors``) or a ``DungeonRef`` for ground-floor
    descents into a subterranean dungeon.
    """

    from_floor: int
    to_floor: int | DungeonRef
    from_tile: tuple[int, int]
    to_tile: tuple[int, int]


@dataclass
class Building:
    """Multi-floor structure with a base shape shared across floors.

    Invariants (checked by :meth:`validate`):

    - ``stair_links`` indices stay inside ``floors``.
    - In-building links connect adjacent floors (``|from - to| == 1``).
    - Descent links originate from floor 0 (the ground floor).

    The shared-footprint invariant (every floor's perimeter matches
    ``shared_perimeter()``) is checked at generation time in a later
    milestone; this class provides the helper but does not enforce
    it against tile data here.
    """

    id: str
    base_shape: RoomShape
    base_rect: Rect
    floors: list[Level] = field(default_factory=list)
    stair_links: list[StairLink] = field(default_factory=list)
    descent: DungeonRef | None = None
    wall_material: str = "brick"     # brick | stone | dungeon | adobe | wood
    interior_floor: str = "stone"    # stone | wood | earth
    # Interior-wall material — picks the line color for the SVG
    # interior-wall overlay. See design/building_interiors.md.
    interior_wall_material: str = "stone"   # wood | stone | brick
    # Optional roof-material marker used by rendering for flavour
    # variants (e.g. forest watchtower wood cap) -- None means "no
    # explicit roof style requested; renderer picks the default".
    roof_material: str | None = None

    @property
    def ground(self) -> Level:
        """Return the ground floor (``floors[0]``)."""
        if not self.floors:
            raise IndexError("Building has no floors")
        return self.floors[0]

    def shared_perimeter(self) -> set[tuple[int, int]]:
        """Perimeter tile set shared by every floor in the building."""
        return self.base_shape.perimeter_tiles(self.base_rect)

    def validate(self) -> None:
        """Raise ``ValueError`` if stair-link invariants are violated."""
        n = len(self.floors)
        for link in self.stair_links:
            if not 0 <= link.from_floor < n:
                raise ValueError(
                    f"stair from_floor {link.from_floor} out of "
                    f"range [0, {n})"
                )
            if isinstance(link.to_floor, int):
                if not 0 <= link.to_floor < n:
                    raise ValueError(
                        f"stair to_floor {link.to_floor} out of "
                        f"range [0, {n})"
                    )
                if abs(link.from_floor - link.to_floor) != 1:
                    raise ValueError(
                        f"stair link {link.from_floor}->"
                        f"{link.to_floor} skips floors"
                    )
            else:
                if link.from_floor != 0:
                    raise ValueError(
                        "descent stair must originate from the "
                        "ground floor (floor 0)"
                    )
