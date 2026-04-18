#!/usr/bin/env python3
"""Generate sample hexcrawl map PNGs for visual inspection.

Usage:
    python -m tests.samples.generate_hexmap [--seed SEED] [--generator bsp|perlin]
    python -m tests.samples.generate_hexmap --seeds 1,2,3
    python -m tests.samples.generate_hexmap --seed 42 --flower 5,3

Outputs PNG images of hex maps (and optionally individual hex
flowers) to debug/ for evaluating generation quality without
running the game server.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.stderr.write(
        "This tool needs Pillow. Install with:\n"
        "  .venv/bin/pip install Pillow\n"
    )
    sys.exit(2)

from nhc.hexcrawl.coords import HexCoord, to_pixel
from nhc.hexcrawl.generator import (
    generate_test_world,
    generate_perlin_world,
)
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
    HexFlower,
    HexWorld,
    FLOWER_COORDS,
)
from nhc.hexcrawl.pack import load_pack


# ── Tile path resolution ───────────────────────────────────────

HEXTILES = Path(__file__).resolve().parents[2] / "hextiles"

# Import from the canonical backend module.
from nhc.hexcrawl.tiles import SLOT_NAME

FEATURE_LABELS: dict[str, str] = {
    "village": "V", "city": "C", "tower": "T", "keep": "K",
    "cave": "Ca", "ruin": "R", "hole": "H", "graveyard": "G",
    "crystals": "Cr", "stones": "St", "wonder": "W",
    "portal": "P", "lake": "L", "river": "Rv",
}


def _tile_path_from_slot(biome: str, slot: int) -> Path:
    """Build the tile PNG path from biome + slot (assigned at
    generation time by nhc.hexcrawl.tiles)."""
    stem = SLOT_NAME[slot]
    return HEXTILES / biome / f"{slot}-{biome}_{stem}.png"


_TILE_CACHE: dict[Path, Image.Image] = {}


def _load_tile(path: Path) -> Image.Image:
    """Load and cache a biome tile PNG."""
    if path not in _TILE_CACHE:
        _TILE_CACHE[path] = Image.open(path).convert("RGBA")
    return _TILE_CACHE[path]


# ── Jitter hash (mirrors hex_map.js _jitterHash) ──────────────

def _jitter_hash(a: int, b: int, c: int) -> int:
    h = (a * 7919 + b * 104729 + c * 34159) & 0x7FFFFFFF
    h = ((h >> 16) ^ h) * 0x45D9F3B
    return ((h >> 16) ^ h) & 0x7FFFFFFF


# ── Catmull-Rom spline (mirrors hex_map.js _drawSubPathCurve) ──

def _catmull_rom_points(
    pts: list[tuple[float, float]],
    steps_per_segment: int = 8,
    tension: float = 0.5,
) -> list[tuple[float, float]]:
    """Compute Catmull-Rom spline through control points."""
    if len(pts) < 2:
        return list(pts)
    result: list[tuple[float, float]] = [pts[0]]
    for i in range(len(pts) - 1):
        p0 = pts[max(0, i - 1)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(len(pts) - 1, i + 2)]
        cp1x = p1[0] + (p2[0] - p0[0]) / (6 * tension)
        cp1y = p1[1] + (p2[1] - p0[1]) / (6 * tension)
        cp2x = p2[0] - (p3[0] - p1[0]) / (6 * tension)
        cp2y = p2[1] - (p3[1] - p1[1]) / (6 * tension)
        for t in range(1, steps_per_segment + 1):
            f = t / steps_per_segment
            g = 1.0 - f
            x = (g ** 3 * p1[0]
                 + 3 * g ** 2 * f * cp1x
                 + 3 * g * f ** 2 * cp2x
                 + f ** 3 * p2[0])
            y = (g ** 3 * p1[1]
                 + 3 * g ** 2 * f * cp1y
                 + 3 * g * f ** 2 * cp2y
                 + f ** 3 * p2[1])
            result.append((x, y))
    return result


# ── Hex map renderer ───────────────────────────────────────────

# Tile PNGs are 238x207; hex radius = 119
TILE_W = 238
TILE_H = 207
HEX_RADIUS = TILE_W / 2  # 119
MARGIN = int(HEX_RADIUS)


def render_hexmap(world: HexWorld, outpath: Path) -> None:
    """Render a HexWorld to a PNG image."""
    pw, ph, min_x, min_y = world.pixel_bbox(HEX_RADIUS)
    cw = int(pw) + 2 * MARGIN
    ch = int(ph) + 2 * MARGIN

    canvas = Image.new("RGBA", (cw, ch), (20, 20, 24, 255))

    # Pass 1: composite tile PNGs
    for coord, cell in world.cells.items():
        px, py = to_pixel(coord, HEX_RADIUS)
        sx = int(px - min_x + MARGIN - TILE_W / 2)
        sy = int(py - min_y + MARGIN - TILE_H / 2)

        tp = _tile_path_from_slot(cell.biome.value, cell.tile_slot)
        try:
            tile = _load_tile(tp)
        except Exception:
            continue
        canvas.paste(tile, (sx, sy), tile)

    # Pass 2: draw rivers and roads
    draw = ImageDraw.Draw(canvas)
    for coord, cell in world.cells.items():
        if not cell.edges:
            continue
        cx, cy = to_pixel(coord, HEX_RADIUS)
        ox = cx - min_x + MARGIN
        oy = cy - min_y + MARGIN

        for seg in cell.edges:
            is_river = seg.type == "river"
            # Try sub_path from flower
            sub_path = None
            if cell.flower:
                for fseg in cell.flower.edges:
                    if (fseg.type == seg.type
                            and fseg.entry_macro_edge == seg.entry_edge
                            and fseg.exit_macro_edge == seg.exit_edge):
                        sub_path = fseg.path
                        break

            if sub_path and len(sub_path) >= 2:
                scale = HEX_RADIUS / 2.5
                s3 = math.sqrt(3)
                jitter = HEX_RADIUS * 0.20
                last = len(sub_path) - 1
                pts = []
                for i, p in enumerate(sub_path):
                    bx = ox + scale * 1.5 * p.q
                    by = oy + scale * (s3 / 2 * p.q + s3 * p.r)
                    # Don't jitter first/last points — they sit
                    # on hex edges and must align with neighbors.
                    if i == 0 or i == last:
                        pts.append((bx, by))
                        continue
                    h1 = _jitter_hash(p.q, p.r, i * 2)
                    h2 = _jitter_hash(p.q, p.r, i * 2 + 1)
                    jx = ((h1 % 1000) / 500 - 1) * jitter
                    jy = ((h2 % 1000) / 500 - 1) * jitter
                    pts.append((bx + jx, by + jy))
                curve = _catmull_rom_points(pts)
            else:
                # Fallback: edge midpoint to edge midpoint
                curve = _fallback_curve(ox, oy, seg)

            if len(curve) >= 2:
                # Outline
                outline_color = ((15, 40, 100, 153) if is_river
                                 else (0, 0, 0, 153))
                fill_color = ((40, 100, 200, 191) if is_river
                              else (120, 80, 40, 178))
                outline_w = int(HEX_RADIUS * 0.06)
                fill_w = int(HEX_RADIUS * 0.04)
                draw.line(curve, fill=outline_color,
                          width=max(1, outline_w), joint="curve")
                draw.line(curve, fill=fill_color,
                          width=max(1, fill_w), joint="curve")

    # Pass 3: feature labels
    for coord, cell in world.cells.items():
        feat = cell.feature.value
        if feat == "none":
            continue
        label = FEATURE_LABELS.get(feat, feat[0].upper())
        px, py = to_pixel(coord, HEX_RADIUS)
        sx = px - min_x + MARGIN
        sy = py - min_y + MARGIN + TILE_H * 0.3
        draw.text((sx, sy), label, fill=(245, 222, 162, 200),
                  anchor="mm")

    canvas = canvas.convert("RGB")
    canvas.save(outpath)


def _fallback_curve(
    cx: float, cy: float, seg,
) -> list[tuple[float, float]]:
    """Simple quadratic arc between entry/exit edge midpoints."""
    s3 = math.sqrt(3)
    mids = [
        (0, -HEX_RADIUS * s3 / 2),
        (3 * HEX_RADIUS / 4, -HEX_RADIUS * s3 / 4),
        (3 * HEX_RADIUS / 4, HEX_RADIUS * s3 / 4),
        (0, HEX_RADIUS * s3 / 2),
        (-3 * HEX_RADIUS / 4, HEX_RADIUS * s3 / 4),
        (-3 * HEX_RADIUS / 4, -HEX_RADIUS * s3 / 4),
    ]
    if seg.entry_edge is not None:
        dx, dy = mids[seg.entry_edge]
        p0 = (cx + dx, cy + dy)
    else:
        p0 = (cx, cy)
    if seg.exit_edge is not None:
        dx, dy = mids[seg.exit_edge]
        p1 = (cx + dx, cy + dy)
    else:
        p1 = (cx, cy)
    mid = ((p0[0] + p1[0]) / 2 + (cx - (p0[0] + p1[0]) / 2) * 0.3,
           (p0[1] + p1[1]) / 2 + (cy - (p0[1] + p1[1]) / 2) * 0.3)
    return [p0, mid, p1]


# ── Hex flower renderer ───────────────────────────────────────

FLOWER_HEX_RADIUS = 60
FLOWER_TILE_SCALE = TILE_W / (2 * FLOWER_HEX_RADIUS)


def render_flower(
    world: HexWorld,
    macro_coord: HexCoord,
    outpath: Path,
) -> None:
    """Render a single hex flower to a PNG image."""
    cell = world.cells.get(macro_coord)
    if cell is None or cell.flower is None:
        print(f"No flower at ({macro_coord.q}, {macro_coord.r})")
        return

    flower = cell.flower
    R = FLOWER_HEX_RADIUS
    s3 = math.sqrt(3)

    # Compute flower pixel bounds
    all_px = []
    all_py = []
    for c in FLOWER_COORDS:
        fx = R * 1.5 * c.q
        fy = R * (s3 / 2 * c.q + s3 * c.r)
        all_px.append(fx)
        all_py.append(fy)
    min_fx = min(all_px) - R
    min_fy = min(all_py) - R
    max_fx = max(all_px) + R
    max_fy = max(all_py) + R
    margin = int(R * 0.5)
    cw = int(max_fx - min_fx) + 2 * margin
    ch = int(max_fy - min_fy) + 2 * margin

    canvas = Image.new("RGBA", (cw, ch), (20, 20, 24, 255))
    tile_cache: dict[Path, Image.Image] = {}

    # Draw sub-hex tiles
    for sub_coord, sub_cell in flower.cells.items():
        fx = R * 1.5 * sub_coord.q
        fy = R * (s3 / 2 * sub_coord.q + s3 * sub_coord.r)
        sx = int(fx - min_fx + margin)
        sy = int(fy - min_fy + margin)

        biome_str = sub_cell.biome.value
        tp = _tile_path_from_slot(biome_str, sub_cell.tile_slot)
        cache_key = tp
        if cache_key not in tile_cache:
            try:
                img = _load_tile(tp)
                tw = int(2 * R)
                th = int(s3 * R)
                img = img.resize((tw, th), Image.LANCZOS)
                tile_cache[cache_key] = img
            except Exception:
                continue
        tile = tile_cache[cache_key]
        tw, th = tile.size
        canvas.paste(tile, (sx - tw // 2, sy - th // 2), tile)

    # Draw river/road edge segments
    draw = ImageDraw.Draw(canvas)
    jitter = R * 0.35

    # Macro hex edge midpoints in flower pixel coords.
    # NEIGHBOR_OFFSETS: N, NE, SE, S, SW, NW
    from nhc.hexcrawl.coords import NEIGHBOR_OFFSETS
    _edge_midpoints: list[tuple[float, float]] = []
    for dq, dr in NEIGHBOR_OFFSETS:
        # Edge midpoint is ~2.5 sub-hex radii from center
        ex = R * 1.5 * dq * 2.5 - min_fx + margin
        ey = R * (s3 / 2 * dq + s3 * dr) * 2.5 - min_fy + margin
        _edge_midpoints.append((ex, ey))

    for seg in flower.edges:
        if not seg.path or len(seg.path) < 2:
            continue
        is_river = seg.type == "river"
        last_idx = len(seg.path) - 1
        pts: list[tuple[float, float]] = []

        # Prepend entry edge point so the curve starts at
        # the flower boundary, not at the ring-2 sub-hex center.
        if seg.entry_macro_edge is not None:
            pts.append(_edge_midpoints[seg.entry_macro_edge])

        for i, p in enumerate(seg.path):
            bx = R * 1.5 * p.q - min_fx + margin
            by = R * (s3 / 2 * p.q + s3 * p.r) - min_fy + margin
            if i == 0 or i == last_idx:
                pts.append((bx, by))
                continue
            h1 = _jitter_hash(p.q, p.r, i * 2)
            h2 = _jitter_hash(p.q, p.r, i * 2 + 1)
            jx = ((h1 % 1000) / 500 - 1) * jitter
            jy = ((h2 % 1000) / 500 - 1) * jitter
            pts.append((bx + jx, by + jy))

        # Append exit edge point so the curve reaches the
        # flower boundary on the exit side.
        if seg.exit_macro_edge is not None:
            pts.append(_edge_midpoints[seg.exit_macro_edge])

        curve = _catmull_rom_points(pts)
        if len(curve) >= 2:
            outline_color = ((15, 40, 100, 153) if is_river
                             else (0, 0, 0, 128))
            fill_color = ((40, 100, 200, 191) if is_river
                          else (120, 80, 40, 178))
            outline_w = int(R * 0.22)
            fill_w = int(R * 0.15)
            draw.line(curve, fill=outline_color,
                      width=max(2, outline_w), joint="curve")
            draw.line(curve, fill=fill_color,
                      width=max(2, fill_w), joint="curve")

    canvas = canvas.convert("RGB")
    canvas.save(outpath)


# ── Pack loading ───────────────────────────────────────────────

def _find_pack(generator: str) -> Path:
    """Find the appropriate content pack for the generator type."""
    content = Path(__file__).resolve().parents[2] / "content"
    if generator == "perlin":
        pack_path = content / "testland-perlin" / "pack.yaml"
        if pack_path.is_file():
            return pack_path
    pack_path = content / "testland" / "pack.yaml"
    if pack_path.is_file():
        return pack_path
    raise FileNotFoundError(
        f"no pack.yaml found under {content}"
    )


# ── CLI ────────────────────────────────────────────────────────

def generate(
    outdir: Path,
    seeds: list[int],
    generator: str,
    flower_coord: tuple[int, int] | None,
) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    pack_path = _find_pack(generator)
    pack = load_pack(pack_path)

    gen_fn = (generate_perlin_world if generator == "perlin"
              else generate_test_world)

    for seed in seeds:
        print(f"Generating {generator} map with seed {seed}...")
        world = gen_fn(seed, pack)

        # Stats
        biomes: dict[str, int] = {}
        features: dict[str, int] = {}
        river_hexes = 0
        for cell in world.cells.values():
            b = cell.biome.value
            biomes[b] = biomes.get(b, 0) + 1
            f = cell.feature.value
            if f != "none":
                features[f] = features.get(f, 0) + 1
            if any(e.type == "river" for e in cell.edges):
                river_hexes += 1

        total = len(world.cells)
        print(f"  {total} hexes, {river_hexes} with rivers "
              f"({100 * river_hexes / total:.0f}%)")
        print(f"  biomes: {biomes}")
        print(f"  features: {features}")
        print(f"  rivers: {len(world.rivers)}, "
              f"paths: {len(world.paths)}")

        # Render hex map
        map_path = outdir / f"hexmap_seed{seed}_{generator}.png"
        render_hexmap(world, map_path)
        print(f"  → {map_path}")

        # Render flower if requested
        if flower_coord is not None:
            fq, fr = flower_coord
            fc = HexCoord(fq, fr)
            flower_path = (
                outdir / f"flower_seed{seed}_{fq}_{fr}.png"
            )
            render_flower(world, fc, flower_path)
            print(f"  → {flower_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--outdir", type=Path, default=Path("debug"),
        help="output directory (default: debug/)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="single seed (default: random)",
    )
    parser.add_argument(
        "--seeds", type=str, default=None,
        help="comma-separated seeds",
    )
    parser.add_argument(
        "--generator", choices=["bsp", "perlin"], default="bsp",
        help="generator type (default: bsp)",
    )
    parser.add_argument(
        "--flower", type=str, default=None,
        help="render flower at q,r (e.g. --flower 5,3)",
    )
    args = parser.parse_args(argv)

    if args.seeds:
        seeds = [int(s) for s in args.seeds.split(",")]
    elif args.seed is not None:
        seeds = [args.seed]
    else:
        import random
        seeds = [random.randrange(1 << 30)]

    flower_coord = None
    if args.flower:
        parts = args.flower.split(",")
        flower_coord = (int(parts[0]), int(parts[1]))

    generate(args.outdir, seeds, args.generator, flower_coord)


if __name__ == "__main__":
    main()
