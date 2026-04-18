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

from nhc.hexcrawl.coords import (
    HexCoord,
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
