"""Unit tests for the BSP-neighbourhood per-plot fill (Phase 2).

Exercises ``nhc.sites._town_layout.fill_partition`` and its helpers:
area-proportional budget split, service-role bias toward the core
(big-plaza) plot, within-band massing skew, archetype-to-plot-aspect
fit, the spill pool (services never dropped), no-overlap / in-bounds
placement, and determinism.

See design/town_generator.md §3.3-§3.5 (D3/D5/D8/D10, B4, Q1-Q6).
"""

import math
import random
import statistics
from collections import Counter

import pytest

from nhc.dungeon.model import Rect
from nhc.sites._town_bsp import Plaza, Plot, partition_interior
from nhc.sites._town_layout import (
    _packable_area,
    _roll_archetype_for_plot,
    _split_budget,
    fill_partition,
)
from nhc.sites.town import SERVICE_ROLES, _roll_role_slots

SIZE_CLASSES = ("hamlet", "village", "town", "city")

INTERIORS: dict[str, Rect] = {
    "hamlet": Rect(1, 1, 56, 40),
    "village": Rect(5, 5, 64, 50),
    "town": Rect(5, 5, 80, 64),
    "city": Rect(5, 5, 96, 78),
}

COUNTS: dict[str, tuple[int, int]] = {
    "hamlet": (3, 4),
    "village": (5, 7),
    "town": (8, 10),
    "city": (40, 48),
}


def _roster(size_class: str, rng: random.Random) -> list[str]:
    lo, hi = COUNTS[size_class]
    return _roll_role_slots(rng, rng.randint(lo, hi))


def _members(plans):
    return [m for plan in plans for m in plan.members]


def _contains(outer: Rect, inner: Rect) -> bool:
    return (
        inner.x >= outer.x and inner.y >= outer.y
        and inner.x2 <= outer.x2 and inner.y2 <= outer.y2
    )


def _host_plot(partition, rect: Rect):
    for plot in partition.plots:
        if _contains(plot.rect, rect):
            return plot
    return None


def _tier_of(plot) -> str:
    if plot.plaza is None:
        return "edge"
    return "core" if plot.plaza.tier == "big" else "pocket"


# Per-class placement floor (fraction of the rolled roster that must
# land). Small/roomy tiers seat ~everything; the dense city trades a few
# drops for the per-plot speed win and stays inside its historical
# tolerance band (~[34, 46] of a 40-48 roll — B4 / town.py _SIZE_CLASSES).
_PLACEMENT_FLOOR: dict[str, float] = {
    "hamlet": 0.85, "village": 0.85, "town": 0.85, "city": 0.68,
}


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_most_buildings_placed(size_class):
    for seed in range(20):
        rng = random.Random(seed)
        part = partition_interior(INTERIORS[size_class], size_class, rng)
        roles = _roster(size_class, rng)
        plans = fill_partition(part, roles, size_class, rng)
        placed = _members(plans)
        indices = {m.index for m in placed}
        assert len(indices) == len(placed)  # no double placement
        assert len(placed) <= len(roles)
        floor = math.ceil(_PLACEMENT_FLOOR[size_class] * len(roles))
        assert len(placed) >= floor


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_no_building_overlap(size_class):
    for seed in range(12):
        rng = random.Random(seed)
        part = partition_interior(INTERIORS[size_class], size_class, rng)
        roles = _roster(size_class, rng)
        plans = fill_partition(part, roles, size_class, rng)
        rects = [m.rect for m in _members(plans)]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not rects[i].intersects(rects[j])


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_members_within_plots_off_plaza(size_class):
    for seed in range(12):
        rng = random.Random(seed)
        part = partition_interior(INTERIORS[size_class], size_class, rng)
        roles = _roster(size_class, rng)
        plans = fill_partition(part, roles, size_class, rng)
        plaza_rects = [p.plaza.rect for p in part.plots if p.plaza]
        for m in _members(plans):
            assert any(_contains(p.rect, m.rect) for p in part.plots)
            for plaza in plaza_rects:
                assert not m.rect.intersects(plaza)


def test_split_budget_capped_and_area_monotonic():
    plots = [
        Plot(rect=Rect(0, 0, 40, 40)),                      # area 1600
        Plot(rect=Rect(0, 0, 20, 20)),                      # area 400
        Plot(                                               # 900 - 121
            rect=Rect(0, 0, 30, 30),
            plaza=Plaza(rect=Rect(0, 0, 11, 11), tier="big"),
        ),
    ]
    # Roomy roster: budgets sum to n exactly (no cap bites).
    assert sum(_split_budget(plots, 12)) == 12
    # Tight roster: budgets cap below n, the shortfall is the pool (B4).
    budgets = _split_budget(plots, 30)
    assert sum(budgets) <= 30
    for plot, budget in zip(plots, budgets):
        assert budget <= max(1, _packable_area(plot) // 135)
    areas = [_packable_area(p) for p in plots]
    order = sorted(range(len(plots)), key=lambda i: areas[i])
    for smaller, larger in zip(order, order[1:]):
        assert budgets[smaller] <= budgets[larger]


@pytest.mark.parametrize("size_class", ("town", "city"))
def test_services_never_dropped(size_class):
    for seed in range(15):
        rng = random.Random(seed)
        part = partition_interior(INTERIORS[size_class], size_class, rng)
        roles = _roster(size_class, rng)
        plans = fill_partition(part, roles, size_class, rng)
        placed = {m.index for m in _members(plans)}
        services = {
            i for i, r in enumerate(roles) if r in SERVICE_ROLES
        }
        assert services <= placed


def test_service_roles_bias_toward_core_plot():
    core_service = core_total = other_service = other_total = 0
    for seed in range(40):
        rng = random.Random(seed)
        part = partition_interior(INTERIORS["city"], "city", rng)
        roles = _roster("city", rng)
        plans = fill_partition(part, roles, "city", rng)
        for m in _members(plans):
            host = _host_plot(part, m.rect)
            if host is None:
                continue
            is_core = _tier_of(host) == "core"
            is_service = roles[m.index] in SERVICE_ROLES
            if is_core:
                core_total += 1
                core_service += int(is_service)
            else:
                other_total += 1
                other_service += int(is_service)
    core_rate = core_service / max(1, core_total)
    other_rate = other_service / max(1, other_total)
    assert core_rate > other_rate


def test_residential_massing_gradient_core_pocket_edge():
    areas: dict[str, list[int]] = {"core": [], "pocket": [], "edge": []}
    for seed in range(60):
        rng = random.Random(seed)
        part = partition_interior(INTERIORS["city"], "city", rng)
        roles = _roster("city", rng)
        plans = fill_partition(part, roles, "city", rng)
        for m in _members(plans):
            if roles[m.index] != "residential":
                continue
            host = _host_plot(part, m.rect)
            if host is None:
                continue
            areas[_tier_of(host)].append(m.rect.width * m.rect.height)
    mean_core = statistics.mean(areas["core"])
    mean_pocket = statistics.mean(areas["pocket"])
    mean_edge = statistics.mean(areas["edge"])
    assert mean_core > mean_pocket > mean_edge


def test_archetype_fits_plot_aspect():
    # The aspect bias is intentionally SOFT (a strong one towers tall
    # plots — see _ASPECT_BOOST), so it shifts the distribution rather
    # than forcing a single archetype: rows are commoner in wide plots,
    # columns commoner in tall plots, and a square plot favours the
    # courtyard.
    def dist(rect: Rect, n_members: int) -> Counter:
        return Counter(
            _roll_archetype_for_plot(n_members, "city", rect, random.Random(s))
            for s in range(400)
        )

    wide = dist(Rect(0, 0, 60, 20), 3)
    tall = dist(Rect(0, 0, 20, 60), 3)
    square = dist(Rect(0, 0, 40, 40), 4)
    assert wide["row"] > tall["row"]        # rows lean wide
    assert tall["column"] > wide["column"]  # columns lean tall
    assert square.most_common(1)[0][0] == "courtyard"


def test_fill_deterministic():
    part = partition_interior(INTERIORS["city"], "city", random.Random(11))
    roles = _roll_role_slots(random.Random(12), 44)
    plans_a = fill_partition(part, roles, "city", random.Random(13))
    plans_b = fill_partition(part, roles, "city", random.Random(13))

    def key(plans):
        return sorted(
            (m.index, m.rect.x, m.rect.y, m.rect.width, m.rect.height)
            for m in _members(plans)
        )

    assert key(plans_a) == key(plans_b)
