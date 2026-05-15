"""Ad-hoc site inspector for macro-surface scatter verification.

Replaces the throwaway ``python -c`` snippets used while tuning
site assemblers (tree / bush densities, surface padding). Builds a
site from a deterministic ``Random(seed)`` and reports surface
dimensions, footprint size, floor count, and per-feature scatter
counts -- the numbers you actually want when eyeballing whether a
biome override moved the needle.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/site_inspect.py tower
    PYTHONPATH=. .venv/bin/python scripts/site_inspect.py tower \
        --biome forest --seeds 5
    PYTHONPATH=. .venv/bin/python scripts/site_inspect.py cottage \
        --seeds 10

``--seeds N`` inspects seeds ``0 .. N-1``. ``--biome`` takes a
:class:`~nhc.hexcrawl.model.Biome` value (e.g. ``forest``,
``mountain``); omit it for the no-biome default. Run with no
arguments to print this help.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass

from nhc.hexcrawl.model import Biome
from nhc.sites.cottage import assemble_cottage
from nhc.sites.farm import assemble_farm
from nhc.sites.tower import assemble_tower

import random

# Site kind -> assembler sharing the
# ``(site_id, rng, biome=None)`` signature. Only macro-surface
# sites with vegetation scatter are listed; extend as needed.
_ASSEMBLERS = {
    "tower": assemble_tower,
    "cottage": assemble_cottage,
    "farm": assemble_farm,
}


@dataclass(frozen=True)
class SiteReport:
    """One inspected site instance."""

    kind: str
    seed: int
    biome: str  # "default" or the Biome value
    surface_w: int
    surface_h: int
    footprint_tiles: int
    floors: int
    features: dict[str, int]  # surface feature name -> tile count


def _resolve_biome(biome: str | None) -> Biome | None:
    if biome is None:
        return None
    try:
        return Biome(biome)
    except ValueError:
        raise ValueError(
            f"unknown biome {biome!r}; expected one of "
            f"{[b.value for b in Biome]}",
        ) from None


def inspect_site(
    kind: str, seed: int, biome: str | None = None,
) -> SiteReport:
    """Assemble ``kind`` from ``Random(seed)`` and report on it."""
    assembler = _ASSEMBLERS.get(kind)
    if assembler is None:
        raise ValueError(
            f"unknown site kind {kind!r}; expected one of "
            f"{sorted(_ASSEMBLERS)}",
        )
    resolved = _resolve_biome(biome)
    site = assembler(
        f"inspect_{kind}", random.Random(seed), biome=resolved,
    )

    footprint = 0
    floors = 0
    for b in site.buildings:
        footprint += len(b.base_shape.floor_tiles(b.base_rect))
        floors += len(b.floors)

    features: Counter[str] = Counter()
    surface = site.surface
    for row in surface.tiles:
        for tile in row:
            if tile.feature is not None:
                features[tile.feature] += 1
    # Stable keys so report diffs stay readable across seeds.
    features.setdefault("tree", 0)
    features.setdefault("bush", 0)

    return SiteReport(
        kind=kind,
        seed=seed,
        biome=biome if biome is not None else "default",
        surface_w=surface.width,
        surface_h=surface.height,
        footprint_tiles=footprint,
        floors=floors,
        features=dict(features),
    )


def aggregate(
    kind: str, biome: str | None = None, seeds=range(5),
) -> list[SiteReport]:
    """Inspect ``kind`` across ``seeds`` (default 0..4)."""
    return [inspect_site(kind, s, biome) for s in seeds]


def format_reports(reports: list[SiteReport]) -> str:
    """Render reports as an aligned table plus a totals line."""
    if not reports:
        return "(no reports)\n"
    feat_keys = sorted(
        {k for r in reports for k in r.features},
    )
    header = (
        f"{'kind':<10} {'seed':>4} {'biome':<10} "
        f"{'surf':>7} {'foot':>5} {'flr':>3} "
        + " ".join(f"{k:>6}" for k in feat_keys)
    )
    lines = [header, "-" * len(header)]
    totals: Counter[str] = Counter()
    for r in reports:
        totals.update(r.features)
        lines.append(
            f"{r.kind:<10} {r.seed:>4} {r.biome:<10} "
            f"{r.surface_w:>3}x{r.surface_h:<3} "
            f"{r.footprint_tiles:>5} {r.floors:>3} "
            + " ".join(
                f"{r.features.get(k, 0):>6}" for k in feat_keys
            )
        )
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<10} {'':>4} {'':<10} {'':>7} {'':>5} {'':>3} "
        + " ".join(f"{totals.get(k, 0):>6}" for k in feat_keys)
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    parser = argparse.ArgumentParser(
        prog="site_inspect",
        description="Inspect a site's macro-surface scatter.",
    )
    parser.add_argument(
        "kind", choices=sorted(_ASSEMBLERS),
        help="site kind to assemble",
    )
    parser.add_argument(
        "--biome", default=None,
        help="Biome value (e.g. forest); default = no biome",
    )
    parser.add_argument(
        "--seeds", type=int, default=5,
        help="inspect seeds 0 .. N-1 (default 5)",
    )
    args = parser.parse_args(argv)

    try:
        reports = aggregate(
            args.kind, biome=args.biome, seeds=range(args.seeds),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_reports(reports), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
