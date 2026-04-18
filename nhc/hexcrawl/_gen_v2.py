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
