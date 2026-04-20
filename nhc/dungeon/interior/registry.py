"""Per-archetype tuning surface.

See ``design/building_interiors.md`` section "Declarative
archetype config". Every knob a site assembler needs is looked
up by archetype name — tweak values here, rerun tests, no code
changes required.

M13 introduces the size-related fields used by town packing;
M14 extends the spec with partitioner / material / shared-door
role pairs and wires every site assembler through this registry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArchetypeSpec:
    """Per-archetype tunables.

    ``size_range`` is the bounding-rect width / height range (both
    drawn from this range independently). ``shape_pool`` names the
    :class:`~nhc.dungeon.model.RoomShape` classes the building may
    take; site assemblers resolve the name to a shape instance.
    """

    size_range: tuple[int, int] = (5, 7)
    shape_pool: tuple[str, ...] = ("rect",)
    partitioner: str = "single_room"
    bsp_mode: str = "doorway"              # "doorway" | "corridor"
    sector_mode: str = "simple"            # "simple" | "enriched"
    min_room: int = 3
    padding: int = 1
    corridor_width: int = 1
    interior_wall_material: str = "stone"  # wood | stone | brick
    locked_door_rate: float = 0.0


ARCHETYPE_CONFIG: dict[str, ArchetypeSpec] = {
    "tavern": ArchetypeSpec(
        size_range=(13, 16), shape_pool=("rect", "l"),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1,
        interior_wall_material="wood",
    ),
    "inn": ArchetypeSpec(
        size_range=(13, 16), shape_pool=("rect", "l"),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1,
        interior_wall_material="wood",
    ),
    "shop": ArchetypeSpec(
        size_range=(10, 12), shape_pool=("rect",),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1,
        interior_wall_material="brick",
        locked_door_rate=0.08,
    ),
    "temple": ArchetypeSpec(
        size_range=(14, 16), shape_pool=("rect",),
        partitioner="temple",
        interior_wall_material="stone",
    ),
    "training": ArchetypeSpec(
        size_range=(9, 11), shape_pool=("rect", "l"),
        partitioner="rect_bsp", bsp_mode="doorway",
        min_room=3, padding=1,
        interior_wall_material="brick",
    ),
    "residential": ArchetypeSpec(
        size_range=(7, 9), shape_pool=("rect", "l"),
        partitioner="divided",
        interior_wall_material="wood",
    ),
    "stable": ArchetypeSpec(
        size_range=(5, 7), shape_pool=("rect",),
        partitioner="single_room",
        interior_wall_material="wood",
    ),
    "cottage": ArchetypeSpec(
        size_range=(7, 9), shape_pool=("rect", "l"),
        partitioner="divided",
        interior_wall_material="wood",
    ),
    "keep": ArchetypeSpec(
        partitioner="rect_bsp", bsp_mode="corridor",
        min_room=3, padding=1, corridor_width=2,
        interior_wall_material="stone",
    ),
    "mansion": ArchetypeSpec(
        partitioner="rect_bsp", bsp_mode="corridor",
        min_room=3, padding=1, corridor_width=2,
        interior_wall_material="stone",
    ),
    "tower_square": ArchetypeSpec(
        size_range=(7, 11), shape_pool=("rect",),
        partitioner="divided",
        interior_wall_material="stone",
    ),
    "tower_circle": ArchetypeSpec(
        size_range=(7, 11), shape_pool=("circle",),
        partitioner="sector", sector_mode="simple",
        interior_wall_material="stone",
    ),
    "mage_residence": ArchetypeSpec(
        size_range=(9, 13), shape_pool=("octagon", "circle"),
        partitioner="sector", sector_mode="enriched",
        interior_wall_material="stone",
    ),
    "ruin": ArchetypeSpec(
        partitioner="single_room",
        interior_wall_material="stone",
    ),
    "farm_main": ArchetypeSpec(
        size_range=(7, 10), shape_pool=("rect", "l"),
        partitioner="divided",
        interior_wall_material="wood",
    ),
}


# Pairs of archetypes that enable cross-building door links (M15).
SHARED_DOOR_PAIRS: list[tuple[str, str]] = [
    ("tavern", "inn"),
    ("residential", "residential"),
]


def get(archetype: str) -> ArchetypeSpec:
    """Return the :class:`ArchetypeSpec` for ``archetype``.

    Raises :class:`KeyError` on unknown archetype — no silent
    fallback. See ``design/building_interiors.md`` — loud failure
    is the intended behavior.
    """
    return ARCHETYPE_CONFIG[archetype]
