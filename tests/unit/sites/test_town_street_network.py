"""Street network for town surfaces (Phase 2).

Replaces the legacy "every walkable tile is STREET" surface fill
with a routed graph: streets thread between clusters via A* with
wobble penalty, palisade gates re-place at the cluster-bbox-set
midpoint (Q14), and remaining walkable tiles tag as GARDEN
(cluster-internal walkable patches) or FIELD (palisade periphery
between the outer clusters and the wall).

See ``town_redesign_plan.md`` Phase 2 for the design.
"""

from __future__ import annotations

import random
from collections import deque

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites.town import _SIZE_CLASSES, assemble_town


def _street_tiles(site) -> set[tuple[int, int]]:
    walkable = {SurfaceType.STREET}
    return {
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, t in enumerate(row)
        if t.surface_type in walkable
    }


def _walkable_floor_tiles(site) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(site.surface.tiles)
        for x, t in enumerate(row)
        if t.terrain == Terrain.FLOOR
    }


# ── 1. Streets reach all gates ────────────────────────────────


class TestStreetReachability:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_every_gate_reachable_via_street_only(self, size_class):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            gates = site.enclosure.gates
            if len(gates) < 2:
                continue
            streets = _street_tiles(site)
            # BFS from gate 0 across STREET tiles only.
            start = (gates[0][0], gates[0][1])
            # Gate origins may sit on the palisade edge; pick the
            # nearest STREET tile inside the palisade.
            inside = _nearest_street(streets, start)
            assert inside is not None, (
                f"seed={seed} {size_class}: gate {start} has no "
                "STREET neighbour"
            )
            seen = {inside}
            queue: deque[tuple[int, int]] = deque([inside])
            while queue:
                cx, cy = queue.popleft()
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (cx + dx, cy + dy)
                    if nb in streets and nb not in seen:
                        seen.add(nb)
                        queue.append(nb)
            for gx, gy, _ in gates[1:]:
                target = _nearest_street(streets, (gx, gy))
                assert target in seen, (
                    f"seed={seed} {size_class}: gate ({gx},{gy}) "
                    f"unreachable via STREET tiles from gate 0"
                )


def _nearest_street(
    streets: set[tuple[int, int]], anchor: tuple[int, int],
) -> tuple[int, int] | None:
    if not streets:
        return None
    best, best_d = None, 1 << 30
    for tx, ty in streets:
        d = abs(tx - anchor[0]) + abs(ty - anchor[1])
        if d < best_d:
            best, best_d = (tx, ty), d
    return best


# ── 1b. Centerpiece patch reachable via streets ───────────────


class TestCenterpieceReachability:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_centerpiece_patch_connected_to_street_network(
        self, size_class,
    ):
        """Q10's reserved centerpiece patch is stamped as STREET so
        the well / fountain plaza reads as cobblestone, but it
        also has to be *reachable* on the street graph -- a town
        whose fountain is an isolated paved island in the grass
        is a routing bug.
        """
        from nhc.sites.town import (
            _CENTERPIECE_PER_SIZE, _SIZE_CLASSES,
        )
        spec = _CENTERPIECE_PER_SIZE.get(size_class)
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            entry = _any_centerpiece(site)
            if entry is None or spec is None:
                continue
            _, (cx, cy) = entry
            patch = {
                (cx + dx - (spec.patch_dim - spec.feature_dim) // 2,
                 cy + dy - (spec.patch_dim - spec.feature_dim) // 2)
                for dx in range(spec.patch_dim)
                for dy in range(spec.patch_dim)
            }
            streets = _street_tiles(site)
            # A patch tile that has at least one STREET neighbour
            # outside the patch -- i.e. a connector exists.
            connector_found = False
            for (px, py) in patch:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (px + dx, py + dy)
                    if nb in streets and nb not in patch:
                        connector_found = True
                        break
                if connector_found:
                    break
            assert connector_found, (
                f"seed={seed} {size_class}: centerpiece patch "
                f"around ({cx},{cy}) is isolated -- no STREET tile "
                f"adjacent to the patch perimeter"
            )


def _any_centerpiece(site):
    """Inline copy of the centerpiece finder from
    test_town_centerpiece (kept private to avoid cross-module
    imports in the test layer)."""
    for feature in (
        "well", "well_square",
        "fountain", "fountain_square",
        "fountain_large", "fountain_large_square",
        "fountain_cross",
    ):
        for y, row in enumerate(site.surface.tiles):
            for x, tile in enumerate(row):
                if tile.feature == feature:
                    return (feature, (x, y))
    return None


# ── 2. Every cluster touches a street ─────────────────────────


class TestClusterReachability:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_every_cluster_has_a_street_adjacent_tile(
        self, size_class,
    ):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            streets = _street_tiles(site)
            for plan in site.cluster_plans:
                # Walk the cluster bbox perimeter and check at
                # least one tile that is also STREET.
                bx, by = plan.bbox.x, plan.bbox.y
                bx2, by2 = plan.bbox.x2, plan.bbox.y2
                touches = False
                for x in range(bx, bx2):
                    if (x, by) in streets or (x, by2 - 1) in streets:
                        touches = True
                        break
                if not touches:
                    for y in range(by, by2):
                        if (bx, y) in streets or (bx2 - 1, y) in streets:
                            touches = True
                            break
                # Also count "1-tile outside the bbox" because the
                # 1-tile internal buffer puts the street one step
                # past the bbox border for tightly-packed sites.
                if not touches:
                    for x in range(bx - 1, bx2 + 1):
                        for y in range(by - 1, by2 + 1):
                            if (x, y) in streets:
                                touches = True
                                break
                        if touches:
                            break
                assert touches, (
                    f"seed={seed} {size_class}: cluster "
                    f"bbox={plan.bbox} has no STREET neighbour"
                )


# ── 3. No street inside a building footprint ──────────────────


class TestStreetSegregation:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_no_street_inside_building_footprint(self, size_class):
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            footprints: set[tuple[int, int]] = set()
            for b in site.buildings:
                footprints |= b.base_shape.floor_tiles(b.base_rect)
            streets = _street_tiles(site)
            inside = streets & footprints
            assert not inside, (
                f"seed={seed} {size_class}: STREET tiles inside "
                f"building footprints: {sorted(inside)[:5]}"
            )


# ── 4. Walkable tiles classified into STREET / GARDEN / FIELD ─


class TestSurfaceClassification:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_every_walkable_floor_tile_has_a_surface_type(
        self, size_class,
    ):
        allowed = {
            SurfaceType.STREET, SurfaceType.GARDEN, SurfaceType.FIELD,
        }
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            for y, row in enumerate(site.surface.tiles):
                for x, tile in enumerate(row):
                    if tile.terrain != Terrain.FLOOR:
                        continue
                    assert tile.surface_type in allowed, (
                        f"seed={seed} {size_class}: walkable tile "
                        f"({x},{y}) has surface_type "
                        f"{tile.surface_type!r}"
                    )

    @pytest.mark.parametrize("size_class", [
        "village", "town",
    ])
    def test_field_tiles_appear_at_palisade_periphery(
        self, size_class,
    ):
        """Every palisade-using site emits some FIELD tiles --
        the periphery between the outermost clusters and the
        palisade wall. Cities are excluded: the city tier paves
        every walkable tile (FIELD / GARDEN → STREET) so the
        whole fortified courtyard reads as one urban surface."""
        seen_field = False
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            for row in site.surface.tiles:
                for tile in row:
                    if tile.surface_type == SurfaceType.FIELD:
                        seen_field = True
                        break
                if seen_field:
                    break
            if seen_field:
                break
        assert seen_field, (
            f"{size_class}: no FIELD tiles produced across 15 "
            "seeds; palisade periphery should generate some"
        )

    def test_city_paves_palisade_interior(self) -> None:
        """City tier converts every walkable FIELD / GARDEN tile
        **inside the palisade rect** to PAVEMENT so the fortified
        courtyard renders as one paved surface (Ashlar Staggered
        via ``pavement_material``). FIELD tiles in the outer
        2-tile grass ring (where trees / bushes scatter outside
        the wall) survive the post-pass."""
        from nhc.sites.town import _SIZE_CLASSES, _palisade_outer_rect
        config = _SIZE_CLASSES["city"]
        pal = _palisade_outer_rect(config)
        for seed in range(15):
            site = assemble_town(
                "t1", random.Random(seed), size_class="city",
            )
            for y in range(pal.y, pal.y2):
                for x in range(pal.x, pal.x2):
                    tile = site.surface.tiles[y][x]
                    assert tile.surface_type not in (
                        SurfaceType.FIELD, SurfaceType.GARDEN,
                    ), (
                        f"city seed={seed}: palisade-interior tile "
                        f"({x},{y}) carries {tile.surface_type!r}; "
                        f"cities pave the courtyard with PAVEMENT"
                    )


# ── 5. Gate placement (Q14) ───────────────────────────────────


class TestGatePlacement:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_gate_y_within_cluster_bbox_set_extent(
        self, size_class,
    ):
        """Q14: gates align with the y-midpoint of the cluster
        bbox set (with multi-gate distribution). The y must sit
        within the cluster bbox set's y-extent so the street
        threads through the clusters, not above or below them."""
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            if not site.cluster_plans:
                continue
            ys_lo = min(p.bbox.y for p in site.cluster_plans)
            ys_hi = max(p.bbox.y2 for p in site.cluster_plans)
            for gx, gy, _ in site.enclosure.gates:
                assert ys_lo <= gy <= ys_hi, (
                    f"seed={seed} {size_class}: gate y={gy} "
                    f"outside cluster bbox y-extent "
                    f"[{ys_lo}, {ys_hi}]"
                )


# ── 6. Spine width per Q2 ─────────────────────────────────────


class TestSpineWidth:
    def test_town_and_city_emit_two_tile_spine(self):
        """Q2: town/city use a 2-tile-wide main spine. We detect
        this by finding a STREET tile whose 4-neighbours contains
        another STREET tile orthogonally adjacent on at least one
        axis (i.e., a 2-wide street). Hamlet/village are uniform
        1-tile and may not exhibit this pattern reliably; only
        assert presence in town and city."""
        for size_class in ("town", "city"):
            saw_two_wide = False
            for seed in range(15):
                site = assemble_town(
                    "t1", random.Random(seed),
                    size_class=size_class,
                )
                streets = _street_tiles(site)
                for x, y in streets:
                    # Look for a 2x1 or 1x2 STREET cluster.
                    if (x + 1, y) in streets and (
                        x, y + 1
                    ) in streets and (x + 1, y + 1) in streets:
                        saw_two_wide = True
                        break
                if saw_two_wide:
                    break
            assert saw_two_wide, (
                f"{size_class}: no 2x2 STREET block across 15 "
                "seeds; spine should be 2 tiles wide"
            )
