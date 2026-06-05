"""Tests for the flood-fill connected-components helper that replaced
the Shapely union+contains hotspot in ``_floor_layers`` (perf fix C).

The key contract: it must match Shapely's tile-box ``unary_union``
connectivity exactly — which is 4-connectivity (edge-adjacent tiles
connect; corner-only-touching tiles do NOT). A Shapely oracle proves
the equivalence on random tile sets.
"""

import random

import pytest

from nhc.rendering._floor_layers import _grid_components

shapely_geometry = pytest.importorskip("shapely.geometry")
shapely_ops = pytest.importorskip("shapely.ops")

_CELL = 32


def _shapely_components(tiles):
    """Oracle: the exact partition the old union+contains produced."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    def box(tx, ty):
        return Polygon([
            (tx * _CELL, ty * _CELL),
            ((tx + 1) * _CELL, ty * _CELL),
            ((tx + 1) * _CELL, (ty + 1) * _CELL),
            (tx * _CELL, (ty + 1) * _CELL),
        ])

    tiles = set(tiles)
    if not tiles:
        return []
    merged = unary_union([box(*t) for t in tiles])
    geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    out = []
    for g in geoms:
        if g.is_empty:
            continue
        comp = {t for t in tiles if g.contains(box(*t))}
        if comp:
            out.append(comp)
    return out


def _as_frozenset(comps):
    """Order-independent view: the set of components (each frozen)."""
    return {frozenset(c) for c in comps}


def test_edge_adjacent_is_one_component():
    assert len(_grid_components({(0, 0), (1, 0)})) == 1


def test_corner_only_is_two_components():
    # 4-connectivity: a diagonal touch does NOT connect (matches Shapely).
    comps = _grid_components({(0, 0), (1, 1)})
    assert len(comps) == 2


def test_l_shape_is_one_component():
    assert len(_grid_components({(0, 0), (1, 0), (1, 1)})) == 1


def test_separated_is_two_components():
    assert len(_grid_components({(0, 0), (3, 0)})) == 2


def test_empty():
    assert _grid_components(set()) == []


def test_deterministic_row_major_order():
    # Components ordered by their topmost-leftmost (row-major) tile, so
    # independent callers agree on the f"<kind>.<i>" numbering.
    tiles = {(5, 5), (6, 5), (0, 0), (1, 0), (3, 9)}
    comps = _grid_components(tiles)
    firsts = [min(c, key=lambda t: (t[1], t[0])) for c in comps]
    assert firsts == sorted(firsts, key=lambda t: (t[1], t[0]))
    # Re-running yields identical ordering.
    assert [sorted(c) for c in comps] == [
        sorted(c) for c in _grid_components(tiles)
    ]


def test_matches_shapely_oracle_on_random_grids():
    rng = random.Random(1234)
    for _ in range(60):
        w = rng.randint(1, 14)
        h = rng.randint(1, 14)
        tiles = {
            (x, y)
            for x in range(w) for y in range(h)
            if rng.random() < 0.5
        }
        assert _as_frozenset(_grid_components(tiles)) == _as_frozenset(
            _shapely_components(tiles)
        ), f"mismatch for tiles={sorted(tiles)}"
