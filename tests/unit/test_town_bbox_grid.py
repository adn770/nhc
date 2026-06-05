"""Equivalence tests for the town cluster-packing overlap fast path.

Two optimisations must be behaviour-identical to the old code so
town/city layouts stay seed-stable:

1. The inlined ``_bboxes_overlap_with_gap`` must match the old
   ``max()``-based formula bit-for-bit.
2. ``_BboxGrid.overlaps_any`` (spatial index) must return the same
   boolean a linear scan would — it only accelerates the query.
"""

import random

from nhc.dungeon.model import Rect
from nhc.sites._town_layout import _BboxGrid, _bboxes_overlap_with_gap


def _old_overlap(a: Rect, b: Rect, gap: int) -> bool:
    """The pre-optimisation reference implementation."""
    dx = max(0, max(a.x - b.x2, b.x - a.x2))
    dy = max(0, max(a.y - b.y2, b.y - a.y2))
    return dx < gap and dy < gap


def _rand_rect(rng):
    return Rect(
        rng.randint(-5, 30), rng.randint(-5, 30),
        rng.randint(1, 10), rng.randint(1, 10),
    )


def test_inline_overlap_matches_old_formula():
    rng = random.Random(7)
    for _ in range(5000):
        a, b = _rand_rect(rng), _rand_rect(rng)
        gap = rng.choice([1, 2, 3])
        assert _bboxes_overlap_with_gap(a, b, gap) == _old_overlap(
            a, b, gap
        ), f"a={a} b={b} gap={gap}"


def test_overlap_is_symmetric():
    rng = random.Random(11)
    for _ in range(2000):
        a, b = _rand_rect(rng), _rand_rect(rng)
        gap = rng.choice([1, 2, 3])
        assert _bboxes_overlap_with_gap(a, b, gap) == _bboxes_overlap_with_gap(
            b, a, gap
        )


def test_bbox_grid_matches_linear_scan():
    rng = random.Random(1234)
    for _ in range(200):
        gap = rng.choice([1, 2, 3])
        rects = [_rand_rect(rng) for _ in range(rng.randint(0, 40))]
        grid = _BboxGrid(gap)
        for r in rects:
            grid.add(r)
        # Query with fresh random bboxes — index result must equal
        # the exhaustive linear scan over every inserted rect.
        for _ in range(20):
            q = _rand_rect(rng)
            expected = any(
                _bboxes_overlap_with_gap(q, r, gap) for r in rects
            )
            assert grid.overlaps_any(q) == expected, (
                f"q={q} gap={gap} rects={rects}"
            )


def test_bbox_grid_empty():
    grid = _BboxGrid(1)
    assert grid.overlaps_any(Rect(0, 0, 5, 5)) is False
