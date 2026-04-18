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
from nhc.hexcrawl.model import Biome, HexCell, HexWorld
from nhc.hexcrawl.noise import SimplexNoise
from nhc.hexcrawl.pack import ContinentalParams, PackMeta


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

            # Continent bias: shift noise upward so more hexes
            # are above sea level (more land, less ocean).
            raw += params.continent_bias

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
        raw += params.continent_bias

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
            boost = rng.uniform(0.10, 0.20)
        elif bh in plates.divergent:
            boost = -0.05
        else:
            boost = 0.0
        boost_map[bh] = boost

    # Apply boosts only to the boundary hex itself (no fade)
    # to keep mountain ranges narrow and avoid inflating the
    # elevation of half the map.
    accumulated: dict[HexCoord, float] = {}
    for bh, boost in boost_map.items():
        accumulated[bh] = accumulated.get(bh, 0.0) + boost

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


# ---------------------------------------------------------------------------
# Stage 5: Biome assignment
# ---------------------------------------------------------------------------


def _biome_from_em(
    e: float,
    m: float,
    sea_level: float,
    is_near_convergent: bool,
    latitude: float,
) -> Biome:
    """Whittaker-style biome lookup from elevation and moisture.

    *latitude* is a normalised value from -1 (north) to +1
    (south). Cold biomes (icelands) are pushed north, warm
    biomes (sandlands, drylands) are pushed south.
    """
    if e < sea_level:
        return Biome.WATER

    # Mountain threshold is lower near convergent boundaries
    # to create coherent mountain ranges.
    mt_threshold = 0.75 if is_near_convergent else 0.85
    if e >= mt_threshold:
        return Biome.MOUNTAIN
    if e >= 0.60:
        return Biome.HILLS if m >= 0.20 else Biome.DRYLANDS

    # Mid-elevation band: latitude influences biome choice.
    if e >= 0.35:
        if m >= 0.30:
            return Biome.FOREST
        if m >= -0.20:
            # Cold latitudes get icelands instead of greenlands
            if latitude < -0.5:
                return Biome.ICELANDS
            return Biome.GREENLANDS
        # Warm latitudes get sandlands, cold get icelands
        if latitude > 0.3:
            return Biome.SANDLANDS
        if latitude < -0.5:
            return Biome.ICELANDS
        return Biome.DRYLANDS

    # Low-elevation band: strong latitude influence.
    if e >= 0.10:
        if latitude < -0.4:
            # Northern low ground: icelands or tundra
            if m >= 0.30:
                return Biome.MARSH
            return Biome.ICELANDS
        if latitude > 0.4:
            # Southern low ground: hot and dry
            if m >= 0.60:
                return Biome.SWAMP
            if m >= 0.20:
                return Biome.MARSH
            return Biome.SANDLANDS
        # Temperate low ground
        if m >= 0.60:
            return Biome.SWAMP
        if m >= 0.20:
            return Biome.MARSH
        if m >= -0.30:
            return Biome.GREENLANDS
        return Biome.DEADLANDS

    # Very low elevation: latitude-driven
    if latitude < -0.2:
        return Biome.ICELANDS
    if latitude > 0.3:
        return Biome.SANDLANDS
    return Biome.DEADLANDS


# Essential biomes that must exist for feature placement.
_ESSENTIAL_FALLBACKS: tuple[tuple[Biome, tuple[Biome, ...]], ...] = (
    (Biome.GREENLANDS, (Biome.DRYLANDS, Biome.FOREST)),
    (Biome.MOUNTAIN, (Biome.HILLS, Biome.DRYLANDS)),
    (Biome.FOREST, (Biome.GREENLANDS, Biome.SWAMP)),
    (Biome.ICELANDS, (Biome.DEADLANDS, Biome.MARSH)),
)


def _repair_essentials(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    rng: random.Random,
) -> None:
    """Guarantee every essential biome exists."""
    for essential, donors in _ESSENTIAL_FALLBACKS:
        if hexes_by_biome[essential]:
            continue
        for donor in donors:
            if len(hexes_by_biome[donor]) > 1:
                victim = rng.choice(hexes_by_biome[donor])
                cells[victim].biome = essential
                if essential is Biome.MOUNTAIN:
                    cells[victim].elevation = 0.80
                hexes_by_biome[donor].remove(victim)
                hexes_by_biome[essential].append(victim)
                break


def _remove_interior_water(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    width: int,
    height: int,
) -> None:
    """Convert interior water to land biomes.

    Flood-fill from edge water hexes. Any water hex not
    reachable from the map edge is interior and gets converted
    to marsh (wet) or greenlands (dry) based on moisture.
    """
    from nhc.hexcrawl.coords import valid_shape_hex

    water_hexes = set(hexes_by_biome[Biome.WATER])
    if not water_hexes:
        return

    # Find edge hexes: hexes where at least one neighbor is
    # outside the map bounds.
    edge_water: set[HexCoord] = set()
    for h in water_hexes:
        for nbr in neighbors(h):
            if not valid_shape_hex(nbr.q, nbr.r, width, height):
                edge_water.add(h)
                break

    # Flood-fill from edge water to find all coastal/ocean water.
    coastal: set[HexCoord] = set(edge_water)
    frontier = list(edge_water)
    while frontier:
        current = frontier.pop()
        for nbr in neighbors(current):
            if nbr in water_hexes and nbr not in coastal:
                coastal.add(nbr)
                frontier.append(nbr)

    # Interior water: water hexes not connected to the edge.
    # Convert to a land biome that fits the latitude.
    all_r = [h.r for h in cells]
    r_min_val = min(all_r)
    r_span = max(max(all_r) - r_min_val, 1)
    interior = water_hexes - coastal
    for h in interior:
        cell = cells[h]
        latitude = 2.0 * (h.r - r_min_val) / r_span - 1.0
        if latitude < -0.4:
            new_biome = Biome.ICELANDS
        elif latitude > 0.4:
            new_biome = Biome.SANDLANDS
        else:
            new_biome = Biome.GREENLANDS
        cell.biome = new_biome
        hexes_by_biome[Biome.WATER].remove(h)
        hexes_by_biome[new_biome].append(h)


def assign_biomes(
    rng: random.Random,
    params: ContinentalParams,
    erosion: ErosionResult,
    plates: PlateResult,
    width: int,
    height: int,
) -> tuple[dict[HexCoord, HexCell], dict[Biome, list[HexCoord]]]:
    """Map post-erosion elevation + moisture to biomes.

    Returns ``(cells, hexes_by_biome)`` where cells is a dict
    of :class:`HexCell` keyed by coordinate.
    """
    # Pre-compute which hexes are near convergent boundaries
    # (within 2 hexes) for mountain threshold lowering.
    near_convergent: set[HexCoord] = set()
    for bh in plates.convergent:
        near_convergent.add(bh)
        for d in (1, 2):
            for h in ring(bh, d):
                if h in erosion.elevation:
                    near_convergent.add(h)

    # Compute the r range for latitude normalisation.
    all_r = [h.r for h in erosion.elevation]
    r_min_val = min(all_r)
    r_max_val = max(all_r)
    r_span = max(r_max_val - r_min_val, 1)

    cells: dict[HexCoord, HexCell] = {}
    hexes_by_biome: dict[Biome, list[HexCoord]] = {
        b: [] for b in Biome
    }

    for h in erosion.elevation:
        e = erosion.elevation[h]
        m = erosion.moisture[h]
        # Latitude: -1 = north (low r), +1 = south (high r).
        latitude = 2.0 * (h.r - r_min_val) / r_span - 1.0
        biome = _biome_from_em(
            e, m, params.sea_level, h in near_convergent,
            latitude,
        )
        cell = HexCell(coord=h, biome=biome, elevation=e)
        cells[h] = cell
        hexes_by_biome[biome].append(h)

    # Remove interior water pockets (land-locked water tiles).
    _remove_interior_water(cells, hexes_by_biome, width, height)

    _repair_essentials(cells, hexes_by_biome, rng)

    return cells, hexes_by_biome


# ---------------------------------------------------------------------------
# Stage 9: Edge-point continuity (macro offsets)
# ---------------------------------------------------------------------------


def _edge_hash(
    aq: int, ar: int, bq: int, br: int, extra: int = 0,
) -> int:
    """Deterministic hash for edge-point allocation.

    Same family as the jitter hash used by both renderers.
    """
    h = (aq * 7919 + ar * 104729
         + bq * 34159 + br * 65537
         + extra * 48611) & 0x7FFFFFFF
    h = ((h >> 16) ^ h) * 0x45D9F3B
    return ((h >> 16) ^ h) & 0x7FFFFFFF


def _assign_macro_offsets(
    cells: dict[HexCoord, HexCell],
) -> None:
    """Assign random edge-crossing offsets to all edge segments.

    For each shared edge between adjacent hexes, compute a
    deterministic random offset in ``[-0.4, +0.4]`` and assign it
    to the exit_offset of the upstream hex and the entry_offset of
    the downstream hex so they share the same physical point.
    """
    # Cache: canonical edge key -> offset.
    cache: dict[tuple[int, int, int, int, str], float] = {}

    for coord, cell in cells.items():
        for seg in cell.edges:
            # Entry offset.
            if seg.entry_edge is not None:
                nbrs = neighbors(coord)
                nbr = nbrs[seg.entry_edge]
                # Canonical key: smaller coord first.
                if (coord.q, coord.r) < (nbr.q, nbr.r):
                    key = (coord.q, coord.r, nbr.q, nbr.r, seg.type)
                else:
                    key = (nbr.q, nbr.r, coord.q, coord.r, seg.type)
                if key not in cache:
                    h = _edge_hash(*key[:4])
                    cache[key] = ((h % 81) - 40) / 100.0
                seg.entry_offset = cache[key]

            # Exit offset.
            if seg.exit_edge is not None:
                nbrs = neighbors(coord)
                nbr = nbrs[seg.exit_edge]
                if (coord.q, coord.r) < (nbr.q, nbr.r):
                    key = (coord.q, coord.r, nbr.q, nbr.r, seg.type)
                else:
                    key = (nbr.q, nbr.r, coord.q, coord.r, seg.type)
                if key not in cache:
                    h = _edge_hash(*key[:4])
                    cache[key] = ((h % 81) - 40) / 100.0
                seg.exit_offset = cache[key]


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


class GeneratorRetryError(RuntimeError):
    """Raised after exhausting retry attempts."""


def _attempt_continental(
    rng: random.Random,
    pack: PackMeta,
) -> HexWorld:
    """Run the full pipeline once, returning a HexWorld."""
    from nhc.hexcrawl._features import (
        FeaturePlacementError,
        place_features as _place_features,
    )
    from nhc.hexcrawl._rivers_v2 import generate_rivers_v2
    from nhc.hexcrawl._paths_v2 import generate_paths_v2
    from nhc.hexcrawl._flowers import generate_flowers as _gen_flowers
    from nhc.hexcrawl.tiles import assign_tile_slot as _assign_slot

    mp = pack.map
    cp = mp.continental
    assert cp is not None

    # Stage 1: Continental shape.
    field = continental_shape(rng, cp, mp.width, mp.height)

    # Stage 2: Tectonic plates.
    plates = tectonic_plates(rng, cp, field)

    # Stage 3: Domain warping.
    warped = domain_warp(
        rng, cp, field, plates, mp.width, mp.height,
    )

    # Stage 4: Hydraulic erosion.
    erosion = hydraulic_erosion(rng, cp, warped)

    # Stage 5: Biome assignment.
    cells, hexes_by_biome = assign_biomes(
        rng, cp, erosion, plates, mp.width, mp.height,
    )

    # Stage 6: Rivers.
    rivers = generate_rivers_v2(
        cells, rng, pack.rivers, cp, erosion.flow_count,
    )

    # Stage 7+: Features (settlements, dungeons, wonders).
    # Reuse the existing v1 feature placer which handles hubs,
    # villages, dungeons, wonders, and cave clustering.
    hub, clusters = _place_features(cells, hexes_by_biome, pack, rng)

    # Stage 8: Roads.
    paths = generate_paths_v2(cells, rng, pack.paths)

    # Stage 9: Edge-point offsets.
    _assign_macro_offsets(cells)

    # Flowers.
    world_seed = rng.randrange(1 << 30)
    _gen_flowers(cells, world_seed)

    # Tile slots.
    for coord, cell in cells.items():
        has_ww = any(e.type == "river" for e in cell.edges)
        cell.tile_slot = _assign_slot(
            cell.biome.value, cell.feature.value,
            coord.q, coord.r, has_ww,
        )

    world = HexWorld(
        pack_id=pack.id,
        seed=world_seed,
        width=mp.width,
        height=mp.height,
        biome_costs=dict(pack.biome_costs),
    )
    for cell in cells.values():
        world.set_cell(cell)
    world.last_hub = hub
    world.cave_clusters = clusters
    world.rivers = rivers
    world.paths = paths
    return world


def generate_continental_world(
    seed: int,
    pack: PackMeta,
    max_attempts: int = 10,
) -> HexWorld:
    """Generate a geologically-inspired :class:`HexWorld`.

    Nine-stage pipeline: simplex continents, Voronoi plates,
    domain warping, flow-accumulation erosion, Whittaker biomes,
    rivers, scored settlements, terrain-aware roads, and edge-
    point continuity.

    Retries up to ``max_attempts`` times if feature placement
    can't meet the pack's targets.
    """
    from nhc.hexcrawl._features import FeaturePlacementError

    rng = random.Random(seed)
    last_err: str | None = None
    for _ in range(max_attempts):
        try:
            return _attempt_continental(rng, pack)
        except FeaturePlacementError as exc:
            last_err = str(exc)
    raise GeneratorRetryError(
        f"exhausted {max_attempts} attempts; last error: {last_err}"
    )
