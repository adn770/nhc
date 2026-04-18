"""Tests for the continental_v2 world generator pipeline."""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import (
    HexCoord,
    expected_shape_cell_count,
    shape_r_range,
    valid_shape_hex,
)
from nhc.hexcrawl.pack import ContinentalParams


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WIDTH = 25
_HEIGHT = 16


def _all_valid_hexes(
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> list[HexCoord]:
    """Return every valid hex in the rectangular odd-q shape."""
    hexes: list[HexCoord] = []
    for q in range(width):
        r_min, r_max = shape_r_range(q, height)
        for r in range(r_min, r_max):
            hexes.append(HexCoord(q, r))
    return hexes


def _params(**overrides: object) -> ContinentalParams:
    return ContinentalParams(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stage 1: Continental shape
# ---------------------------------------------------------------------------


class TestContinentalShape:
    """Tests for the continental_shape() stage function."""

    def test_bounded(self) -> None:
        from nhc.hexcrawl._gen_v2 import continental_shape

        rng = random.Random(42)
        field = continental_shape(
            rng, _params(), _WIDTH, _HEIGHT,
        )
        for v in field.values():
            assert -1.0 <= v <= 1.0

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._gen_v2 import continental_shape

        a = continental_shape(
            random.Random(99), _params(), _WIDTH, _HEIGHT,
        )
        b = continental_shape(
            random.Random(99), _params(), _WIDTH, _HEIGHT,
        )
        assert a == b

    def test_island_mask_edges_lower(self) -> None:
        from nhc.hexcrawl._gen_v2 import continental_shape

        field = continental_shape(
            random.Random(42), _params(), _WIDTH, _HEIGHT,
        )
        hexes = _all_valid_hexes()
        cx = (_WIDTH - 1) / 2.0
        cy = (_HEIGHT - 1) / 2.0
        center_vals: list[float] = []
        edge_vals: list[float] = []
        for h in hexes:
            dx = (h.q - cx) / cx if cx else 0
            dy = (h.r - cy) / cy if cy else 0
            dist = (dx ** 2 + dy ** 2) ** 0.5
            if dist < 0.3:
                center_vals.append(field[h])
            elif dist > 0.8:
                edge_vals.append(field[h])
        if center_vals and edge_vals:
            avg_center = sum(center_vals) / len(center_vals)
            avg_edge = sum(edge_vals) / len(edge_vals)
            assert avg_center > avg_edge

    def test_different_seeds(self) -> None:
        from nhc.hexcrawl._gen_v2 import continental_shape

        a = continental_shape(
            random.Random(1), _params(), _WIDTH, _HEIGHT,
        )
        b = continental_shape(
            random.Random(2), _params(), _WIDTH, _HEIGHT,
        )
        assert a != b

    def test_covers_all_valid_hexes(self) -> None:
        from nhc.hexcrawl._gen_v2 import continental_shape

        field = continental_shape(
            random.Random(42), _params(), _WIDTH, _HEIGHT,
        )
        expected = expected_shape_cell_count(_WIDTH, _HEIGHT)
        assert len(field) == expected

    def test_sea_level_classification(self) -> None:
        from nhc.hexcrawl._gen_v2 import continental_shape

        params = _params(sea_level=-0.25)
        field = continental_shape(
            random.Random(42), params, _WIDTH, _HEIGHT,
        )
        land = sum(1 for v in field.values() if v >= params.sea_level)
        sea = sum(1 for v in field.values() if v < params.sea_level)
        # Both land and sea should exist
        assert land > 0
        assert sea > 0
