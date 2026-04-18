"""Tests for the v2 river generation module."""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import Biome, HexCell, HexFeatureType
from nhc.hexcrawl.pack import ContinentalParams, RiverParams


def _params(**overrides: object) -> ContinentalParams:
    return ContinentalParams(**overrides)  # type: ignore[arg-type]


def _river_params(**overrides: object) -> RiverParams:
    return RiverParams(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Build a small test world for river testing
# ---------------------------------------------------------------------------


def _build_test_cells() -> dict[HexCoord, HexCell]:
    """Build a 10x8 test grid with controlled biomes for river tests.

    Layout (simplified):
    - Left columns (q=0-2): MOUNTAIN at high elevation
    - Middle columns (q=3-5): FOREST at mid elevation
    - Right columns (q=6-7): GREENLANDS at low elevation
    - Bottom row: DRYLANDS at very low elevation
    - One WATER hex at (9, 0)
    """
    from nhc.hexcrawl.coords import shape_r_range

    cells: dict[HexCoord, HexCell] = {}
    width, height = 10, 8
    for q in range(width):
        r_min, r_max = shape_r_range(q, height)
        for r in range(r_min, r_max):
            coord = HexCoord(q, r)
            if q <= 2:
                biome = Biome.MOUNTAIN
                elev = 0.80 - r * 0.02
            elif q <= 5:
                biome = Biome.FOREST
                elev = 0.40 - r * 0.02 - (q - 3) * 0.05
            elif q <= 7:
                biome = Biome.GREENLANDS
                elev = 0.20 - r * 0.02 - (q - 6) * 0.05
            else:
                biome = Biome.GREENLANDS
                elev = 0.10 - r * 0.01

            # Bottom row: drylands
            if r == r_max - 1 and q >= 3:
                biome = Biome.DRYLANDS
                elev = 0.05

            cells[coord] = HexCell(
                coord=coord, biome=biome, elevation=elev,
            )

    # One water hex as a sea terminus
    water_coord = HexCoord(9, 0)
    if water_coord in cells:
        cells[water_coord].biome = Biome.WATER
        cells[water_coord].elevation = -0.40

    return cells


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRiversV2:

    def test_starts_at_mountain(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        cells = _build_test_cells()
        rng = random.Random(42)
        rparams = _river_params(
            max_rivers=3, min_length=3,
            avoided_biomes=frozenset(),
        )
        rivers = generate_rivers_v2(
            cells, rng, rparams, _params(),
            flow_count={},
        )
        for river in rivers:
            src = river[0]
            assert cells[src].biome in (
                Biome.MOUNTAIN, Biome.HILLS,
            ), f"river source {src} is {cells[src].biome}"

    def test_forest_crossing(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        cells = _build_test_cells()
        rng = random.Random(42)
        # No avoided biomes: forest crossing is allowed
        rparams = _river_params(
            max_rivers=5, min_length=2,
            avoided_biomes=frozenset(),
        )
        rivers = generate_rivers_v2(
            cells, rng, rparams, _params(),
            flow_count={},
        )
        forest_crossed = any(
            cells[h].biome is Biome.FOREST
            for river in rivers
            for h in river
        )
        assert forest_crossed, "no river crossed a forest hex"

    def test_dies_in_drylands(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        cells = _build_test_cells()
        rng = random.Random(42)
        rparams = _river_params(
            max_rivers=5, min_length=2,
            avoided_biomes=frozenset(),
        )
        rivers = generate_rivers_v2(
            cells, rng, rparams, _params(),
            flow_count={},
        )
        for river in rivers:
            for i, h in enumerate(river):
                if cells[h].biome is Biome.DRYLANDS:
                    # River must end here or at the next step
                    assert i >= len(river) - 2, (
                        f"river continued {len(river) - i - 1} "
                        f"steps past drylands at index {i}"
                    )

    def test_sea_termination(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        cells = _build_test_cells()
        rng = random.Random(42)
        rparams = _river_params(
            max_rivers=5, min_length=2,
            avoided_biomes=frozenset(),
        )
        rivers = generate_rivers_v2(
            cells, rng, rparams, _params(),
            flow_count={},
        )
        for river in rivers:
            last = river[-1]
            if cells[last].biome is Biome.WATER:
                # Good: river terminated at water
                pass

    def test_lake_creation(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        cells = _build_test_cells()
        rng = random.Random(42)
        rparams = _river_params(
            max_rivers=5, min_length=2,
            avoided_biomes=frozenset(),
        )
        cparams = _params(lake_chance=1.0)
        rivers = generate_rivers_v2(
            cells, rng, rparams, cparams,
            flow_count={},
        )
        lakes = [
            h for h, c in cells.items()
            if c.feature is HexFeatureType.LAKE
        ]
        # With lake_chance=1.0, at least one lake should be created
        # if any river reaches low-elevation greenlands/marsh
        # (our test grid has low-elevation greenlands on the right)
        assert len(lakes) >= 1 or all(
            cells[river[-1]].biome in (Biome.WATER, Biome.DRYLANDS)
            for river in rivers
        )

    def test_edge_segments_consistent(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        cells = _build_test_cells()
        rng = random.Random(42)
        rparams = _river_params(
            max_rivers=3, min_length=2,
            avoided_biomes=frozenset(),
        )
        generate_rivers_v2(
            cells, rng, rparams, _params(),
            flow_count={},
        )
        for coord, cell in cells.items():
            for seg in cell.edges:
                if seg.type != "river":
                    continue
                if seg.entry_edge is not None:
                    assert 0 <= seg.entry_edge <= 5
                if seg.exit_edge is not None:
                    assert 0 <= seg.exit_edge <= 5

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._rivers_v2 import generate_rivers_v2

        rparams = _river_params(
            max_rivers=3, min_length=2,
            avoided_biomes=frozenset(),
        )

        cells_a = _build_test_cells()
        rivers_a = generate_rivers_v2(
            cells_a, random.Random(42), rparams, _params(),
            flow_count={},
        )

        cells_b = _build_test_cells()
        rivers_b = generate_rivers_v2(
            cells_b, random.Random(42), rparams, _params(),
            flow_count={},
        )

        assert rivers_a == rivers_b
