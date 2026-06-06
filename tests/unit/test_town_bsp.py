"""Unit tests for the shallow BSP town partitioner (Phase 1).

Pure-geometry checks for ``nhc.sites._town_bsp.partition_interior``:
leaf-count targets (leaves = cuts + 1), big/small plaza reservation
carved out of host leaves, min-plot floor, partition-of-unity,
determinism, and the special single-plot / village-auto-shrink paths.

See design/town_generator.md §3.1-§3.2 (D2, D7, B1, B2, Q6).
"""

import random

import pytest

from nhc.dungeon.model import Rect
from nhc.sites._town_bsp import (
    MIN_PLOT_DIM,
    _BIG_PLAZA_DIM,
    _LEAF_TARGET_RANGE,
    _SMALL_PLAZA_DIM,
    partition_interior,
)

SIZE_CLASSES = ("hamlet", "village", "town", "city")

# Representative buildable interiors, mirroring ``_buildable_bounds``
# for each size class (palisade outer − ring − padding). Exact values
# don't matter for the partitioner; only that they're production-scale.
INTERIORS: dict[str, Rect] = {
    "hamlet": Rect(1, 1, 56, 40),
    "village": Rect(5, 5, 64, 50),
    "town": Rect(5, 5, 80, 64),
    "city": Rect(5, 5, 96, 78),
}

# Expected plaza tier counts per size class (design D7).
PLAZA_COUNTS: dict[str, tuple[int, int]] = {
    # size_class: (big, small)
    "hamlet": (0, 1),
    "village": (1, 0),
    "town": (1, 1),
    "city": (1, 2),
}


def _tiles(rect: Rect) -> set[tuple[int, int]]:
    return {
        (x, y)
        for x in range(rect.x, rect.x2)
        for y in range(rect.y, rect.y2)
    }


def _all_plazas(partition):
    return [p.plaza for p in partition.plots if p.plaza is not None]


def _tier_counts(partition) -> tuple[int, int]:
    plazas = _all_plazas(partition)
    big = sum(1 for z in plazas if z.tier == "big")
    small = sum(1 for z in plazas if z.tier == "small")
    return big, small


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_leaf_count_within_target(size_class):
    lo, hi = _LEAF_TARGET_RANGE[size_class]
    for seed in range(40):
        part = partition_interior(
            INTERIORS[size_class], size_class, random.Random(seed)
        )
        assert lo <= len(part.plots) <= hi
        # leaves = cuts + 1 (each split reserves exactly one gutter).
        assert len(part.plots) == len(part.gutters) + 1


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_plaza_counts_and_tiers(size_class):
    expected = PLAZA_COUNTS[size_class]
    for seed in range(40):
        part = partition_interior(
            INTERIORS[size_class], size_class, random.Random(seed)
        )
        assert _tier_counts(part) == expected


@pytest.mark.parametrize("size_class", ("village", "town", "city"))
def test_big_plaza_dim_per_site(size_class):
    expected = _BIG_PLAZA_DIM[size_class]
    part = partition_interior(
        INTERIORS[size_class], size_class, random.Random(7)
    )
    big = next(z for z in _all_plazas(part) if z.tier == "big")
    assert big.rect.width == expected
    assert big.rect.height == expected


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_small_plaza_dim_is_five(size_class):
    for seed in range(20):
        part = partition_interior(
            INTERIORS[size_class], size_class, random.Random(seed)
        )
        for z in _all_plazas(part):
            if z.tier == "small":
                assert z.rect.width == _SMALL_PLAZA_DIM
                assert z.rect.height == _SMALL_PLAZA_DIM


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_plaza_inside_host_plot(size_class):
    for seed in range(20):
        part = partition_interior(
            INTERIORS[size_class], size_class, random.Random(seed)
        )
        for plot in part.plots:
            if plot.plaza is not None:
                assert _tiles(plot.plaza.rect) <= _tiles(plot.rect)


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_every_plot_meets_min_size(size_class):
    for seed in range(40):
        part = partition_interior(
            INTERIORS[size_class], size_class, random.Random(seed)
        )
        for plot in part.plots:
            assert plot.rect.width >= MIN_PLOT_DIM
            assert plot.rect.height >= MIN_PLOT_DIM


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_partition_of_unity(size_class):
    """Every interior tile belongs to exactly one of {plot, plaza,
    gutter}; plots+gutters tile the interior and plazas nest in plots."""
    interior = INTERIORS[size_class]
    for seed in range(20):
        part = partition_interior(interior, size_class, random.Random(seed))
        covered: set[tuple[int, int]] = set()
        for plot in part.plots:
            cells = _tiles(plot.rect)
            assert covered.isdisjoint(cells), "plots overlap"
            covered |= cells
        for gutter in part.gutters:
            cells = _tiles(gutter)
            assert covered.isdisjoint(cells), "gutter overlaps a plot"
            covered |= cells
        assert covered == _tiles(interior)


@pytest.mark.parametrize("size_class", SIZE_CLASSES)
def test_determinism_same_seed(size_class):
    a = partition_interior(
        INTERIORS[size_class], size_class, random.Random(99)
    )
    b = partition_interior(
        INTERIORS[size_class], size_class, random.Random(99)
    )
    assert a == b


def test_different_seed_differs():
    a = partition_interior(INTERIORS["city"], "city", random.Random(1))
    b = partition_interior(INTERIORS["city"], "city", random.Random(2))
    assert a != b


def test_hamlet_single_plot():
    part = partition_interior(INTERIORS["hamlet"], "hamlet", random.Random(3))
    assert len(part.plots) == 1
    assert part.gutters == []
    assert _tier_counts(part) == (0, 1)
    plaza = _all_plazas(part)[0]
    assert plaza.tier == "small"
    assert plaza.rect.width == _SMALL_PLAZA_DIM


def test_village_one_big_no_small():
    part = partition_interior(
        INTERIORS["village"], "village", random.Random(4)
    )
    assert len(part.plots) == 2
    assert _tier_counts(part) == (1, 0)


def test_village_big_plaza_auto_shrinks_when_tight():
    """A deliberately tiny village interior can't seat the 7x7 fountain
    with building room, so the big plaza shrinks to 5x5 — fountain kept
    (tier stays 'big'), never dropping buildings to fit (Q6)."""
    tiny = Rect(0, 0, 14, 14)
    part = partition_interior(tiny, "village", random.Random(5))
    big = next(z for z in _all_plazas(part) if z.tier == "big")
    assert big.tier == "big"
    assert big.rect.width == _SMALL_PLAZA_DIM
    assert big.rect.height == _SMALL_PLAZA_DIM


def test_non_palisade_forces_single_plot():
    """suppress_palisade sites skip BSP: one plot, no gutters, the
    plaza reserved inside that single plot (Q2)."""
    part = partition_interior(
        INTERIORS["city"], "city", random.Random(6), single_plot=True
    )
    assert len(part.plots) == 1
    assert part.gutters == []
    plazas = _all_plazas(part)
    assert len(plazas) == 1
    assert _tiles(plazas[0].rect) <= _tiles(part.plots[0].rect)
