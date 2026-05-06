"""Catalog SVG label injector.

The catalog page IR carries no label ops — the painter trait
emits clean material renders. Labels are a presentation concern
specific to the catalog SVG view: column headers above each cell
column, row labels (rotated 90°) to the left of each cell row.

PNG output bypasses this module — ``nhc_render.ir_to_png(buf)``
goes straight to disk so PNG stays a clean rasteriser artifact.
"""

from __future__ import annotations

from nhc.rendering._svg_helpers import PADDING

from ._builder import (
    CELL_PX, GUTTER_PX, LEFT_MARGIN_PX, TOP_MARGIN_PX,
    CatalogPageSpec, cell_bbox,
)


# Label typography. Sized to fit the 24/32 px margin areas.
COLUMN_LABEL_FONT_PX = 11
ROW_LABEL_FONT_PX = 11
LABEL_INK = "#222222"
LABEL_FONT_FAMILY = "sans-serif"


def _column_label_anchor(col_idx: int) -> tuple[int, int]:
    """Centre point above column ``col_idx`` in raw IR-pixel coords.

    Sits just above the cell's top edge in the TOP_MARGIN strip.
    """
    x0, y0, x1, _ = cell_bbox(col_idx, 0)
    cx = (x0 + x1) // 2
    cy = y0 - 8  # 8 px above the cell top
    return cx, cy


def _row_label_anchor(row_idx: int) -> tuple[int, int]:
    """Centre point to the left of row ``row_idx`` in raw IR-pixel
    coords. The label is rotated -90° (reads bottom-to-top).
    """
    x0, y0, _, y1 = cell_bbox(0, row_idx)
    cx = x0 - 8  # 8 px left of the cell left edge
    cy = (y0 + y1) // 2
    return cx, cy


def _build_label_block(spec: CatalogPageSpec) -> str:
    """Build the SVG ``<g>`` block carrying every column + row label.

    Coordinates are in IR-pixel space. The painter wraps every
    rendered op inside ``<g transform="translate(PADDING,PADDING)
    scale(1)">`` so injecting raw IR-pixel coords means the labels
    composite into the same coordinate frame as the cells.
    """
    parts: list[str] = []
    parts.append(
        f'<g class="catalog-labels" '
        f'fill="{LABEL_INK}" '
        f'font-family="{LABEL_FONT_FAMILY}" '
        f'text-anchor="middle">'
    )
    for col_idx, column in enumerate(spec.columns):
        cx, cy = _column_label_anchor(col_idx)
        parts.append(
            f'<text x="{cx}" y="{cy}" '
            f'font-size="{COLUMN_LABEL_FONT_PX}">'
            f'{_escape(column.label)}</text>'
        )
    for row_idx, row_label in enumerate(spec.rows):
        cx, cy = _row_label_anchor(row_idx)
        parts.append(
            f'<text x="{cx}" y="{cy}" '
            f'font-size="{ROW_LABEL_FONT_PX}" '
            f'transform="rotate(-90 {cx} {cy})">'
            f'{_escape(row_label)}</text>'
        )
    parts.append("</g>")
    return "".join(parts)


def _escape(text: str) -> str:
    """Minimal SVG-text escaping for & < > characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def inject_catalog_labels(svg: str, spec: CatalogPageSpec) -> str:
    """Inject row + column labels into the SVG body.

    The renderer wraps the painted body in
    ``<g transform="translate(PADDING,PADDING) ...">`` near the
    end of the file. We append the label block just before the
    final ``</svg>`` close — the inner transform applies to it
    too via SVG's last-wins-z-order, layering labels above the
    cells.

    A future revision could parse the SVG with ``xml.etree`` for
    safety, but the painter's output shape is stable enough that a
    string replace at the closing tag is cheaper and adequate.
    """
    label_block = _build_label_block(spec)
    close = "</svg>"
    if close not in svg:
        # Painter output didn't terminate as expected — fall back
        # to appending so the diff is visible rather than silent.
        return svg + label_block
    return svg.replace(close, label_block + close, 1)


__all__ = [
    "inject_catalog_labels",
    "COLUMN_LABEL_FONT_PX", "ROW_LABEL_FONT_PX",
    "LABEL_INK", "LABEL_FONT_FAMILY",
]
