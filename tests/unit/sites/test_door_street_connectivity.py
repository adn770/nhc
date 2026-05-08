"""Settlement door → street connectivity invariant.

Every building door on a settlement surface must have at least
one STREET-tagged tile in its 4-neighbourhood so the player can
step from the door onto the routed network. Without this
invariant a door can land in a GARDEN / FIELD pocket fully
surrounded by other GARDEN / FIELD tiles — visually the door
opens onto grass with no route in or out of the building.

The post-spine connection pass walks every entry in
``site.building_doors``. If the door already has a STREET
4-neighbour (placed by the spine / branch / gate-apron passes),
it's left alone. Otherwise the connector A*-routes a short path
from a walkable 4-neighbour of the door to the nearest existing
STREET tile and stamps every tile on the path as STREET. The
door tile itself is never overwritten — the door bias logic
that picks GARDEN-facing perimeter tiles for L-block elbows and
courtyard east/west members keeps its visual signal.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType
from nhc.sites.town import assemble_town


def _walk_street_component(
    site, start: tuple[int, int],
) -> set[tuple[int, int]]:
    """4-connected flood-fill on STREET tiles starting at ``start``."""
    surface = site.surface
    if not surface.in_bounds(*start):
        return set()
    if surface.tiles[start[1]][start[0]].surface_type is not SurfaceType.STREET:
        return set()
    seen: set[tuple[int, int]] = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen:
                continue
            if not surface.in_bounds(nx, ny):
                continue
            if surface.tiles[ny][nx].surface_type is not SurfaceType.STREET:
                continue
            seen.add((nx, ny))
            stack.append((nx, ny))
    return seen


def _door_street_neighbour(
    site, door: tuple[int, int],
) -> tuple[int, int] | None:
    """Return the first 4-neighbour of ``door`` whose surface
    tile is ``SurfaceType.STREET``, or ``None`` if no neighbour
    is on the network. Door tiles themselves carry the door
    bias's chosen surface_type (often GARDEN), so the connector
    invariant is anchored to the 4-neighbourhood, not the door
    tile itself."""
    sx, sy = door
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = sx + dx, sy + dy
        if not site.surface.in_bounds(nx, ny):
            continue
        if site.surface.tiles[ny][nx].surface_type is SurfaceType.STREET:
            return (nx, ny)
    return None


def _all_street_tiles(site) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for y, row in enumerate(site.surface.tiles):
        for x, tile in enumerate(row):
            if tile.surface_type is SurfaceType.STREET:
                out.add((x, y))
    return out


class TestEveryDoorHasStreetNeighbour:
    """Each door must have at least one ``SurfaceType.STREET``
    tile in its 4-neighbourhood so the player can step from the
    door directly onto the routed network. The door tile itself
    keeps whatever surface_type the door bias picked (GARDEN for
    L-block elbows / courtyard E-W faces, STREET / FIELD
    elsewhere) — the connector pass adds adjacency without
    overwriting the door tile."""

    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_every_door_has_street_4_neighbour(
        self, size_class,
    ) -> None:
        for seed in range(15):
            site = assemble_town(
                f"t_{size_class}_seed{seed}",
                random.Random(seed),
                size_class=size_class,
            )
            for (sx, sy), (bid, _bx, _by) in (
                site.building_doors.items()
            ):
                neighbours = (
                    (sx - 1, sy), (sx + 1, sy),
                    (sx, sy - 1), (sx, sy + 1),
                )
                has_street = False
                for nx, ny in neighbours:
                    if not site.surface.in_bounds(nx, ny):
                        continue
                    if site.surface.tiles[ny][nx].surface_type is SurfaceType.STREET:
                        has_street = True
                        break
                assert has_street, (
                    f"{size_class} seed={seed}: door of {bid} at "
                    f"({sx}, {sy}) has no STREET tile in its "
                    f"4-neighbourhood"
                )


class TestMostDoorsReachMainStreetNetwork:
    """Soft invariant: most doors share the main connected STREET
    component (the one containing the gates / centerpiece
    spine). Doors trapped in walkable pockets that the cluster
    packer fully encloses with buildings still satisfy the
    per-door "is STREET" invariant via a stub stamp, but form
    their own sub-component. Pin a 50% lower bound — strict
    connectivity would require modifying the cluster packer to
    avoid enclosing walkable pockets, which is out of scope."""

    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_majority_of_doors_share_largest_component(
        self, size_class,
    ) -> None:
        for seed in range(15):
            site = assemble_town(
                f"t_{size_class}_seed{seed}",
                random.Random(seed),
                size_class=size_class,
            )
            doors = list(site.building_doors.keys())
            if not doors:
                continue
            # Anchor each door to its STREET 4-neighbour, then
            # collect the unique STREET components those anchors
            # belong to.
            components: list[set[tuple[int, int]]] = []
            anchors: list[tuple[int, int] | None] = []
            for sxy in doors:
                nb = _door_street_neighbour(site, sxy)
                anchors.append(nb)
                if nb is None:
                    continue
                if any(nb in c for c in components):
                    continue
                comp = _walk_street_component(site, nb)
                components.append(comp)
            if not components:
                continue
            largest = max(components, key=len)
            in_largest = sum(
                1 for nb in anchors if nb is not None and nb in largest
            )
            ratio = in_largest / len(doors)
            assert ratio >= 0.50, (
                f"{size_class} seed={seed}: only {in_largest}/"
                f"{len(doors)} ({ratio:.2f}) doors land adjacent "
                f"to the largest STREET component"
            )
