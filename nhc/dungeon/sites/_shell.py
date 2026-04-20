"""Site-level shell composition.

Perimeter wall stamping moved out of every ``_build_*_floor()``.
See ``design/building_interiors.md`` — the building contract is
interior only; the site owns every footprint-boundary tile.

M1 lands the perimeter pass only. M15 extends the signature to
cover entry doors and shared walls between adjacent buildings.
"""

from __future__ import annotations

from typing import Mapping

from nhc.dungeon.model import Level, Terrain, Tile


def compose_shell(
    level: Level,
    building_footprints: Mapping[str, set[tuple[int, int]]],
    *,
    shared_doors: (
        list[tuple[str, str, tuple[int, int]]] | None
    ) = None,
) -> None:
    """Stamp WALL at every 8-neighbour of any building footprint.

    Neighbours that already belong to a footprint are skipped
    (so edge-adjacent footprints share their seam). Neighbours
    that are already non-VOID are preserved. Out-of-bounds
    neighbours are skipped.

    ``shared_doors`` is ``[(from_id, to_id, (x, y)), …]``. Each
    entry stamps a ``door_closed`` feature at ``(x, y)``. Today
    every building floor is its own Level, so the parameter is
    declared for API completeness and exercised via unit calls;
    the town assembler wires tavern↔inn / residential pairs via
    the separate :class:`InteriorDoorLink` teleport mechanism.
    """
    all_footprints: set[tuple[int, int]] = set()
    for tiles in building_footprints.values():
        all_footprints |= tiles

    for (x, y) in all_footprints:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = x + dx, y + dy
                if (nx, ny) in all_footprints:
                    continue
                if not level.in_bounds(nx, ny):
                    continue
                if level.tiles[ny][nx].terrain is Terrain.VOID:
                    level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)

    for (_from_id, _to_id, xy) in shared_doors or ():
        x, y = xy
        if not level.in_bounds(x, y):
            continue
        tile = level.tiles[y][x]
        tile.feature = "door_closed"
