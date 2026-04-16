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
import random
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

# Biomes generated entirely from foundation tiles. Each entry
# carries the flat RGB background colour the generated hex is
# filled with before the foundation feature is stamped on top.
#
# The colours below were originally sampled from the now-retired
# pointy-top forest_XX / mountain_XX tiles; keeping them so the
# generated palette remains visually consistent across versions.
# Tweak here if you want a different biome tone.
# (BIOME_COLOURS is populated below, after the RGB dataclass.)

"""Foundation tiles are overlays: only the feature silhouette is
opaque, the rest is fully transparent. The right composition is
a biome-coloured hex *beneath* the foundation, so the feature
"stamps" onto a solid biome background. The hex silhouette is
drawn from a fully paletted biome tile (greenlands) which shares
the foundation's 238x207 flat-top dimensions -- the native
forest/mountain tiles happen to ship at a different aspect
(222x255, pointy-top oriented) so they cannot serve as the
silhouette source."""

# Biome + slot to read the hex silhouette from. greenlands slot 2
# is a full 238x207 flat-top hex, pixel-compatible with the
# foundation tiles.
HEX_SILHOUETTE_BIOME = "greenlands"
HEX_SILHOUETTE_SLOT = 2


@dataclass
class RGB:
    r: int
    g: int
    b: int

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)


BIOME_COLOURS = {
    "forest":   RGB(60, 100, 50),     # deep forest canopy
    "mountain": RGB(125, 110, 100),   # warm stone grey
    # Added alongside the Biome enum expansion (M-G.1). Colours
    # calibrated against the five full-palette biomes so the
    # generated tiles sit in the same saturation band:
    #   hills  -- olive-sage, between greenlands and drylands,
    #             pulled toward green.
    #   marsh  -- murky wet-grass, darker than greenlands but
    #             distinctly green vs. the olive deadlands
    #             (80, 80, 64).
    #   swamp  -- shadowed wetland, darker than forest with a
    #             touch less saturation so the two read as
    #             related but distinct on the map.
    "hills":    RGB(150, 160, 95),
    "marsh":    RGB(95, 125, 85),
    "swamp":    RGB(55, 72, 50),
}

# Background dither: per-pixel random offset (signed, uniform)
# added to each RGB channel of the flat biome colour. 0 turns
# the effect off (pure flat fill). 12 is a subtle terrain grain
# that keeps the hex feeling solid while avoiding the "plastic"
# look of a truly flat colour. The seed is mixed per (biome,
# slot) so neighbouring tiles don't share the identical noise
# pattern.
NOISE_AMPLITUDE = 12


def biome_tile(biome: str, slot: int) -> Path:
    stem = SLOT_NAME[slot]
    return HEXTILES / biome / f"{slot}-{biome}_{stem}.png"


def foundation_tile(slot: int) -> Path:
    stem = SLOT_NAME[slot]
    return HEXTILES / f"{slot}-foundation_{stem}.png"


_SILHOUETTE_CACHE: Image.Image | None = None


def _hex_silhouette_mask() -> Image.Image:
    """Return an "L" mode image whose non-zero pixels are inside
    the hex shape, 238x207 to match the foundation tiles."""
    global _SILHOUETTE_CACHE
    if _SILHOUETTE_CACHE is not None:
        return _SILHOUETTE_CACHE
    src = biome_tile(HEX_SILHOUETTE_BIOME, HEX_SILHOUETTE_SLOT)
    img = Image.open(src).convert("RGBA")
    _r, _g, _b, alpha = img.split()
    _SILHOUETTE_CACHE = alpha
    return alpha


def _dithered_fill(
    size: tuple[int, int],
    colour: RGB,
    amplitude: int,
    seed: int,
) -> Image.Image:
    """Return an RGBA image filled with ``colour`` plus uniform
    per-channel random noise in [-amplitude, +amplitude]. Alpha
    is fully opaque; the hex silhouette is applied later by the
    caller via a paste mask."""
    w, h = size
    if amplitude <= 0:
        return Image.new("RGBA", (w, h), (*colour.as_tuple(), 255))
    rng = random.Random(seed)
    out = Image.new("RGBA", (w, h))
    px = out.load()
    r, g, b = colour.as_tuple()
    lo, hi = -amplitude, amplitude
    for y in range(h):
        for x in range(w):
            nr = max(0, min(255, r + rng.randint(lo, hi)))
            ng = max(0, min(255, g + rng.randint(lo, hi)))
            nb = max(0, min(255, b + rng.randint(lo, hi)))
            px[x, y] = (nr, ng, nb, 255)
    return out


def compose_biome_tile(
    foundation_path: Path,
    biome: str,
    colour: RGB,
    *,
    slot: int,
    noise: int = NOISE_AMPLITUDE,
) -> Image.Image:
    """Build a biome-specific tile by stamping a foundation feature
    over a biome-coloured hex.

    Step 1: fill a canvas with the biome's background colour
    (with optional per-pixel noise dither), masked by the
    greenlands silhouette (same 238x207 flat-top shape all
    foundation tiles use).
    Step 2: alpha-composite the foundation feature on top; its
    partial-alpha "detail" pixels (village, tundra stipple, cave
    mouth, etc.) land on the dithered biome background.

    The dither seed is mixed from (biome, slot) so each tile has
    its own noise pattern while staying deterministic between
    runs.
    """
    foundation = Image.open(foundation_path).convert("RGBA")
    silhouette = _hex_silhouette_mask()
    if silhouette.size != foundation.size:
        silhouette = silhouette.resize(foundation.size)
    w, h = foundation.size
    # Seed: stable hash of (biome, slot) in the uint32 range.
    seed = (hash((biome, slot)) & 0xFFFFFFFF)
    fill = _dithered_fill((w, h), colour, noise, seed)
    bg = Image.new("RGBA", (w, h), (*colour.as_tuple(), 0))
    bg.paste(fill, (0, 0), silhouette)
    return Image.alpha_composite(bg, foundation)


def existing_slots(biome: str) -> set[int]:
    """Slots already present under hextiles/<biome>/."""
    biome_dir = HEXTILES / biome
    if not biome_dir.is_dir():
        return set()
    present: set[int] = set()
    for p in biome_dir.iterdir():
        name = p.name
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
        description=(
            "Generate the full 27-slot forest / mountain palettes "
            "from foundation tiles."
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite biome tiles even when they already exist.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List actions without touching disk.",
    )
    parser.add_argument(
        "--noise", type=int, default=NOISE_AMPLITUDE,
        help=(
            "Dither amplitude applied to the biome background "
            f"(default {NOISE_AMPLITUDE}; 0 = flat fill)."
        ),
    )
    args = parser.parse_args()

    if not HEXTILES.is_dir():
        print(f"hextiles/ not found at {HEXTILES}", file=sys.stderr)
        return 1

    # Sanity-check the silhouette source early so we fail fast
    # with a clear message instead of a PIL stack trace.
    src = biome_tile(HEX_SILHOUETTE_BIOME, HEX_SILHOUETTE_SLOT)
    if not src.is_file():
        print(
            f"silhouette source missing: {src}\n"
            f"(the greenlands palette is required; it provides "
            f"the 238x207 flat-top hex shape)",
            file=sys.stderr,
        )
        return 1

    total_written = 0
    for biome, tint in BIOME_COLOURS.items():
        print(f"[{biome}] background rgb{tint.as_tuple()}")
        present = existing_slots(biome)
        targets = set(SLOT_NAME) - (set() if args.force else present)
        for slot in sorted(targets):
            fnd = foundation_tile(slot)
            if not fnd.is_file():
                print(f"  slot {slot:2d}: no foundation tile, skip")
                continue
            out_path = biome_tile(biome, slot)
            if args.dry_run:
                print(f"  slot {slot:2d}: would write {out_path.name}")
                continue
            composed = compose_biome_tile(
                fnd, biome, tint, slot=slot, noise=args.noise,
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            composed.save(out_path)
            total_written += 1
            print(f"  slot {slot:2d}: wrote {out_path.name}")

    print(f"\nDone. {total_written} tile(s) written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
