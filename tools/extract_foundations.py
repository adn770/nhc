#!/usr/bin/env python3
"""Extract foundation-style feature overlays from full-body hex tiles.

Given a directory of complete biome tiles (hex-shaped PNGs with
a solid biome-colour backdrop + feature detail drawn on top),
this tool strips the backdrop via colour-key masking and emits
alpha-masked overlays where only the feature silhouette is
opaque — the same shape our ``generate_missing_hextiles.py``
tool composites over a flat biome background.

The primary use case is the CC-licensed forestPack tileset
(``~/src/forestPack/``), whose tiles are pointy-top 222×255
full-body forest hexes. The extracted features land as flat-top
238×207 foundation-compatible PNGs ready for use as new or
alternative slots in the ``hextiles/`` pipeline.

Algorithm
---------

1. **Colour-key floor removal.** Two reference centres (light
   grass + shadow grass) define a band in RGB space. Pixels
   inside the band (with feathered alpha at the edges) are
   treated as "biome backdrop" and masked out.

2. **Erosion crop.** A morphological erosion (``MinFilter``)
   shrinks the source hex's opaque region inward by N pixels,
   cutting the hex-silhouette outline so the output carries
   no trace of the source hex shape.

3. **Halo cleanup.** Semi-transparent transitional pixels below
   a threshold are dropped; those above the threshold are
   darkened (RGB × factor) and pushed to full opacity so they
   read as shadow rather than a bright fringe on a different-
   coloured background.

Usage
-----

    .venv/bin/python tools/extract_foundations.py \\
        ~/src/forestPack \\
        --out hextiles/foundations_forest

Add ``--dry-run`` to list actions without writing files.

Tuning flags (defaults match forestPack v5 calibration):

    --floor-light R,G,B     Light-grass floor centre (136,176,104)
    --floor-shadow R,G,B    Shadow-grass floor centre (104,136,88)
    --radius-light N        Tolerance radius for light centre (52)
    --radius-shadow N       Tolerance radius for shadow centre (40)
    --feather N             Feather band width at sphere edges (10)
    --erode N               Erosion pixels to crop hex outline (4)
    --halo-drop N           Alpha below this → transparent (50)
    --halo-darken F         RGB multiplier for kept halos (0.70)
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageFilter
except ImportError:
    sys.stderr.write(
        "This tool needs Pillow. Install with:\n"
        "  .venv/bin/pip install Pillow\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Defaults (forestPack v5 calibration)
# ---------------------------------------------------------------------------

DEFAULT_FLOOR_LIGHT = (136, 176, 104)
DEFAULT_FLOOR_SHADOW = (104, 136, 88)
DEFAULT_RADIUS_LIGHT = 52
DEFAULT_RADIUS_SHADOW = 40
DEFAULT_FEATHER = 10
DEFAULT_ERODE = 4
DEFAULT_HALO_DROP = 50
DEFAULT_HALO_DARKEN = 0.70


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


def _min_signed_dist(
    r: int, g: int, b: int,
    centres: list[tuple[tuple[int, int, int], int]],
) -> float:
    """Signed distance from the closest floor sphere's surface.

    Negative = inside a sphere (floor-like).
    Positive = outside all spheres (feature-like).
    """
    best = float("inf")
    for (cr, cg, cb), radius in centres:
        d = math.sqrt(
            (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        )
        best = min(best, d - radius)
    return best


def _erode_mask(img: Image.Image, radius: int) -> Image.Image:
    """Binary erosion: shrink the opaque region inward by
    ``radius`` pixels. Returns an 'L' mask (255 = interior)."""
    alpha = img.split()[3]
    binary = alpha.point(lambda a: 255 if a == 255 else 0)
    eroded = binary
    for _ in range(radius):
        eroded = eroded.filter(ImageFilter.MinFilter(3))
    return eroded


def extract_features(
    src_path: Path,
    dst_path: Path,
    *,
    centres: list[tuple[tuple[int, int, int], int]],
    feather: int,
    erode_px: int,
    halo_drop: int,
    halo_darken: float,
) -> tuple[Image.Image, int, int]:
    """Extract feature pixels from ``src_path``.

    Returns ``(image, kept_pixels, total_opaque_pixels)``. The
    caller saves the image (possibly after a recanvas step).
    """
    img = Image.open(src_path).convert("RGBA")
    w, h = img.size

    # Build the eroded interior mask BEFORE mutating pixels.
    interior = _erode_mask(img, erode_px)
    interior_px = interior.load()

    px = img.load()
    total = 0

    # Pass 1: colour-key floor removal.
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            total += 1
            d = _min_signed_dist(r, g, b, centres)
            if d <= -feather:
                px[x, y] = (r, g, b, 0)
            elif d <= 0:
                t = (d + feather) / feather
                px[x, y] = (r, g, b, int(a * t))

    # Pass 2: crop to eroded interior — kills hex-edge pixels.
    for y in range(h):
        for x in range(w):
            if interior_px[x, y] == 0:
                px[x, y] = (0, 0, 0, 0)

    # Pass 3: halo cleanup.
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0 or a == 255:
                continue
            if a < halo_drop:
                px[x, y] = (0, 0, 0, 0)
            else:
                dr = int(r * halo_darken)
                dg = int(g * halo_darken)
                db = int(b * halo_darken)
                px[x, y] = (dr, dg, db, 255)

    kept = sum(
        1 for y in range(h) for x in range(w) if px[x, y][3] > 0
    )
    return img, kept, total


def recanvas(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """Downscale ``img`` to fit inside ``(target_w, target_h)``
    and centre on a transparent canvas of exactly that size.

    Uses LANCZOS resampling so the contour edges come out smooth
    rather than aliased from a nearest-neighbour resize.
    """
    w, h = img.size
    # Uniform scale factor constrained by the tighter axis.
    scale = min(target_w / w, target_h / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    offset_x = (target_w - new_w) // 2
    offset_y = (target_h - new_h) // 2
    canvas.paste(scaled, (offset_x, offset_y), scaled)
    return canvas


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_rgb(s: str) -> tuple[int, int, int]:
    parts = s.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"expected R,G,B (three comma-separated ints), got {s!r}"
        )
    return tuple(int(p.strip()) for p in parts)  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract foundation-style feature overlays from "
            "full-body hex tiles by colour-keying the biome "
            "backdrop."
        ),
    )
    parser.add_argument(
        "source_dir",
        help="Directory of source PNG tiles (e.g. ~/src/forestPack).",
    )
    parser.add_argument(
        "--out", default=None,
        help=(
            "Output directory for extracted PNGs. Defaults to "
            "debug/extracted_foundations."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List actions without writing files.",
    )
    parser.add_argument(
        "--floor-light", type=_parse_rgb,
        default=DEFAULT_FLOOR_LIGHT,
        help=f"Light-grass floor centre R,G,B (default {DEFAULT_FLOOR_LIGHT}).",
    )
    parser.add_argument(
        "--floor-shadow", type=_parse_rgb,
        default=DEFAULT_FLOOR_SHADOW,
        help=f"Shadow-grass floor centre R,G,B (default {DEFAULT_FLOOR_SHADOW}).",
    )
    parser.add_argument(
        "--radius-light", type=int, default=DEFAULT_RADIUS_LIGHT,
        help=f"Tolerance radius for light centre (default {DEFAULT_RADIUS_LIGHT}).",
    )
    parser.add_argument(
        "--radius-shadow", type=int, default=DEFAULT_RADIUS_SHADOW,
        help=f"Tolerance radius for shadow centre (default {DEFAULT_RADIUS_SHADOW}).",
    )
    parser.add_argument(
        "--feather", type=int, default=DEFAULT_FEATHER,
        help=f"Feather band width at sphere edges (default {DEFAULT_FEATHER}).",
    )
    parser.add_argument(
        "--erode", type=int, default=DEFAULT_ERODE,
        help=f"Erosion pixels to crop hex outline (default {DEFAULT_ERODE}).",
    )
    parser.add_argument(
        "--halo-drop", type=int, default=DEFAULT_HALO_DROP,
        help=f"Alpha below this is dropped (default {DEFAULT_HALO_DROP}).",
    )
    parser.add_argument(
        "--halo-darken", type=float, default=DEFAULT_HALO_DARKEN,
        help=f"RGB multiplier for kept halos (default {DEFAULT_HALO_DARKEN}).",
    )
    parser.add_argument(
        "--recanvas", default=None, metavar="WxH",
        help=(
            "After extraction, downscale + centre the feature on a "
            "transparent canvas of exactly WxH pixels (e.g. 238x207 "
            "for the flat-top foundation grid). Uses LANCZOS "
            "resampling to smooth contour edges."
        ),
    )
    args = parser.parse_args()

    source = Path(args.source_dir).expanduser()
    if not source.is_dir():
        print(f"source directory not found: {source}", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else Path("debug/extracted_foundations")

    # Parse --recanvas WxH.
    recanvas_size: tuple[int, int] | None = None
    if args.recanvas:
        try:
            rw, rh = args.recanvas.lower().split("x")
            recanvas_size = (int(rw), int(rh))
        except (ValueError, TypeError):
            print(
                f"--recanvas expects WxH (e.g. 238x207), "
                f"got {args.recanvas!r}",
                file=sys.stderr,
            )
            return 1

    pngs = sorted(source.glob("*.png"))
    if not pngs:
        print(f"no PNG files in {source}", file=sys.stderr)
        return 1

    centres = [
        (args.floor_light, args.radius_light),
        (args.floor_shadow, args.radius_shadow),
    ]

    rc_label = f"  Recanvas={recanvas_size}" if recanvas_size else ""
    print(
        f"Source: {source} ({len(pngs)} tiles)\n"
        f"Output: {out_dir}\n"
        f"Floor centres: light={args.floor_light} r={args.radius_light}, "
        f"shadow={args.floor_shadow} r={args.radius_shadow}\n"
        f"Feather={args.feather}  Erode={args.erode}px  "
        f"Halo-drop={args.halo_drop}  Halo-darken={args.halo_darken}"
        f"{rc_label}\n"
    )

    total_written = 0
    for src in pngs:
        dst = out_dir / src.name
        if args.dry_run:
            print(f"  {src.name} -> {dst}")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        result, kept, total = extract_features(
            src, dst,
            centres=centres,
            feather=args.feather,
            erode_px=args.erode,
            halo_drop=args.halo_drop,
            halo_darken=args.halo_darken,
        )
        if recanvas_size is not None:
            result = recanvas(result, *recanvas_size)
        result.save(dst)
        pct = 100 * kept / total if total else 0
        size_label = f" -> {result.size[0]}x{result.size[1]}" if recanvas_size else ""
        print(f"  {src.name:<32} kept {kept:>6d}/{total:>6d} ({pct:5.1f}%){size_label}")
        total_written += 1

    print(f"\nDone. {total_written} tile(s) written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
