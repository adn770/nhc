"""Catalog-page samples — composite renders for visual evaluation.

Each catalog page is one ``FloorIR`` carrying a grid of regions
(rect / octagon / circle cells) with one paint / stroke / fixture
op per cell. Renders as a single PNG via ``nhc_render.ir_to_png``
(no labels; raw painter output) and a single SVG via
``nhc_render.ir_to_svg`` post-processed to inject row / column
``<text>`` labels.

Pages live under ``debug/samples/synthetic/<topic>/<page>.{svg,png,
nir,json}``. Topics enumerated in ``plans/samples_catalog_plan.md``
(or the chat thread that produced this scaffold) — each topic gets
one or more page files; the page-builder pattern is uniform.

Importing this module registers all catalog pages with the shared
``CATALOG`` from ``_samples._core``.
"""

from __future__ import annotations

# Importing each page module appends entries to CATALOG. Order is
# irrelevant; the CLI iterates the catalog and filters via
# --category / --name.
from . import floors_cave  # noqa: F401
from . import floors_earth  # noqa: F401
from . import floors_liquid  # noqa: F401
from . import floors_plain  # noqa: F401
from . import floors_special  # noqa: F401
from . import floors_stone  # noqa: F401
from . import floors_wood  # noqa: F401
from . import walls  # noqa: F401
