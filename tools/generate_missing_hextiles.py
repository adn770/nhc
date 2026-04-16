#!/usr/bin/env python3
"""Fill in missing biome hextiles by tinting foundation tiles.

The CC-licensed hextile pack ships a full 27-slot palette for five
biomes (greenlands / drylands / sandlands / icelands / deadlands)
and a partial palette for two more (forest / mountain). This tool
closes the gap: for every slot a partial-palette biome is missing,
it takes the foundation tile for that slot, samples the biome's
characteristic background colour from one of its existing tiles,
and writes a tinted copy.

Result: every (biome, slot) pair has a tile on disk, and
hex_map.js's foundation fallback is only ever a safety net rather
than a visible stand-in.

Usage
-----

    .venv/bin/python tools/generate_missing_hextiles.py

The tool is idempotent -- re-running it rewrites the generated
tiles but never touches source tiles you've curated by hand. It
only writes into hextiles/<biome>/ for biomes named in
PARTIAL_BIOMES, and only for slots that don't already exist.

Add ``--force`` to regenerate even already-present tiles.
Add ``--dry-run`` to list what would be written without touching
disk.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.stderr.write(
        "This tool needs Pillow. Install with:\n"
        "  .venv/bin/pip install Pillow\n"
    )
    sys.exit(2)


HEXTILES = Path(__file__).resolve().parents[1] / "hextiles"

# 27-slot filename stems. Must match nhc/web/static/js/hex_map.js
# SLOT_NAME. Update both together if the pack ever renames.
SLOT_NAME: dict[int, str] = {
    1: "vulcano", 2: "forest", 3: "tundra", 4: "trees", 5: "water",
    6: "hills", 7: "river", 8: "portal", 9: "mountains", 10: "lake",
    11: "village", 12: "city", 13: "tower", 14: "community",
    15: "cave", 16: "hole", 17: "dead-Trees", 18: "ruins",
    19: "graveyard", 20: "swamp", 21: "floating-Island",
    22: "keep", 23: "wonder", 24: "cristals", 25: "stones",
    26: "farms", 27: "fog",
}

# Biomes that ship with a partial palette and should be completed
# by tinting. The "sample_slot" is the biome's most
# representative "pure terrain" tile; the tool reads its colour
# to pick a tint.
PARTIAL_BIOMES: dict[str, int] = {
    "forest": 2,      # 2-forest_forest.png   (dense forest canopy)
    "mountain": 9,    # 9-mountain_mountains  (bare rock)
}

"""Foundation tiles are overlays: only the feature silhouette is
opaque, the rest is fully transparent. The right composition is
a biome-coloured hex *beneath* the foundation, so the feature
"stamps" onto a solid biome background. The hex silhouette comes
from an existing biome tile's alpha channel -- see
``HEX_SILHOUETTE_SLOT``."""

# Which slot to use as the source for the hex silhouette (its
# alpha defines "inside the hex"). Same for both biomes since the
# pack's hex shape is uniform across palettes.
HEX_SILHOUETTE_SLOT = 2


@dataclass
class RGB:
    r: int
    g: int
    b: int

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)


def biome_tile(biome: str, slot: int) -> Path:
    stem = SLOT_NAME[slot]
    return HEXTILES / biome / f"{slot}-{biome}_{stem}.png"


def foundation_tile(slot: int) -> Path:
    stem = SLOT_NAME[slot]
    return HEXTILES / f"{slot}-foundation_{stem}.png"


def sample_background_color(tile_path: Path) -> RGB:
    """Approximate the dominant background colour of a tile.

    We take the outer 6-pixel ring (where hex tiles keep their
    terrain background, unobscured by any central feature),
    discard fully-transparent pixels, and return the median RGB.
    Median is robust against the occasional highlight or outline
    pixel the ring catches.
    """
    img = Image.open(tile_path).convert("RGBA")
    w, h = img.size
    ring = 8
    pixels: list[tuple[int, int, int, int]] = []
    raw = img.load()
    for y in range(h):
        for x in range(w):
            in_ring = (
                x < ring or x >= w - ring
                or y < ring or y >= h - ring
            )
            if not in_ring:
                continue
            p = raw[x, y]
            if p[3] < 128:
                continue
            pixels.append(p)
    if not pixels:
        return RGB(128, 128, 128)
    rs = sorted(p[0] for p in pixels)
    gs = sorted(p[1] for p in pixels)
    bs = sorted(p[2] for p in pixels)
    mid = len(rs) // 2
    return RGB(rs[mid], gs[mid], bs[mid])


def _hex_silhouette_mask(biome: str) -> Image.Image:
    """Return an "L" mode image whose non-zero pixels are inside
    the hex shape. Cached per biome; read from the biome's own
    HEX_SILHOUETTE_SLOT tile so the generated tiles align
    pixel-for-pixel with the rest of the palette."""
    src = biome_tile(biome, HEX_SILHOUETTE_SLOT)
    img = Image.open(src).convert("RGBA")
    # The alpha channel is the hex silhouette: opaque = inside,
    # transparent = outside the hex bounding polygon.
    _r, _g, _b, alpha = img.split()
    return alpha


def compose_biome_tile(
    foundation_path: Path,
    biome: str,
    colour: RGB,
) -> Image.Image:
    """Build a biome-specific tile by stamping a foundation feature
    over a solid biome-colour hex.

    Step 1: fill a canvas the size of the foundation with the
    biome's background colour, masked by the hex silhouette (so
    transparent corners stay transparent).
    Step 2: alpha-composite the foundation feature on top; its
    partial-alpha "detail" pixels (village, tundra stipple, cave
    mouth, etc.) land on the solid biome background.
    """
    foundation = Image.open(foundation_path).convert("RGBA")
    w, h = foundation.size
    # 1. Solid-colour background, hex-shaped via silhouette alpha.
    bg = Image.new("RGBA", (w, h), (*colour.as_tuple(), 0))
    silhouette = _hex_silhouette_mask(biome)
    if silhouette.size != (w, h):
        silhouette = silhouette.resize((w, h))
    fill = Image.new("RGBA", (w, h), (*colour.as_tuple(), 255))
    bg.paste(fill, (0, 0), silhouette)
    # 2. Alpha-composite the foundation feature on top.
    return Image.alpha_composite(bg, foundation)


def existing_slots(biome: str) -> set[int]:
    """Slots already present under hextiles/<biome>/."""
    biome_dir = HEXTILES / biome
    if not biome_dir.is_dir():
        return set()
    present: set[int] = set()
    for p in biome_dir.iterdir():
        name = p.name
        # Expect "{slot}-{biome}_{stem}.png"
        if not name.endswith(".png"):
            continue
        slot_str, _, rest = name.partition("-")
        if not slot_str.isdigit():
            continue
        if not rest.startswith(f"{biome}_"):
            continue
        present.add(int(slot_str))
    return present


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tint foundation tiles to fill missing biome slots.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite biome tiles even when they already exist.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List actions without touching disk.",
    )
    args = parser.parse_args()

    if not HEXTILES.is_dir():
        print(f"hextiles/ not found at {HEXTILES}", file=sys.stderr)
        return 1

    total_written = 0
    for biome, sample_slot in PARTIAL_BIOMES.items():
        sample_path = biome_tile(biome, sample_slot)
        if not sample_path.is_file():
            print(
                f"[{biome}] sample tile missing: {sample_path}",
                file=sys.stderr,
            )
            continue
        tint = sample_background_color(sample_path)
        print(
            f"[{biome}] sampled background from "
            f"{sample_path.name}: rgb{tint.as_tuple()}"
        )
        present = existing_slots(biome)
        targets = set(SLOT_NAME) - (set() if args.force else present)
        # Always skip the sample slot itself -- it IS the source.
        targets.discard(sample_slot)
        for slot in sorted(targets):
            fnd = foundation_tile(slot)
            if not fnd.is_file():
                print(f"  slot {slot:2d}: no foundation tile, skip")
                continue
            out_path = biome_tile(biome, slot)
            if args.dry_run:
                print(f"  slot {slot:2d}: would write {out_path.name}")
                continue
            composed = compose_biome_tile(fnd, biome, tint)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            composed.save(out_path)
            total_written += 1
            print(f"  slot {slot:2d}: wrote {out_path.name}")

    print(f"\nDone. {total_written} tile(s) written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
