"""Core types for the sample catalog.

The :class:`SampleSpec` dataclass is the unit the catalog ships
and the CLI iterates over. The render path is purely:

    buf = spec.build(seed)
    svg = nhc_render.ir_to_svg(buf)
    png = nhc_render.ir_to_png(buf, 1.0, None)

Both rasterisers consume the same FlatBuffer, so the SVG / PNG
pair surfaces backend-specific drift visually. The ``.nir``
sidecar is the canonical artifact (the IR buffer); the ``.json``
sidecar is the parametric recipe (seed + ``params`` dict from
the spec) so the operator can re-derive what was rendered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import nhc_render


@dataclass(frozen=True)
class SampleSpec:
    """One sample in the catalog.

    Attributes:
        name: Filename stem (e.g. ``"cobblestone_octagon"``). No
            extension; the renderer appends ``.svg`` / ``.png`` /
            ``.nir`` / ``.json``.
        category: Nested category path (e.g.
            ``"decorators/cobblestone"``). Maps to the directory
            tree under the output root.
        description: One-line human-readable summary of what the
            sample exercises. Surfaces in the JSON recipe so a
            reviewer can grep for "what does this sample test?".
        params: Static parametric description (style, shape,
            context, theme, decorator name, etc.). Echoed into
            the JSON recipe alongside the seed.
        build: ``(seed: int) -> bytes`` callable returning a
            FloorIR FlatBuffer. The renderer calls this with each
            requested seed.
        seeds: Per-spec seed override. ``None`` = use the CLI's
            seed list (default ``(7, 42, 99)``). Synthetic samples
            with deterministic geometry typically pin to one seed.
    """

    name: str
    category: str
    description: str
    params: dict[str, Any]
    build: Callable[[int], bytes]
    seeds: tuple[int, ...] | None = None


# The catalog list is populated by the per-source modules.
CATALOG: list[SampleSpec] = []


def render_sample(spec: SampleSpec, seed: int) -> tuple[bytes, str, bytes]:
    """Build the IR for ``spec`` at ``seed`` and rasterise both ways.

    Returns ``(buf, svg_text, png_bytes)``. Pure function — caller
    decides where the artifacts land via :func:`write_sample`.
    """
    buf = spec.build(seed)
    svg = nhc_render.ir_to_svg(buf)
    png = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    return buf, svg, png


def write_sample(
    spec: SampleSpec,
    seed: int,
    outdir: Path,
    *,
    buf: bytes | None = None,
    svg: str | None = None,
    png: bytes | None = None,
) -> Path:
    """Render ``spec`` (or use pre-rendered artifacts) and write
    the four sidecars under ``outdir/<spec.category>/``.

    Returns the base path (no extension) so callers can log the
    rendered location.

    The ``buf`` / ``svg`` / ``png`` parameters let callers reuse
    artifacts produced elsewhere (e.g. a parallel worker that
    rendered upstream of the writer). When all three are
    ``None``, the function calls :func:`render_sample`.
    """
    if buf is None or svg is None or png is None:
        buf, svg, png = render_sample(spec, seed)
    base = outdir / spec.category / f"{spec.name}_seed{seed}"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".svg").write_text(svg)
    base.with_suffix(".png").write_bytes(png)
    base.with_suffix(".nir").write_bytes(buf)
    recipe = {
        "name": spec.name,
        "category": spec.category,
        "description": spec.description,
        "seed": seed,
        "params": spec.params,
    }
    base.with_suffix(".json").write_text(
        json.dumps(recipe, indent=2, sort_keys=True) + "\n",
    )
    return base


__all__ = ["CATALOG", "SampleSpec", "render_sample", "write_sample"]
