"""Sample catalog for visual evaluation of the SVG/PNG renderer.

The catalog drives ``tests/samples/generate_samples.py``. Every
entry is a :class:`SampleSpec` whose ``build(seed)`` callable
returns a FloorIR FlatBuffer; the renderer side calls
``nhc_render.ir_to_svg`` and ``nhc_render.ir_to_png`` against
that buffer and writes the four sidecars (``.svg`` / ``.png`` /
``.nir`` / ``.json``) into ``debug/samples/<category>/<name>``.

Two source families:

* ``generators`` — wraps the production world / dungeon
  generators (BSP variety sweep, structural templates, underworld
  biomes, settlements, sites). Use these to surface integration
  bugs across the full pipeline.
* ``_catalog`` — composite catalog pages. Each page is one
  ``FloorIR`` carrying a grid of cell regions (one column = one
  material / treatment / decorator, one row = one shape) with
  one paint / stroke / fixture op per cell. Reduces the per-room
  per-style sample explosion to ~30 reviewable pages.
"""

from __future__ import annotations

from ._core import CATALOG, SampleSpec, render_sample, write_sample

__all__ = ["CATALOG", "SampleSpec", "render_sample", "write_sample"]
