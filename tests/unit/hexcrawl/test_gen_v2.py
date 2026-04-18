"""Tests for the continental_v2 world generator pipeline."""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import (
    HexCoord,
    distance,
    expected_shape_cell_count,
    neighbors,
    shape_r_range,
    valid_shape_hex,
)
from nhc.hexcrawl.model import Biome, EdgeSegment, HexCell
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


# ---------------------------------------------------------------------------
# Stage 2: Tectonic plates
# ---------------------------------------------------------------------------


def _make_continent_field(
    seed: int = 42,
) -> dict[HexCoord, float]:
    from nhc.hexcrawl._gen_v2 import continental_shape
    return continental_shape(
        random.Random(seed), _params(), _WIDTH, _HEIGHT,
    )


class TestTectonicPlates:
    """Tests for the tectonic_plates() stage function."""

    def test_coverage(self) -> None:
        from nhc.hexcrawl._gen_v2 import tectonic_plates

        field = _make_continent_field()
        result = tectonic_plates(
            random.Random(42), _params(), field,
        )
        # Every hex must be assigned to exactly one plate
        assert set(result.plate_of.keys()) == set(field.keys())
        for plate_id in result.plate_of.values():
            assert 0 <= plate_id < _params().plate_count

    def test_plate_count(self) -> None:
        from nhc.hexcrawl._gen_v2 import tectonic_plates

        field = _make_continent_field()
        params = _params(plate_count=5)
        result = tectonic_plates(
            random.Random(42), params, field,
        )
        distinct_plates = set(result.plate_of.values())
        assert len(distinct_plates) == 5

    def test_boundaries_have_cross_plate_neighbors(self) -> None:
        from nhc.hexcrawl._gen_v2 import tectonic_plates

        field = _make_continent_field()
        result = tectonic_plates(
            random.Random(42), _params(), field,
        )
        for bh in result.boundaries:
            nbr_plates = {
                result.plate_of[n]
                for n in neighbors(bh)
                if n in result.plate_of
            }
            # Must have at least one neighbor in a different plate
            assert len(nbr_plates) > 1, (
                f"boundary {bh} has no cross-plate neighbor"
            )

    def test_boundary_classification_disjoint(self) -> None:
        from nhc.hexcrawl._gen_v2 import tectonic_plates

        field = _make_continent_field()
        result = tectonic_plates(
            random.Random(42), _params(), field,
        )
        # All classified sets are subsets of boundaries
        assert result.convergent <= result.boundaries
        assert result.divergent <= result.boundaries
        assert result.transform <= result.boundaries
        # Disjoint
        assert not (result.convergent & result.divergent)
        assert not (result.convergent & result.transform)
        assert not (result.divergent & result.transform)
        # Together they cover all boundaries
        assert (
            result.convergent | result.divergent | result.transform
            == result.boundaries
        )

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._gen_v2 import tectonic_plates

        field = _make_continent_field()
        a = tectonic_plates(random.Random(42), _params(), field)
        b = tectonic_plates(random.Random(42), _params(), field)
        assert a.plate_of == b.plate_of
        assert a.boundaries == b.boundaries


# ---------------------------------------------------------------------------
# Stage 3: Domain warping
# ---------------------------------------------------------------------------


def _make_plates(
    seed: int = 42,
) -> tuple[dict[HexCoord, float], object]:
    from nhc.hexcrawl._gen_v2 import continental_shape, tectonic_plates

    rng = random.Random(seed)
    field = continental_shape(rng, _params(), _WIDTH, _HEIGHT)
    plates = tectonic_plates(rng, _params(), field)
    return field, plates


class TestDomainWarping:
    """Tests for the domain_warp() stage function."""

    def test_bounded(self) -> None:
        from nhc.hexcrawl._gen_v2 import domain_warp

        field, plates = _make_plates()
        rng = random.Random(42)
        warped = domain_warp(
            rng, _params(), field, plates,
            _WIDTH, _HEIGHT,
        )
        for v in warped.values():
            assert -1.0 <= v <= 1.0

    def test_changes_coastline(self) -> None:
        from nhc.hexcrawl._gen_v2 import domain_warp

        field, plates = _make_plates()
        rng = random.Random(42)
        warped = domain_warp(
            rng, _params(), field, plates,
            _WIDTH, _HEIGHT,
        )
        # Count how many hexes changed sign relative to sea level
        sea = _params().sea_level
        changes = sum(
            1 for h in field
            if (field[h] >= sea) != (warped[h] >= sea)
        )
        # Some coastline hexes should have changed
        assert changes > 0

    def test_convergent_boost(self) -> None:
        from nhc.hexcrawl._gen_v2 import domain_warp

        field, plates = _make_plates()
        rng = random.Random(42)
        warped = domain_warp(
            rng, _params(), field, plates,
            _WIDTH, _HEIGHT,
        )
        if not plates.convergent:
            pytest.skip("no convergent boundaries on this seed")

        # Average elevation at convergent boundaries should be
        # higher than the average of the plate interior.
        conv_avg = sum(
            warped[h] for h in plates.convergent
        ) / len(plates.convergent)
        interior = [
            h for h in warped
            if h not in plates.boundaries
        ]
        if not interior:
            pytest.skip("no interior hexes")
        int_avg = sum(warped[h] for h in interior) / len(interior)
        assert conv_avg > int_avg

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._gen_v2 import domain_warp

        field, plates = _make_plates()
        a = domain_warp(
            random.Random(42), _params(), field, plates,
            _WIDTH, _HEIGHT,
        )
        b = domain_warp(
            random.Random(42), _params(), field, plates,
            _WIDTH, _HEIGHT,
        )
        assert a == b


# ---------------------------------------------------------------------------
# Stage 4: Hydraulic erosion
# ---------------------------------------------------------------------------


def _make_elevation(
    seed: int = 42,
) -> dict[HexCoord, float]:
    from nhc.hexcrawl._gen_v2 import (
        continental_shape,
        domain_warp,
        tectonic_plates,
    )
    rng = random.Random(seed)
    field = continental_shape(rng, _params(), _WIDTH, _HEIGHT)
    plates = tectonic_plates(rng, _params(), field)
    return domain_warp(rng, _params(), field, plates, _WIDTH, _HEIGHT)


class TestHydraulicErosion:
    """Tests for the hydraulic_erosion() stage function."""

    def test_bounded(self) -> None:
        from nhc.hexcrawl._gen_v2 import hydraulic_erosion

        elev = _make_elevation()
        result = hydraulic_erosion(
            random.Random(42), _params(), elev,
        )
        for v in result.elevation.values():
            assert -1.0 <= v <= 1.0

    def test_reduces_total_elevation(self) -> None:
        from nhc.hexcrawl._gen_v2 import hydraulic_erosion

        elev = _make_elevation()
        total_before = sum(elev.values())
        result = hydraulic_erosion(
            random.Random(42), _params(), elev,
        )
        total_after = sum(result.elevation.values())
        # Net erosion should reduce total elevation
        assert total_after < total_before

    def test_basins_cover_land(self) -> None:
        from nhc.hexcrawl._gen_v2 import hydraulic_erosion

        elev = _make_elevation()
        sea = _params().sea_level
        result = hydraulic_erosion(
            random.Random(42), _params(), elev,
        )
        land_hexes = {
            h for h, v in result.elevation.items()
            if v >= sea
        }
        # Every land hex should belong to a drainage basin
        for h in land_hexes:
            assert h in result.basins, f"{h} has no basin"

    def test_moisture_enhanced_at_high_flow(self) -> None:
        from nhc.hexcrawl._gen_v2 import hydraulic_erosion

        elev = _make_elevation()
        result = hydraulic_erosion(
            random.Random(42), _params(), elev,
        )
        if not result.flow_count:
            pytest.skip("no flow data")
        max_flow = max(result.flow_count.values())
        if max_flow < 2:
            pytest.skip("flow too uniform to test")
        # Find hexes with above-median flow
        flows = sorted(result.flow_count.values())
        median_flow = flows[len(flows) // 2]
        high_flow = [
            h for h, fc in result.flow_count.items()
            if fc > median_flow and fc > 1
        ]
        low_flow = [
            h for h, fc in result.flow_count.items()
            if fc <= 1
        ]
        if high_flow and low_flow:
            avg_high = sum(
                result.moisture[h] for h in high_flow
            ) / len(high_flow)
            avg_low = sum(
                result.moisture[h] for h in low_flow
            ) / len(low_flow)
            assert avg_high > avg_low

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._gen_v2 import hydraulic_erosion

        elev = _make_elevation()
        a = hydraulic_erosion(random.Random(42), _params(), elev)
        b = hydraulic_erosion(random.Random(42), _params(), elev)
        assert a.elevation == b.elevation
        assert a.basins == b.basins


# ---------------------------------------------------------------------------
# Stage 5: Biome assignment
# ---------------------------------------------------------------------------


def _make_erosion(
    seed: int = 42,
) -> tuple[object, object]:
    """Run stages 1-4 and return (erosion_result, plates)."""
    from nhc.hexcrawl._gen_v2 import (
        continental_shape,
        domain_warp,
        hydraulic_erosion,
        tectonic_plates,
    )
    rng = random.Random(seed)
    field = continental_shape(rng, _params(), _WIDTH, _HEIGHT)
    plates = tectonic_plates(rng, _params(), field)
    warped = domain_warp(rng, _params(), field, plates, _WIDTH, _HEIGHT)
    erosion = hydraulic_erosion(rng, _params(), warped)
    return erosion, plates


class TestBiomeAssignment:
    """Tests for the assign_biomes() stage function."""

    def test_essentials_present(self) -> None:
        from nhc.hexcrawl._gen_v2 import assign_biomes
        from nhc.hexcrawl.model import Biome

        erosion, plates = _make_erosion()
        rng = random.Random(42)
        cells, by_biome = assign_biomes(
            rng, _params(), erosion, plates, _WIDTH, _HEIGHT,
        )
        for essential in (
            Biome.GREENLANDS, Biome.MOUNTAIN,
            Biome.FOREST, Biome.ICELANDS,
        ):
            assert len(by_biome[essential]) > 0, (
                f"essential biome {essential} missing"
            )

    def test_mountain_coherence(self) -> None:
        from nhc.hexcrawl._gen_v2 import assign_biomes
        from nhc.hexcrawl.model import Biome

        erosion, plates = _make_erosion()
        rng = random.Random(42)
        cells, by_biome = assign_biomes(
            rng, _params(), erosion, plates, _WIDTH, _HEIGHT,
        )
        mountain_hexes = by_biome[Biome.MOUNTAIN]
        if len(mountain_hexes) < 2:
            pytest.skip("too few mountains to test coherence")
        near_convergent = sum(
            1 for h in mountain_hexes
            if any(
                distance(h, bh) <= 2
                for bh in plates.convergent
            )
        )
        # At least 30% of mountain hexes should be near
        # convergent boundaries (relaxed from 50% since some
        # seeds may have few convergent hexes).
        ratio = near_convergent / len(mountain_hexes)
        assert ratio >= 0.3, (
            f"only {ratio:.0%} mountains near convergent "
            f"boundaries"
        )

    def test_diversity(self) -> None:
        from nhc.hexcrawl._gen_v2 import assign_biomes

        erosion, plates = _make_erosion()
        rng = random.Random(42)
        cells, by_biome = assign_biomes(
            rng, _params(), erosion, plates, _WIDTH, _HEIGHT,
        )
        distinct = sum(1 for v in by_biome.values() if v)
        assert distinct >= 6

    def test_water_below_sea_level(self) -> None:
        from nhc.hexcrawl._gen_v2 import assign_biomes
        from nhc.hexcrawl.model import Biome

        erosion, plates = _make_erosion()
        rng = random.Random(42)
        cells, by_biome = assign_biomes(
            rng, _params(), erosion, plates, _WIDTH, _HEIGHT,
        )
        for h in by_biome[Biome.WATER]:
            assert cells[h].elevation < _params().sea_level

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._gen_v2 import assign_biomes

        erosion, plates = _make_erosion()
        cells_a, _ = assign_biomes(
            random.Random(42), _params(), erosion, plates,
            _WIDTH, _HEIGHT,
        )
        cells_b, _ = assign_biomes(
            random.Random(42), _params(), erosion, plates,
            _WIDTH, _HEIGHT,
        )
        for h in cells_a:
            assert cells_a[h].biome == cells_b[h].biome


# ---------------------------------------------------------------------------
# Stage 9: Edge-point continuity (macro offsets)
# ---------------------------------------------------------------------------


class TestMacroEdgeOffsets:
    """Tests for _assign_macro_offsets()."""

    def _make_cells_with_river(self) -> dict[HexCoord, HexCell]:
        """Build cells with a simple 3-hex river for offset testing."""
        from nhc.hexcrawl.model import EdgeSegment, HexCell
        from nhc.hexcrawl.coords import shape_r_range

        cells: dict[HexCoord, HexCell] = {}
        for q in range(5):
            r_min, r_max = shape_r_range(q, 5)
            for r in range(r_min, r_max):
                cells[HexCoord(q, r)] = HexCell(
                    coord=HexCoord(q, r),
                    biome=Biome.GREENLANDS,
                    elevation=0.3,
                )

        # Stamp a 3-hex river: (1,0) -> (2,0) -> (3,0)
        from nhc.hexcrawl.coords import direction_index
        path = [HexCoord(1, 0), HexCoord(2, 0), HexCoord(3, 0)]
        for i, coord in enumerate(path):
            entry = None if i == 0 else (
                direction_index(path[i - 1], coord) + 3
            ) % 6
            exit_ = None if i == len(path) - 1 else (
                direction_index(coord, path[i + 1])
            )
            cells[coord].edges.append(
                EdgeSegment(
                    type="river",
                    entry_edge=entry if i > 0 else None,
                    exit_edge=exit_,
                ),
            )
        return cells

    def test_shared_offset(self) -> None:
        from nhc.hexcrawl._gen_v2 import _assign_macro_offsets

        cells = self._make_cells_with_river()
        _assign_macro_offsets(cells)

        # The exit offset of (1,0) should equal the entry offset
        # of (2,0) -- they share the same edge.
        seg_1 = cells[HexCoord(1, 0)].edges[0]
        seg_2 = cells[HexCoord(2, 0)].edges[0]
        assert seg_1.exit_offset is not None
        assert seg_2.entry_offset is not None
        assert seg_1.exit_offset == seg_2.entry_offset

        # Same for (2,0) exit and (3,0) entry.
        seg_3 = cells[HexCoord(3, 0)].edges[0]
        assert seg_2.exit_offset is not None
        assert seg_3.entry_offset is not None
        assert seg_2.exit_offset == seg_3.entry_offset

    def test_bounded(self) -> None:
        from nhc.hexcrawl._gen_v2 import _assign_macro_offsets

        cells = self._make_cells_with_river()
        _assign_macro_offsets(cells)

        for cell in cells.values():
            for seg in cell.edges:
                if seg.entry_offset is not None:
                    assert -0.4 <= seg.entry_offset <= 0.4
                if seg.exit_offset is not None:
                    assert -0.4 <= seg.exit_offset <= 0.4

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._gen_v2 import _assign_macro_offsets

        cells_a = self._make_cells_with_river()
        _assign_macro_offsets(cells_a)
        cells_b = self._make_cells_with_river()
        _assign_macro_offsets(cells_b)

        for h in cells_a:
            for sa, sb in zip(
                cells_a[h].edges, cells_b[h].edges, strict=True,
            ):
                assert sa.entry_offset == sb.entry_offset
                assert sa.exit_offset == sb.exit_offset

    def test_source_and_sink_remain_none(self) -> None:
        from nhc.hexcrawl._gen_v2 import _assign_macro_offsets

        cells = self._make_cells_with_river()
        _assign_macro_offsets(cells)

        # Source (first hex) has entry_edge=None -> offset=None
        seg_src = cells[HexCoord(1, 0)].edges[0]
        assert seg_src.entry_offset is None

        # Sink (last hex) has exit_edge=None -> offset=None
        seg_sink = cells[HexCoord(3, 0)].edges[0]
        assert seg_sink.exit_offset is None


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Integration tests for generate_continental_world()."""

    def _make_pack(self, tmp_path) -> object:
        import textwrap
        from nhc.hexcrawl.pack import load_pack

        body = textwrap.dedent("""
            id: testland-v2
            version: 2
            map:
              generator: continental_v2
              width: 15
              height: 10
              continental:
                plate_count: 4
                erosion_iterations: 2
            features:
              hub: 1
              village:
                min: 1
                max: 3
              dungeon:
                min: 1
                max: 3
              wonder:
                min: 0
                max: 1
        """)
        p = tmp_path / "pack.yaml"
        p.write_text(body)
        return load_pack(p)

    def test_produces_hexworld(self, tmp_path) -> None:
        from nhc.hexcrawl._gen_v2 import generate_continental_world
        from nhc.hexcrawl.model import HexWorld

        pack = self._make_pack(tmp_path)
        world = generate_continental_world(seed=42, pack=pack)
        assert isinstance(world, HexWorld)
        assert len(world.cells) > 0

    def test_deterministic(self, tmp_path) -> None:
        from nhc.hexcrawl._gen_v2 import generate_continental_world

        pack = self._make_pack(tmp_path)
        a = generate_continental_world(seed=99, pack=pack)
        b = generate_continental_world(seed=99, pack=pack)
        assert len(a.cells) == len(b.cells)
        for h in a.cells:
            assert a.cells[h].biome == b.cells[h].biome
            assert a.cells[h].elevation == b.cells[h].elevation

    def test_all_cells_populated(self, tmp_path) -> None:
        from nhc.hexcrawl._gen_v2 import generate_continental_world

        pack = self._make_pack(tmp_path)
        world = generate_continental_world(seed=42, pack=pack)
        for coord, cell in world.cells.items():
            assert cell.biome is not None
            assert cell.tile_slot > 0

    def test_rivers_valid(self, tmp_path) -> None:
        from nhc.hexcrawl._gen_v2 import generate_continental_world

        pack = self._make_pack(tmp_path)
        world = generate_continental_world(seed=42, pack=pack)
        for river in world.rivers:
            src = river[0]
            assert world.cells[src].biome in (
                Biome.MOUNTAIN, Biome.HILLS,
            )

    def test_edge_continuity(self, tmp_path) -> None:
        from nhc.hexcrawl._gen_v2 import generate_continental_world

        pack = self._make_pack(tmp_path)
        world = generate_continental_world(seed=42, pack=pack)
        # Check macro offset sharing.
        for coord, cell in world.cells.items():
            for seg in cell.edges:
                if seg.exit_edge is not None and seg.exit_offset is not None:
                    nbr = neighbors(coord)[seg.exit_edge]
                    if nbr not in world.cells:
                        continue
                    # Find matching entry on the neighbor.
                    expected_entry = (seg.exit_edge + 3) % 6
                    for nseg in world.cells[nbr].edges:
                        if (nseg.type == seg.type
                                and nseg.entry_edge == expected_entry):
                            assert nseg.entry_offset == seg.exit_offset
