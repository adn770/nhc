"""Tests for river generation.

Rivers flow downhill from mountains toward sea (WATER) tiles.
Each hex along the river carries an EdgeSegment with consistent
entry/exit edges. The algorithm supports bifurcation (branching)
and enforces a minimum length.
"""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import HexCoord, NEIGHBOR_OFFSETS, neighbors
from nhc.hexcrawl.model import Biome, EdgeSegment, HexCell, HexWorld
from nhc.hexcrawl._rivers import (
    direction_index,
    generate_rivers,
    RiverParams,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cells(
    width: int,
    height: int,
    biome: Biome = Biome.GREENLANDS,
    elevation: float = 0.3,
) -> dict[HexCoord, HexCell]:
    """Flat grid of uniform biome + elevation."""
    cells: dict[HexCoord, HexCell] = {}
    for q in range(width):
        for r in range(height):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                biome=biome,
                elevation=elevation,
            )
    return cells


def _mountain_to_sea_strip() -> dict[HexCoord, HexCell]:
    """Vertical strip: mountain at top, greenlands in middle, water at bottom.

    Layout (q=0, r=0..5):
      r=0  MOUNTAIN  elev=0.85
      r=1  HILLS     elev=0.55
      r=2  GREENLANDS elev=0.30
      r=3  GREENLANDS elev=0.20
      r=4  GREENLANDS elev=0.10
      r=5  WATER     elev=-0.40
    """
    specs = [
        (Biome.MOUNTAIN, 0.85),
        (Biome.HILLS, 0.55),
        (Biome.GREENLANDS, 0.30),
        (Biome.GREENLANDS, 0.20),
        (Biome.GREENLANDS, 0.10),
        (Biome.WATER, -0.40),
    ]
    cells: dict[HexCoord, HexCell] = {}
    for r, (biome, elev) in enumerate(specs):
        c = HexCoord(0, r)
        cells[c] = HexCell(coord=c, biome=biome, elevation=elev)
    return cells


# ---------------------------------------------------------------------------
# direction_index
# ---------------------------------------------------------------------------


def test_direction_index_all_six() -> None:
    origin = HexCoord(3, 3)
    for idx, (dq, dr) in enumerate(NEIGHBOR_OFFSETS):
        nbr = HexCoord(origin.q + dq, origin.r + dr)
        assert direction_index(origin, nbr) == idx


def test_direction_index_non_adjacent_raises() -> None:
    with pytest.raises(ValueError):
        direction_index(HexCoord(0, 0), HexCoord(2, 2))


# ---------------------------------------------------------------------------
# River flows downhill
# ---------------------------------------------------------------------------


def test_river_flows_downhill() -> None:
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert len(rivers) >= 1
    river = rivers[0]
    for i in range(len(river) - 1):
        cur_elev = cells[river[i]].elevation
        nxt_elev = cells[river[i + 1]].elevation
        assert cur_elev >= nxt_elev, (
            f"river went uphill at step {i}: "
            f"{cur_elev} -> {nxt_elev}"
        )


def test_river_starts_at_mountain() -> None:
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert len(rivers) >= 1
    source = rivers[0][0]
    assert cells[source].biome is Biome.MOUNTAIN


def test_river_terminates_at_water_or_edge() -> None:
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert len(rivers) >= 1
    terminus = rivers[0][-1]
    # Either the last hex is WATER, or the river reached a map edge
    # (no in-map neighbor in the flow direction).
    at_water = cells[terminus].biome is Biome.WATER
    at_edge = all(n not in cells for n in neighbors(terminus))
    assert at_water or at_edge, (
        f"river didn't terminate at water or edge: {terminus}"
    )


# ---------------------------------------------------------------------------
# Edge segment consistency
# ---------------------------------------------------------------------------


def test_river_edge_segments_consistent() -> None:
    """Exit edge of cell[i] must be the opposite of entry edge of cell[i+1]."""
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert len(rivers) >= 1
    river = rivers[0]
    for i in range(len(river) - 1):
        cur_segs = [
            s for s in cells[river[i]].edges if s.type == "river"
        ]
        nxt_segs = [
            s for s in cells[river[i + 1]].edges if s.type == "river"
        ]
        assert cur_segs, f"no river segment on cell {river[i]}"
        assert nxt_segs, f"no river segment on cell {river[i + 1]}"
        # The exit edge of the current cell
        cur_exit = cur_segs[0].exit_edge
        # The entry edge of the next cell
        nxt_entry = nxt_segs[0].entry_edge
        assert cur_exit is not None
        assert nxt_entry is not None
        assert nxt_entry == (cur_exit + 3) % 6, (
            f"edge mismatch at step {i}: "
            f"exit={cur_exit}, next entry={nxt_entry}"
        )


def test_river_source_has_none_entry() -> None:
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    source = rivers[0][0]
    segs = [s for s in cells[source].edges if s.type == "river"]
    assert segs[0].entry_edge is None


def test_river_sink_has_none_exit() -> None:
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    terminus = rivers[0][-1]
    segs = [s for s in cells[terminus].edges if s.type == "river"]
    assert segs[0].exit_edge is None


# ---------------------------------------------------------------------------
# No self-intersection
# ---------------------------------------------------------------------------


def test_river_no_self_intersection() -> None:
    cells = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    for river in rivers:
        assert len(river) == len(set(river)), "river intersects itself"


# ---------------------------------------------------------------------------
# Min-length enforcement
# ---------------------------------------------------------------------------


def test_river_min_length_enforced() -> None:
    """Rivers shorter than min_length are discarded."""
    # Single mountain hex surrounded by water — river would be
    # length 2 (mountain + water). Set min_length=3 so it's rejected.
    cells = {
        HexCoord(0, 0): HexCell(
            coord=HexCoord(0, 0), biome=Biome.MOUNTAIN, elevation=0.85,
        ),
        HexCoord(0, 1): HexCell(
            coord=HexCoord(0, 1), biome=Biome.WATER, elevation=-0.40,
        ),
    }
    params = RiverParams(max_rivers=1, min_length=3)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert rivers == [], "too-short river should have been discarded"


# ---------------------------------------------------------------------------
# Bifurcation
# ---------------------------------------------------------------------------


def test_bifurcation_produces_branch() -> None:
    """With bifurcation_chance=1.0, at least one branch is created."""
    # Wide enough grid so there's room to branch.
    cells: dict[HexCoord, HexCell] = {}
    for q in range(5):
        for r in range(8):
            if q == 2 and r == 0:
                biome, elev = Biome.MOUNTAIN, 0.85
            elif r == 7:
                biome, elev = Biome.WATER, -0.40
            else:
                biome = Biome.GREENLANDS
                elev = 0.6 - 0.1 * r + 0.01 * q
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r), biome=biome, elevation=elev,
            )
    params = RiverParams(
        max_rivers=1, min_length=2, bifurcation_chance=1.0,
    )
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    # With 100% bifurcation chance we should get the main river
    # plus at least one branch.
    assert len(rivers) > 1, "expected at least one branch"


# ---------------------------------------------------------------------------
# Deterministic
# ---------------------------------------------------------------------------


def test_river_generation_deterministic() -> None:
    cells_a = _mountain_to_sea_strip()
    cells_b = _mountain_to_sea_strip()
    params = RiverParams(max_rivers=1, min_length=2)
    rivers_a = generate_rivers(cells_a, random.Random(99), params)
    rivers_b = generate_rivers(cells_b, random.Random(99), params)
    assert rivers_a == rivers_b


# ---------------------------------------------------------------------------
# Empty / no-source edge cases
# ---------------------------------------------------------------------------


def test_no_mountains_produces_no_rivers() -> None:
    cells = _make_cells(4, 4, biome=Biome.GREENLANDS, elevation=0.3)
    params = RiverParams(max_rivers=3, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert rivers == []


# ---------------------------------------------------------------------------
# Max-length enforcement
# ---------------------------------------------------------------------------


def test_river_respects_max_length() -> None:
    """Rivers must not exceed max_length hexes."""
    # Wide flat grid — river would meander forever without cap.
    cells: dict[HexCoord, HexCell] = {}
    for q in range(10):
        for r in range(20):
            if q == 5 and r == 0:
                biome, elev = Biome.MOUNTAIN, 0.85
            else:
                biome = Biome.GREENLANDS
                elev = 0.6 - 0.02 * r
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r), biome=biome, elevation=elev,
            )
    params = RiverParams(max_rivers=1, min_length=2, max_length=10)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    for river in rivers:
        assert len(river) <= 10, (
            f"river exceeded max_length: {len(river)} > 10"
        )


# ---------------------------------------------------------------------------
# Flatness termination
# ---------------------------------------------------------------------------


def test_river_avoids_arid_biomes() -> None:
    """Rivers should not flow through drylands or sandlands."""
    # Mountain source, then greenlands path flanked by drylands,
    # ending in water. River should follow the green corridor.
    cells: dict[HexCoord, HexCell] = {}
    for q in range(5):
        for r in range(8):
            if q == 2 and r == 0:
                biome, elev = Biome.MOUNTAIN, 0.85
            elif r == 7:
                biome, elev = Biome.WATER, -0.40
            elif q == 2:
                # Green corridor down the middle
                biome = Biome.GREENLANDS
                elev = 0.6 - 0.1 * r
            else:
                # Arid flanks
                biome = Biome.DRYLANDS
                elev = 0.5 - 0.08 * r
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r), biome=biome, elevation=elev,
            )
    params = RiverParams(max_rivers=1, min_length=2)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    arid = frozenset({Biome.DRYLANDS, Biome.SANDLANDS})
    for river in rivers:
        for coord in river:
            assert cells[coord].biome not in arid, (
                f"river entered arid biome at {coord}: "
                f"{cells[coord].biome}"
            )


def test_river_goes_around_arid_when_possible() -> None:
    """River should route around arid hexes if a non-arid
    neighbor exists, not just terminate."""
    # Mountain at top, greenlands path that bends around a
    # drylands hex, water at bottom.
    cells: dict[HexCoord, HexCell] = {}
    specs = {
        HexCoord(0, 0): (Biome.MOUNTAIN, 0.85),
        HexCoord(0, 1): (Biome.GREENLANDS, 0.55),
        HexCoord(0, 2): (Biome.DRYLANDS, 0.35),   # arid blocker
        HexCoord(1, 1): (Biome.GREENLANDS, 0.40),  # detour
        HexCoord(1, 2): (Biome.GREENLANDS, 0.25),  # detour
        HexCoord(0, 3): (Biome.GREENLANDS, 0.15),
        HexCoord(0, 4): (Biome.WATER, -0.40),
    }
    for coord, (biome, elev) in specs.items():
        cells[coord] = HexCell(coord=coord, biome=biome,
                               elevation=elev)
    params = RiverParams(max_rivers=1, min_length=3)
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert len(rivers) >= 1, "river should find a path around"
    river = rivers[0]
    assert len(river) >= 3, "river should be long enough"
    arid = frozenset({Biome.DRYLANDS, Biome.SANDLANDS})
    for coord in river:
        assert cells[coord].biome not in arid


def test_river_flatness_termination() -> None:
    """River stops when terrain becomes flat for too long."""
    # Mountain start, steep drop, then perfectly flat terrain.
    cells: dict[HexCoord, HexCell] = {}
    for r in range(15):
        if r == 0:
            biome, elev = Biome.MOUNTAIN, 0.85
        elif r <= 3:
            biome, elev = Biome.GREENLANDS, 0.85 - 0.15 * r
        else:
            # Perfectly flat from r=4 onward
            biome, elev = Biome.GREENLANDS, 0.30
        cells[HexCoord(0, r)] = HexCell(
            coord=HexCoord(0, r), biome=biome, elevation=elev,
        )
    params = RiverParams(
        max_rivers=1, min_length=2, max_length=50,
        flatness_window=3, flatness_threshold=0.01,
    )
    rng = random.Random(42)
    rivers = generate_rivers(cells, rng, params)
    assert len(rivers) >= 1
    # River should terminate in the flat zone, not reach the end.
    river = rivers[0]
    assert len(river) < 15, (
        f"river should have stopped in flat terrain, "
        f"but went {len(river)} hexes"
    )
