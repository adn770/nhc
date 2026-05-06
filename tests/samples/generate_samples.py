#!/usr/bin/env python3
"""Generate sample SVG + PNG renders for visual evaluation.

The catalog lives in ``tests/samples/_samples/`` and is split into
two source families:

* ``generators/`` — wraps the production world / dungeon
  generators (BSP variety sweep, structural templates, underworld
  biomes, settlements, sites). Surfaces full-pipeline integration
  bugs.
* ``synthetic/`` — hand-built minimum-viable IR. The matrix covers
  each painting style on each room shape and (where relevant) in
  each consumer context (site / dungeon-room / building floor) so
  per-shape bleeding, cross-context portability, and group-opacity
  overlap surface one sample at a time.

Each sample writes four files under
``<outdir>/<category>/<name>_seed<S>.{svg,png,nir,json}``:

* ``.svg`` / ``.png`` — rendered output via
  ``nhc_render.ir_to_svg`` / ``nhc_render.ir_to_png``.
* ``.nir`` — the canonical FloorIR FlatBuffer.
* ``.json`` — parametric recipe (seed + ``params`` dict from the
  ``SampleSpec``) so the operator can re-derive what was rendered.

Default behaviour: render every sample at every default seed,
parallelised across CPU cores. Use ``--category`` /  ``--name``
glob filters to iterate fast.

Usage::

    python -m tests.samples.generate_samples
    python -m tests.samples.generate_samples --outdir /tmp/samples
    python -m tests.samples.generate_samples --category 'synthetic/decorators/*'
    python -m tests.samples.generate_samples --name 'on_octagon'
    python -m tests.samples.generate_samples --list
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Importing the source modules populates the CATALOG at module
# load. The order doesn't matter — each module appends its
# entries to the shared list.
from tests.samples._samples import generators  # noqa: F401
from tests.samples._samples import synthetic  # noqa: F401
from tests.samples._samples import _catalog  # noqa: F401
from tests.samples._samples._core import (
    CATALOG, SampleSpec, write_sample,
)


DEFAULT_SEEDS: tuple[int, ...] = (7, 42, 99)


def _parse_seeds(arg: str | None) -> tuple[int, ...]:
    if arg is None:
        return DEFAULT_SEEDS
    return tuple(int(s) for s in arg.split(",") if s.strip())


def _select(
    catalog: list[SampleSpec],
    *,
    category: str | None,
    name: str | None,
) -> list[SampleSpec]:
    """Filter the catalog by glob-style ``--category`` / ``--name``."""
    out = list(catalog)
    if category is not None:
        out = [s for s in out if fnmatch.fnmatch(s.category, category)]
    if name is not None:
        out = [s for s in out if fnmatch.fnmatch(s.name, name)]
    return out


def _render_one(
    spec_index: int, seed: int, outdir: Path, labels: bool,
) -> tuple[str, Path]:
    """Worker function. Process pool forks the catalog so we look
    up the spec by index to dodge pickling the build callable."""
    spec = CATALOG[spec_index]
    base = write_sample(spec, seed, outdir, inject_labels=labels)
    label = f"{spec.category}/{spec.name}_seed{seed}"
    return label, base


def _expand_jobs(
    specs: list[SampleSpec],
    cli_seeds: tuple[int, ...],
) -> list[tuple[int, int]]:
    """Expand each spec into (catalog_index, seed) jobs. Honours
    per-spec seed overrides (``spec.seeds``) when set."""
    jobs: list[tuple[int, int]] = []
    for idx, spec in enumerate(CATALOG):
        if spec not in specs:
            continue
        seeds = spec.seeds if spec.seeds is not None else cli_seeds
        for seed in seeds:
            jobs.append((idx, seed))
    return jobs


def _list(specs: list[SampleSpec], seeds: tuple[int, ...]) -> None:
    """Print the catalog (filtered) without rendering."""
    by_category: dict[str, list[SampleSpec]] = {}
    for spec in specs:
        by_category.setdefault(spec.category, []).append(spec)
    total = 0
    for cat in sorted(by_category):
        print(f"\n{cat}/")
        for spec in by_category[cat]:
            spec_seeds = spec.seeds or seeds
            count = len(spec_seeds)
            print(
                f"  {spec.name:<30} ({count} seed"
                f"{'s' if count != 1 else ''}: "
                f"{','.join(str(s) for s in spec_seeds)})"
            )
            print(f"    {spec.description}")
            total += count
    print(f"\n{len(specs)} sample{'s' if len(specs) != 1 else ''}, "
          f"{total} total render{'s' if total != 1 else ''}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir", type=Path, default=Path("debug/samples"),
        help="Output directory (default: debug/samples/).",
    )
    parser.add_argument(
        "--seeds", type=str, default=None,
        help=(
            "Comma-separated seed list (default: 7,42,99). "
            "Per-spec overrides still apply."
        ),
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help=(
            "Glob filter on category path (e.g. "
            "'synthetic/decorators/*' or 'generators/*')."
        ),
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Glob filter on sample name (e.g. 'on_octagon').",
    )
    parser.add_argument(
        "--workers", type=int, default=os.cpu_count() or 4,
        help=(
            "Worker processes (default: cpu_count). Set to 1 for "
            "serial execution / easier debugging."
        ),
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List matching samples without rendering.",
    )
    parser.add_argument(
        "--labels", action="store_true",
        help=(
            "Inject debug overlays into the SVG (room IDs, door "
            "markers, corridor IDs). PNG output stays clean. "
            "Off by default — raw renders are the canonical "
            "artifact."
        ),
    )
    args = parser.parse_args(argv)

    seeds = _parse_seeds(args.seeds)
    specs = _select(CATALOG, category=args.category, name=args.name)
    if not specs:
        print("(no samples matched filter)", file=sys.stderr)
        return 1

    if args.list:
        _list(specs, seeds)
        return 0

    args.outdir.mkdir(parents=True, exist_ok=True)
    jobs = _expand_jobs(specs, seeds)
    print(
        f"Rendering {len(jobs)} sample{'s' if len(jobs) != 1 else ''} "
        f"across {args.workers} worker"
        f"{'s' if args.workers != 1 else ''} → {args.outdir}/",
        flush=True,
    )

    t0 = time.monotonic()
    failures: list[tuple[str, str]] = []
    if args.workers <= 1:
        # Serial execution — easier to bisect when something
        # explodes during catalog development.
        for idx, seed in jobs:
            try:
                label, base = _render_one(
                    idx, seed, args.outdir, args.labels,
                )
                print(f"  ✓ {label}", flush=True)
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    (f"{CATALOG[idx].category}/"
                     f"{CATALOG[idx].name}_seed{seed}", str(exc)),
                )
                print(f"  ✗ {failures[-1][0]}: {exc}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    _render_one, idx, seed, args.outdir, args.labels,
                ): (idx, seed)
                for idx, seed in jobs
            }
            for fut in as_completed(futures):
                idx, seed = futures[fut]
                try:
                    label, _ = fut.result()
                    print(f"  ✓ {label}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    failures.append(
                        (f"{CATALOG[idx].category}/"
                         f"{CATALOG[idx].name}_seed{seed}", str(exc)),
                    )
                    print(
                        f"  ✗ {failures[-1][0]}: {exc}", flush=True,
                    )

    elapsed = time.monotonic() - t0
    n_ok = len(jobs) - len(failures)
    summary = (
        f"\n{n_ok}/{len(jobs)} rendered in {elapsed:.1f}s"
    )
    if failures:
        summary += f" ({len(failures)} failed)"
        print(summary, file=sys.stderr)
        for label, exc in failures:
            print(f"  ✗ {label}: {exc}", file=sys.stderr)
        return 1

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
