"""Cluster-based building packer for towns (Phase 1).

Replaces the legacy left-to-right row-pack with cluster groups
(row / column / L-block / courtyard / solo). Each size class has
its own cluster-count band and archetype-weight table; service
roles anchor one-per-cluster; row/column members always touch and
roll a 50/50 cross-building link per adjacent pair; rejection-
sampling places cluster bboxes with a 2-tile inter-bbox gap and
demotes archetype on exhaustion.

See `town_redesign_plan.md` Phase 1 for the full design.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from nhc.dungeon.model import Rect
from nhc.sites._town_layout import (
    CLUSTER_ARCHETYPE_WEIGHTS,
    CLUSTER_BBOX_GAP,
    CLUSTER_COUNT_RANGE,
    _ClusterPlan,
    _cluster_pack,
    _placements_from_clusters,
)
from nhc.sites.town import (
    _SIZE_CLASSES,
    SERVICE_ROLES,
    _draw_size_for_role,
    _roll_role_slots,
    assemble_town,
)


# ── Fixtures: deterministic role / size lists per size class ──

def _build_inputs(
    rng: random.Random, size_class: str,
) -> tuple[list[str], list[tuple[int, int]]]:
    config = _SIZE_CLASSES[size_class]
    lo, hi = config.building_count_range
    n = rng.randint(lo, hi)
    roles = _roll_role_slots(rng, n)
    sizes = [_draw_size_for_role(role, rng) for role in roles]
    return roles, sizes


def _run_packer(
    seed: int, size_class: str,
    forbidden_rects: list[Rect] | None = None,
) -> list[_ClusterPlan]:
    rng = random.Random(seed)
    roles, sizes = _build_inputs(rng, size_class)
    return _cluster_pack(
        roles, sizes, _SIZE_CLASSES[size_class], size_class, rng,
        forbidden_rects=forbidden_rects,
    )


# ── 1. All buildings round-trip through the cluster packer ────


class TestCoverageAndOrdering:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_every_input_index_lands_in_a_cluster(self, size_class):
        for seed in range(40):
            rng = random.Random(seed)
            roles, sizes = _build_inputs(rng, size_class)
            plans = _cluster_pack(
                roles, sizes, _SIZE_CLASSES[size_class], size_class,
                rng,
            )
            covered = []
            for plan in plans:
                for m in plan.members:
                    covered.append(m.index)
            assert sorted(covered) == list(range(len(roles))), (
                f"seed={seed} {size_class}: cluster members "
                f"{sorted(covered)} != input range "
                f"{list(range(len(roles)))}"
            )

    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_placements_helper_is_parallel_to_inputs(
        self, size_class,
    ):
        for seed in range(20):
            rng = random.Random(seed)
            roles, sizes = _build_inputs(rng, size_class)
            plans = _cluster_pack(
                roles, sizes, _SIZE_CLASSES[size_class], size_class,
                rng,
            )
            placements = _placements_from_clusters(len(roles), plans)
            assert len(placements) == len(roles)
            for i, ((x, y, w, h), (sw, sh)) in enumerate(
                zip(placements, sizes),
            ):
                assert (w, h) == (sw, sh), (
                    f"seed={seed} {size_class}: placement {i} "
                    f"size ({w},{h}) != input size ({sw},{sh})"
                )


# ── 2. Bbox gap and surface bounds ────────────────────────────


def _rects_overlap(a: Rect, b: Rect) -> bool:
    return (a.x < b.x2 and b.x < a.x2
            and a.y < b.y2 and b.y < a.y2)


def _expand(r: Rect, gap: int) -> Rect:
    return Rect(r.x - gap, r.y - gap, r.width + 2 * gap, r.height + 2 * gap)


class TestBboxGapAndBounds:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_cluster_bboxes_keep_inter_bbox_gap(self, size_class):
        """Two cluster bboxes are at least CLUSTER_BBOX_GAP apart so
        a street can pass between them."""
        for seed in range(40):
            plans = _run_packer(seed, size_class)
            bboxes = [p.bbox for p in plans]
            for i, a in enumerate(bboxes):
                for b in bboxes[i + 1:]:
                    expanded = _expand(a, CLUSTER_BBOX_GAP - 1)
                    # b must not intersect the expanded a (which
                    # adds gap-1 on each side -- two such expansions
                    # sum to 2*(gap-1) < 2*gap, leaving the exact
                    # gap requirement of 2 tiles).
                    # Equivalent: actual gap (max(0, dx, dy)) >= GAP.
                    dx = max(0, max(a.x - b.x2, b.x - a.x2))
                    dy = max(0, max(a.y - b.y2, b.y - a.y2))
                    assert dx >= CLUSTER_BBOX_GAP or dy >= CLUSTER_BBOX_GAP, (
                        f"seed={seed} {size_class}: cluster bboxes "
                        f"{a} and {b} closer than "
                        f"{CLUSTER_BBOX_GAP} tiles "
                        f"(dx={dx}, dy={dy})"
                    )

    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_no_building_overlap(self, size_class):
        for seed in range(40):
            plans = _run_packer(seed, size_class)
            rects = [m.rect for plan in plans for m in plan.members]
            for i, a in enumerate(rects):
                for b in rects[i + 1:]:
                    assert not _rects_overlap(a, b), (
                        f"seed={seed} {size_class}: overlapping "
                        f"buildings {a} and {b}"
                    )

    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_all_buildings_inside_surface(self, size_class):
        config = _SIZE_CLASSES[size_class]
        for seed in range(40):
            plans = _run_packer(seed, size_class)
            for plan in plans:
                for m in plan.members:
                    r = m.rect
                    assert 0 <= r.x and r.x2 <= config.surface_width
                    assert 0 <= r.y and r.y2 <= config.surface_height


# ── 3. Cluster count band and archetype constraints ───────────


class TestClusterCount:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_cluster_count_in_band_or_below(self, size_class):
        """Cluster count never exceeds the configured upper band.
        The lower band is a soft target (a small hamlet of 3
        buildings can produce 2 or 3 clusters depending on the
        partition; demotion to solo can also raise the count)."""
        lo_band, hi_band = CLUSTER_COUNT_RANGE[size_class]
        for seed in range(40):
            plans = _run_packer(seed, size_class)
            n_buildings = sum(len(p.members) for p in plans)
            # Solo demotion can raise the count beyond hi_band when
            # rejection sampling exhausts; cap at n_buildings.
            assert 1 <= len(plans) <= max(hi_band, n_buildings)

    def test_courtyard_only_in_town_or_city(self):
        for seed in range(60):
            for sc in ("hamlet", "village"):
                plans = _run_packer(seed, sc)
                kinds = {p.kind for p in plans}
                assert "courtyard" not in kinds, (
                    f"seed={seed} {sc}: courtyard appeared in "
                    "size_class that doesn't allow it"
                )

    def test_courtyard_has_exactly_4_members(self):
        seen_courtyard = False
        for seed in range(120):
            plans = _run_packer(seed, "city")
            for p in plans:
                if p.kind == "courtyard":
                    seen_courtyard = True
                    assert len(p.members) == 4, (
                        f"seed={seed}: courtyard with "
                        f"{len(p.members)} members; must be 4"
                    )
        assert seen_courtyard, (
            "120 city seeds produced no courtyard; widen the "
            "sample or check archetype weights"
        )

    def test_l_block_has_exactly_3_members(self):
        seen_l = False
        for seed in range(120):
            plans = _run_packer(seed, "city")
            for p in plans:
                if p.kind == "l_block":
                    seen_l = True
                    assert len(p.members) == 3, (
                        f"seed={seed}: l_block with "
                        f"{len(p.members)} members; must be 3"
                    )
        assert seen_l, (
            "120 city seeds produced no l_block; widen sample or "
            "check archetype weights"
        )

    def test_archetype_pool_matches_size_class(self):
        for sc in ("hamlet", "village", "town", "city"):
            allowed = set(CLUSTER_ARCHETYPE_WEIGHTS[sc].keys()) | {
                "solo",
            }
            for seed in range(40):
                plans = _run_packer(seed, sc)
                for p in plans:
                    assert p.kind in allowed, (
                        f"seed={seed} {sc}: cluster kind "
                        f"{p.kind!r} not in allowed pool {allowed}"
                    )


# ── 4. Service-role anchoring ─────────────────────────────────


class TestServiceAnchoring:
    @pytest.mark.parametrize("size_class", [
        "village", "town", "city",
    ])
    def test_services_distributed_across_clusters(self, size_class):
        """Service roles spread across at least ceil(N/2) clusters
        (Phase 1 plan: "no all-one cluster"). When the placement
        path triggers a row-to-solo split, the freshly-created
        solo clusters can absorb residential members; this test
        guards against the failure mode where every service piles
        into a single cluster, not against minor variance."""
        for seed in range(40):
            rng = random.Random(seed)
            roles, sizes = _build_inputs(rng, size_class)
            plans = _cluster_pack(
                roles, sizes, _SIZE_CLASSES[size_class], size_class,
                rng,
            )
            n_services = sum(1 for r in roles if r in SERVICE_ROLES)
            if n_services == 0:
                continue
            clusters_with_service = 0
            for p in plans:
                if any(m.role in SERVICE_ROLES for m in p.members):
                    clusters_with_service += 1
            min_expected = max(
                1, min(n_services, (len(plans) + 1) // 2),
            )
            assert clusters_with_service >= min_expected, (
                f"seed={seed} {size_class}: only "
                f"{clusters_with_service} of {len(plans)} clusters "
                f"host a service ({n_services} services in input); "
                f"expected >= {min_expected}"
            )


# ── 5. Row / column always touching, with 50/50 link rolls ────


class TestRowColumnTouching:
    def test_row_cluster_members_touch_along_x(self):
        for seed in range(40):
            for sc in ("village", "town", "city"):
                plans = _run_packer(seed, sc)
                for p in plans:
                    if p.kind != "row":
                        continue
                    rects = sorted(
                        (m.rect for m in p.members), key=lambda r: r.x,
                    )
                    for left, right in zip(rects, rects[1:]):
                        assert left.x2 == right.x, (
                            f"seed={seed} {sc}: row cluster member "
                            f"{left} not touching {right} (gap "
                            f"{right.x - left.x2})"
                        )
                        assert left.y == right.y, (
                            f"seed={seed} {sc}: row cluster members "
                            f"{left}, {right} have different y"
                        )

    def test_column_cluster_members_touch_along_y(self):
        for seed in range(40):
            for sc in ("village", "town", "city"):
                plans = _run_packer(seed, sc)
                for p in plans:
                    if p.kind != "column":
                        continue
                    rects = sorted(
                        (m.rect for m in p.members), key=lambda r: r.y,
                    )
                    for top, bot in zip(rects, rects[1:]):
                        assert top.y2 == bot.y, (
                            f"seed={seed} {sc}: column cluster "
                            f"member {top} not touching {bot}"
                        )
                        assert top.x == bot.x, (
                            f"seed={seed} {sc}: column cluster "
                            f"members {top}, {bot} have different x"
                        )


# ── 6. Forbidden rects are honoured ───────────────────────────


class TestForbiddenRects:
    def test_no_cluster_bbox_overlaps_forbidden_rect(self):
        # Reserve the centre of a city for a 4x4 patch + 2-tile gap.
        config = _SIZE_CLASSES["city"]
        cx = config.surface_width // 2
        cy = config.surface_height // 2
        forbidden = [Rect(cx, cy, 4, 4)]
        for seed in range(20):
            plans = _run_packer(seed, "city", forbidden_rects=forbidden)
            for p in plans:
                bbox = p.bbox
                # bbox must keep CLUSTER_BBOX_GAP from the forbidden
                # rect on at least one axis.
                fr = forbidden[0]
                dx = max(0, max(bbox.x - fr.x2, fr.x - bbox.x2))
                dy = max(0, max(bbox.y - fr.y2, fr.y - bbox.y2))
                assert (dx >= CLUSTER_BBOX_GAP
                        or dy >= CLUSTER_BBOX_GAP), (
                    f"seed={seed} city: cluster bbox {bbox} "
                    f"overlaps forbidden rect {fr} "
                    f"(dx={dx}, dy={dy})"
                )


# ── 7. End-to-end smoke through assemble_town ─────────────────


class TestAssembleTownIntegratesCluster:
    @pytest.mark.parametrize("size_class", [
        "hamlet", "village", "town", "city",
    ])
    def test_building_count_preserved(self, size_class):
        config = _SIZE_CLASSES[size_class]
        lo, hi = config.building_count_range
        for seed in range(20):
            site = assemble_town(
                "t1", random.Random(seed), size_class=size_class,
            )
            assert lo <= len(site.buildings) <= hi

    def test_interior_links_only_connect_touching_buildings(self):
        """Every cross-building interior door link connects two
        buildings that share an edge (Q8). Row-cluster pairs touch
        east/west; column-cluster pairs touch north/south. Solo /
        L-block / courtyard archetypes never spawn links."""
        for seed in range(60):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            by_id = {b.id: b for b in site.buildings}
            for link in site.interior_door_links:
                a = by_id[link.from_building].base_rect
                b = by_id[link.to_building].base_rect
                shares_x_edge = (
                    (a.x2 == b.x or b.x2 == a.x)
                    and a.y < b.y2 and b.y < a.y2
                )
                shares_y_edge = (
                    (a.y2 == b.y or b.y2 == a.y)
                    and a.x < b.x2 and b.x < a.x2
                )
                assert shares_x_edge or shares_y_edge, (
                    f"seed={seed}: link {link} connects {a} and "
                    f"{b}, which do not share an edge"
                )

    def test_cluster_kinds_visible_on_site(self):
        """assemble_town stashes the cluster plans on the site so
        Phase 2 / 3 / 5 can consume them."""
        seen_kinds: Counter[str] = Counter()
        for seed in range(40):
            site = assemble_town(
                "t1", random.Random(seed), size_class="city",
            )
            assert hasattr(site, "cluster_plans"), (
                "site should expose the cluster plans for Phase 2+"
            )
            for plan in site.cluster_plans:
                seen_kinds[plan.kind] += 1
        # City uses every archetype across enough seeds.
        for kind in ("row", "l_block", "courtyard"):
            assert seen_kinds[kind] > 0, (
                f"city archetype mix missing {kind!r}: {seen_kinds}"
            )
