"""Continental V2 world generator pipeline.

A nine-stage pipeline that builds terrain geologically:
continental crust, tectonic plates, domain warping, erosion,
biome assignment, rivers, settlements, roads, and micro-tile
edge continuity.

Each stage is a function that takes a seed/RNG and configuration,
returning its output for the next stage to consume.
"""

from __future__ import annotations

import math
import random

from dataclasses import dataclass

from nhc.hexcrawl.coords import (
    HexCoord,
    distance,
    neighbors,
    ring,
    shape_r_range,
)
from nhc.hexcrawl.noise import SimplexNoise
from nhc.hexcrawl.pack import ContinentalParams


# ---------------------------------------------------------------------------
# Stage 1: Continental shape
# ---------------------------------------------------------------------------


def continental_shape(
    rng: random.Random,
    params: ContinentalParams,
    width: int,
    height: int,
) -> dict[HexCoord, float]:
    """Low-frequency simplex noise + island mask for ocean/land.

    Returns a dictionary mapping every valid hex in the
    rectangular odd-q shape to a continental elevation value
    in ``[-1, 1]``. Values above ``params.sea_level`` are land;
    below are ocean.
    """
    noise = SimplexNoise(seed=rng.randrange(1 << 30))
    freq = params.continent_frequency
    octaves = params.continent_octaves
    falloff = params.island_falloff

    # Map center for the island mask.
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    # Maximum distance from center to any corner (normalised).
    max_dist = math.sqrt(2.0)

    field: dict[HexCoord, float] = {}
    for q in range(width):
        r_min, r_max = shape_r_range(q, height)
        for r in range(r_min, r_max):
            # Axial -> planar for noise sampling (same mapping
            # used in the Perlin generator).
            fx = q * freq
            fy = (r + q * 0.5) * freq

            raw = noise.fractal(fx, fy, octaves=octaves)

            # Island mask: radial falloff from map center pushes
            # edges toward ocean.
            dx = (q - cx) / max(cx, 1)
            dy = (r - cy) / max(cy, 1)
            dist = math.sqrt(dx * dx + dy * dy) / max_dist
            mask = 1.0 - (dist * falloff) ** 2
            mask = max(mask, 0.0)

            value = raw * mask
            value = max(-1.0, min(1.0, value))
            field[HexCoord(q, r)] = value

    return field


# ---------------------------------------------------------------------------
# Stage 2: Tectonic plates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlateResult:
    """Output of the tectonic_plates() stage."""

    plate_of: dict[HexCoord, int]
    boundaries: frozenset[HexCoord]
    convergent: frozenset[HexCoord]
    divergent: frozenset[HexCoord]
    transform: frozenset[HexCoord]


def tectonic_plates(
    rng: random.Random,
    params: ContinentalParams,
    continent_field: dict[HexCoord, float],
) -> PlateResult:
    """Voronoi tessellation on the hex grid for tectonic plates.

    Assigns every hex to the nearest of ``params.plate_count``
    randomly placed sites, classifies plate boundaries as
    convergent, divergent, or transform based on random drift
    vectors.
    """
    all_hexes = list(continent_field.keys())
    k = min(params.plate_count, len(all_hexes))

    # Pick plate sites uniformly at random.
    sites = rng.sample(all_hexes, k)

    # Drift vector per plate: random direction and magnitude.
    drifts: list[tuple[float, float]] = [
        (rng.uniform(-1, 1), rng.uniform(-1, 1))
        for _ in range(k)
    ]

    # Assign each hex to its nearest site (Voronoi on hex grid).
    plate_of: dict[HexCoord, int] = {}
    for h in all_hexes:
        best_plate = 0
        best_dist = distance(h, sites[0])
        for i in range(1, k):
            d = distance(h, sites[i])
            if d < best_dist:
                best_dist = d
                best_plate = i
        plate_of[h] = best_plate

    # Detect boundaries: hex whose neighbors include a different
    # plate.
    boundaries: set[HexCoord] = set()
    for h in all_hexes:
        my_plate = plate_of[h]
        for nbr in neighbors(h):
            if nbr in plate_of and plate_of[nbr] != my_plate:
                boundaries.add(h)
                break

    # Classify boundaries by relative plate motion.
    convergent: set[HexCoord] = set()
    divergent: set[HexCoord] = set()
    transform: set[HexCoord] = set()

    # Compute plate centroids for boundary normal direction.
    plate_sum_q: list[float] = [0.0] * k
    plate_sum_r: list[float] = [0.0] * k
    plate_count: list[int] = [0] * k
    for h, pid in plate_of.items():
        plate_sum_q[pid] += h.q
        plate_sum_r[pid] += h.r
        plate_count[pid] += 1
    centroids: list[tuple[float, float]] = [
        (plate_sum_q[i] / max(plate_count[i], 1),
         plate_sum_r[i] / max(plate_count[i], 1))
        for i in range(k)
    ]

    threshold = 0.15

    for bh in boundaries:
        my_plate = plate_of[bh]
        # Find the dominant neighbor plate.
        nbr_plates: dict[int, int] = {}
        for nbr in neighbors(bh):
            if nbr in plate_of and plate_of[nbr] != my_plate:
                pid = plate_of[nbr]
                nbr_plates[pid] = nbr_plates.get(pid, 0) + 1
        if not nbr_plates:
            transform.add(bh)
            continue
        other_plate = max(nbr_plates, key=nbr_plates.get)  # type: ignore[arg-type]

        # Relative drift between the two plates.
        da = drifts[my_plate]
        db = drifts[other_plate]
        rel = (da[0] - db[0], da[1] - db[1])

        # Boundary normal: direction from my centroid to other.
        ca = centroids[my_plate]
        cb = centroids[other_plate]
        nx = cb[0] - ca[0]
        ny = cb[1] - ca[1]
        norm = math.sqrt(nx * nx + ny * ny)
        if norm < 1e-9:
            transform.add(bh)
            continue
        nx /= norm
        ny /= norm

        dot = rel[0] * nx + rel[1] * ny
        if dot < -threshold:
            convergent.add(bh)
        elif dot > threshold:
            divergent.add(bh)
        else:
            transform.add(bh)

    return PlateResult(
        plate_of=plate_of,
        boundaries=frozenset(boundaries),
        convergent=frozenset(convergent),
        divergent=frozenset(divergent),
        transform=frozenset(transform),
    )


# ---------------------------------------------------------------------------
# Stage 3: Domain warping
# ---------------------------------------------------------------------------


def domain_warp(
    rng: random.Random,
    params: ContinentalParams,
    continent_field: dict[HexCoord, float],
    plates: PlateResult,
    width: int,
    height: int,
) -> dict[HexCoord, float]:
    """Warp noise coordinates for organic coastlines.

    Re-samples the continent noise at displaced coordinates and
    combines with tectonic elevation boosts at plate boundaries.
    Returns the pre-erosion elevation field in ``[-1, 1]``.
    """
    continent_noise = SimplexNoise(seed=rng.randrange(1 << 30))
    warp_x_noise = SimplexNoise(seed=rng.randrange(1 << 30))
    warp_y_noise = SimplexNoise(seed=rng.randrange(1 << 30))

    freq = params.continent_frequency
    octaves = params.continent_octaves
    warp_freq = params.warp_frequency
    warp_amp = params.warp_amplitude
    falloff = params.island_falloff

    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    max_dist = math.sqrt(2.0)

    elevation: dict[HexCoord, float] = {}

    for h in continent_field:
        fx = h.q * freq
        fy = (h.r + h.q * 0.5) * freq

        # Domain warp displacement.
        wfx = h.q * warp_freq
        wfy = (h.r + h.q * 0.5) * warp_freq
        warp_dx = warp_x_noise.fractal(
            wfx, wfy, octaves=2,
        ) * warp_amp
        warp_dy = warp_y_noise.fractal(
            wfx, wfy, octaves=2,
        ) * warp_amp

        # Re-sample continent noise at warped coordinates.
        raw = continent_noise.fractal(
            fx + warp_dx, fy + warp_dy, octaves=octaves,
        )

        # Re-apply island mask.
        dx = (h.q - cx) / max(cx, 1)
        dy = (h.r - cy) / max(cy, 1)
        dist = math.sqrt(dx * dx + dy * dy) / max_dist
        mask = 1.0 - (dist * falloff) ** 2
        mask = max(mask, 0.0)

        elevation[h] = raw * mask

    # Apply tectonic elevation boosts at boundaries.
    # Pre-compute per-boundary-hex boosts, then fade into
    # neighbours.
    boost_map: dict[HexCoord, float] = {}
    for bh in plates.boundaries:
        if bh in plates.convergent:
            boost = rng.uniform(0.3, 0.5)
        elif bh in plates.divergent:
            boost = -0.1
        else:
            boost = 0.1
        boost_map[bh] = boost

    # Apply boosts with distance fade (up to 2 hexes out).
    accumulated: dict[HexCoord, float] = {}
    for bh, boost in boost_map.items():
        # Distance 0 (the boundary hex itself).
        accumulated[bh] = accumulated.get(bh, 0.0) + boost
        # Rings at distance 1 and 2.
        for d in (1, 2):
            fade = 1.0 - d / 3.0
            for h in ring(bh, d):
                if h in elevation:
                    accumulated[h] = (
                        accumulated.get(h, 0.0) + boost * fade
                    )

    for h in elevation:
        elevation[h] += accumulated.get(h, 0.0)
        elevation[h] = max(-1.0, min(1.0, elevation[h]))

    return elevation


# ---------------------------------------------------------------------------
# Stage 4: Hydraulic erosion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErosionResult:
    """Output of the hydraulic_erosion() stage."""

    elevation: dict[HexCoord, float]
    moisture: dict[HexCoord, float]
    flow_to: dict[HexCoord, HexCoord | None]
    flow_count: dict[HexCoord, int]
    basins: dict[HexCoord, int]


def hydraulic_erosion(
    rng: random.Random,
    params: ContinentalParams,
    elevation_field: dict[HexCoord, float],
) -> ErosionResult:
    """Iterative flow-accumulation erosion for hex grids.

    Simulates water flow to carve peaks, fill valleys, and
    identify natural drainage basins. Adapted for ~400-cell grids
    where individual-droplet erosion would be invisible.
    """
    # Work on a mutable copy.
    elev = dict(elevation_field)
    all_hexes = list(elev.keys())
    hex_set = set(all_hexes)

    # Moisture noise field.
    moist_noise = SimplexNoise(seed=rng.randrange(1 << 30))
    moisture: dict[HexCoord, float] = {}
    for h in all_hexes:
        mx = h.q * 0.12
        my = (h.r + h.q * 0.5) * 0.12
        moisture[h] = moist_noise.fractal(mx, my, octaves=4)

    flow_to: dict[HexCoord, HexCoord | None] = {}
    flow_count: dict[HexCoord, int] = {}

    for _ in range(params.erosion_iterations):
        # 1. Flow direction: steepest descent neighbor.
        flow_to.clear()
        for h in all_hexes:
            best_nbr: HexCoord | None = None
            best_drop = 0.0
            for nbr in neighbors(h):
                if nbr not in hex_set:
                    continue
                drop = elev[h] - elev[nbr]
                if drop > best_drop:
                    best_drop = drop
                    best_nbr = nbr
            flow_to[h] = best_nbr

        # 2. Flow accumulation.
        flow_count = {h: 0 for h in all_hexes}
        for h in all_hexes:
            current = h
            steps = 0
            while current is not None and steps < 30:
                nxt = flow_to.get(current)
                if nxt is None:
                    break
                flow_count[nxt] = flow_count.get(nxt, 0) + 1
                current = nxt
                steps += 1

        # 3. Erosion: reduce elevation proportional to flow.
        for h in all_hexes:
            fc = flow_count.get(h, 0)
            if fc > 0:
                elev[h] -= params.erosion_rate * math.log(1 + fc)

        # 4. Deposition: where flow slows, add sediment.
        for h in all_hexes:
            upstream = flow_to.get(h)
            if upstream is None:
                continue
            # h flows TO somewhere; check if upstream flows to h
            # (i.e., h is downstream of upstream).
            fc_h = flow_count.get(h, 0)
            fc_up = flow_count.get(upstream, 0)
            if fc_h < fc_up and fc_up > 0:
                delta = (fc_up - fc_h)
                elev[h] += params.deposit_rate * delta * 0.01

        # 5. Clamp.
        for h in all_hexes:
            elev[h] = max(-1.0, min(1.0, elev[h]))

    # Drainage basin identification: follow flow_to to the sink,
    # group hexes by their terminal sink.
    basins: dict[HexCoord, int] = {}
    sink_to_basin: dict[HexCoord, int] = {}
    next_basin = 0

    for h in all_hexes:
        # Walk to the sink.
        current = h
        steps = 0
        while flow_to.get(current) is not None and steps < 30:
            current = flow_to[current]  # type: ignore[assignment]
            steps += 1
        sink = current
        if sink not in sink_to_basin:
            sink_to_basin[sink] = next_basin
            next_basin += 1
        basins[h] = sink_to_basin[sink]

    # Moisture enhancement in high-flow areas.
    max_flow = max(flow_count.values()) if flow_count else 1
    log_max = math.log(1 + max_flow)
    if log_max > 0:
        for h in all_hexes:
            fc = flow_count.get(h, 0)
            if fc > 0:
                moisture[h] += (
                    0.2 * math.log(1 + fc) / log_max
                )

    return ErosionResult(
        elevation=elev,
        moisture=moisture,
        flow_to=dict(flow_to),
        flow_count=flow_count,
        basins=basins,
    )
