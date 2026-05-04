"""Core types for the sample catalog.

The :class:`SampleSpec` dataclass is the unit the catalog ships
and the CLI iterates over. The render path is purely:

    result = spec.build(seed)
    svg = nhc_render.ir_to_svg(result.buf)
    png = nhc_render.ir_to_png(result.buf, 1.0, None)

Both rasterisers consume the same FlatBuffer, so the SVG / PNG
pair surfaces backend-specific drift visually. The ``.nir``
sidecar is the canonical artifact (the IR buffer); the ``.json``
sidecar is the parametric recipe (seed + ``params`` dict from
the spec) so the operator can re-derive what was rendered.

``BuildResult.level`` carries the source :class:`Level` when
available so the optional ``--labels`` overlay can extract room
/ corridor / door metadata. Synthetic samples that hand-build
the IR without a level pass ``level=None``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Union

import nhc_render


@dataclass(frozen=True)
class BuildResult:
    """The result of a sample's ``build(seed)`` call.

    Attributes:
        buf: The FloorIR FlatBuffer — fed to ``nhc_render.ir_to_svg``
            / ``ir_to_png`` for the canonical render.
        level: Source :class:`Level` (or ``None`` for synthetic
            specs that don't have one). When present, the
            ``--labels`` overlay extracts rooms / doors /
            corridors from this object.
        site: Optional :class:`Site` reference for samples that
            wrap a site-level surface (settlements / sites/macro).
            Used by label extraction to reach buildings.
    """

    buf: bytes
    level: Any | None = None
    site: Any | None = None


# Builders may return either raw bytes (no labels) or a
# :class:`BuildResult` (labels available). The renderer normalises
# via :func:`_coerce_result`.
BuildOutput = Union[bytes, BuildResult]


def _coerce_result(value: BuildOutput) -> BuildResult:
    if isinstance(value, BuildResult):
        return value
    return BuildResult(buf=value)


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
        build: ``(seed: int) -> bytes | BuildResult`` callable
            returning the FloorIR FlatBuffer. Wrap the buffer in a
            :class:`BuildResult` when the source ``level`` /
            ``site`` is needed for label extraction; raw bytes
            disable labels for the spec.
        seeds: Per-spec seed override. ``None`` = use the CLI's
            seed list (default ``(7, 42, 99)``). Synthetic samples
            with deterministic geometry typically pin to one seed.
    """

    name: str
    category: str
    description: str
    params: dict[str, Any]
    build: Callable[[int], BuildOutput]
    seeds: tuple[int, ...] | None = None


# The catalog list is populated by the per-source modules.
CATALOG: list[SampleSpec] = []


def render_sample(
    spec: SampleSpec, seed: int,
) -> tuple[BuildResult, str, bytes]:
    """Build the IR for ``spec`` at ``seed`` and rasterise both ways.

    Returns ``(result, svg_text, png_bytes)`` where ``result``
    carries the buffer + optional source level for label extraction.
    Pure function — caller decides where the artifacts land via
    :func:`write_sample`.
    """
    result = _coerce_result(spec.build(seed))
    svg = nhc_render.ir_to_svg(result.buf)
    png = bytes(nhc_render.ir_to_png(result.buf, 1.0, None))
    return result, svg, png


def write_sample(
    spec: SampleSpec,
    seed: int,
    outdir: Path,
    *,
    result: BuildResult | None = None,
    svg: str | None = None,
    png: bytes | None = None,
    inject_labels: bool = False,
) -> Path:
    """Render ``spec`` (or use pre-rendered artifacts) and write
    the four sidecars under ``outdir/<spec.category>/``.

    Returns the base path (no extension) so callers can log the
    rendered location.

    The ``result`` / ``svg`` / ``png`` parameters let callers reuse
    artifacts produced elsewhere (e.g. a parallel worker that
    rendered upstream of the writer). When all three are
    ``None``, the function calls :func:`render_sample`.

    ``inject_labels`` enables the optional debug-overlay pass that
    augments the SVG with room / corridor / door labels. PNG
    output is always raw (no labels).
    """
    if result is None or svg is None or png is None:
        result, svg, png = render_sample(spec, seed)
    if inject_labels and result.level is not None:
        from ._labels import inject_labels as _inject
        svg = _inject(svg, result.level, site=result.site)
    base = outdir / spec.category / f"{spec.name}_seed{seed}"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".svg").write_text(svg)
    base.with_suffix(".png").write_bytes(png)
    base.with_suffix(".nir").write_bytes(result.buf)
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


__all__ = [
    "BuildResult", "CATALOG", "SampleSpec",
    "render_sample", "write_sample",
]
