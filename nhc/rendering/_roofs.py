"""Shingle roof SVG fragments for site surfaces.

Each building on a Site gets a gable or pyramid roof clipped to
its footprint polygon. Rectangles with unequal sides and L-shapes
use gables (two sunlit/shadow halves along the longest axis with
a black ridge line); squares and octagons use pyramids (N
triangles from the polygon centre with N ridge spokes). Circles
skip entirely since circular footprints don't need orthogonal
roof geometry.

Public API:

    building_roof_fragments(site, seed) -> list[str]
        SVG fragments ready to concatenate before ``</svg>``.
        Includes one ``<defs>`` block with per-building clipPath
        definitions plus the clipped roof bodies.

Historically this code lived in ``tests/samples/generate_svg.py``.
It now sits in production so the game's site-surface SVG pipeline
(M5) can paint rooftops on the floor layer without importing dev
tooling.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nhc.dungeon.model import (
    CircleShape, LShape, OctagonShape, RectShape,
)
from nhc.rendering._svg_helpers import CELL, PADDING

if TYPE_CHECKING:
    from nhc.dungeon.building import Building
    from nhc.sites._site import Site


# Base roof tints. Each is the mid-sunlit shade; shadow side uses
# ~50% of the tint, sunlit uses ~100%, with a small ±12% jitter
# per shingle. Gradients are out — flat colours only.
ROOF_TINTS = [
    "#8A8A8A",  # cool gray
    "#8A7A5A",  # warm tan
    "#8A5A3A",  # terracotta
    "#5A5048",  # charcoal
    "#7A5A3A",  # ochre
]

ROOF_SHADOW_FACTOR = 0.5
ROOF_SHINGLE_WIDTH = 14.0
ROOF_SHINGLE_HEIGHT = 5.0
ROOF_SHINGLE_JITTER = 2.0
ROOF_RIDGE_STROKE = "#000000"
ROOF_RIDGE_WIDTH = 1.5
ROOF_SHINGLE_STROKE = "#000000"
ROOF_SHINGLE_STROKE_OPACITY = 0.2
ROOF_SHINGLE_STROKE_WIDTH = 0.3


def _scale_hex(hx: str, factor: float) -> str:
    r = min(255, max(0, int(int(hx[1:3], 16) * factor)))
    g = min(255, max(0, int(int(hx[3:5], 16) * factor)))
    b = min(255, max(0, int(int(hx[5:7], 16) * factor)))
    return f"#{r:02X}{g:02X}{b:02X}"


def _shade_palette(tint: str, sunlit: bool) -> list[str]:
    """Three flat shades of the tint. Sunlit brackets 100% of the
    tint; shadow sits near ROOF_SHADOW_FACTOR so the
    non-illuminated half reads ~half as bright."""
    if sunlit:
        factors = (1.15, 1.00, 0.88)
    else:
        centre = ROOF_SHADOW_FACTOR
        factors = (centre * 1.15, centre, centre * 0.88)
    return [_scale_hex(tint, f) for f in factors]


def _footprint_polygon_px(
    b: "Building",
) -> list[tuple[float, float]] | None:
    """Building footprint as a list of pixel-coord polygon
    vertices. Returns None for shapes without orthogonal polygon
    support (currently CircleShape — we skip its roof)."""
    shape = b.base_shape
    r = b.base_rect

    def _tp(tx: float, ty: float) -> tuple[float, float]:
        return (PADDING + tx * CELL, PADDING + ty * CELL)

    if isinstance(shape, RectShape):
        return [
            _tp(r.x, r.y), _tp(r.x2, r.y),
            _tp(r.x2, r.y2), _tp(r.x, r.y2),
        ]
    if isinstance(shape, LShape):
        notch = shape._notch_rect(r)
        x0, y0, x1, y1 = r.x, r.y, r.x2, r.y2
        nx0, ny0, nx1, ny1 = (
            notch.x, notch.y, notch.x2, notch.y2,
        )
        if shape.corner == "nw":
            return [
                _tp(nx1, y0), _tp(x1, y0),
                _tp(x1, y1), _tp(x0, y1),
                _tp(x0, ny1), _tp(nx1, ny1),
            ]
        if shape.corner == "ne":
            return [
                _tp(x0, y0), _tp(nx0, y0),
                _tp(nx0, ny1), _tp(x1, ny1),
                _tp(x1, y1), _tp(x0, y1),
            ]
        if shape.corner == "sw":
            return [
                _tp(x0, y0), _tp(x1, y0),
                _tp(x1, y1), _tp(nx1, y1),
                _tp(nx1, ny0), _tp(x0, ny0),
            ]
        # "se"
        return [
            _tp(x0, y0), _tp(x1, y0),
            _tp(x1, ny0), _tp(nx0, ny0),
            _tp(nx0, y1), _tp(x0, y1),
        ]
    if isinstance(shape, OctagonShape):
        clip = max(1, min(r.width, r.height) // 3)
        return [
            _tp(r.x + clip, r.y),
            _tp(r.x2 - clip, r.y),
            _tp(r.x2, r.y + clip),
            _tp(r.x2, r.y2 - clip),
            _tp(r.x2 - clip, r.y2),
            _tp(r.x + clip, r.y2),
            _tp(r.x, r.y2 - clip),
            _tp(r.x, r.y + clip),
        ]
    if isinstance(shape, CircleShape):
        return None
    return None


def _roof_mode(b: "Building") -> str:
    """Pick ``"gable"`` (2-side) or ``"pyramid"`` (N-triangle)
    roof style. ``"skip"`` for circular buildings."""
    shape = b.base_shape
    r = b.base_rect
    if isinstance(shape, CircleShape):
        return "skip"
    if isinstance(shape, OctagonShape):
        return "pyramid"
    if isinstance(shape, RectShape):
        return "pyramid" if r.width == r.height else "gable"
    if isinstance(shape, LShape):
        return "gable"
    return "skip"


def _shingle_rect(
    x: float, y: float, w: float, h: float, fill: str,
) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'fill="{fill}" '
        f'stroke="{ROOF_SHINGLE_STROKE}" '
        f'stroke-opacity="{ROOF_SHINGLE_STROKE_OPACITY}" '
        f'stroke-width="{ROOF_SHINGLE_STROKE_WIDTH}"/>'
    )


def _shingle_region(
    x: float, y: float, w: float, h: float,
    shades: list[str], rng: random.Random,
) -> list[str]:
    """Running-bond rows of shingle rects filling a bounding box."""
    sw = ROOF_SHINGLE_WIDTH
    sh = ROOF_SHINGLE_HEIGHT
    jitter = ROOF_SHINGLE_JITTER
    frags: list[str] = []
    row = 0
    cy = y
    while cy < y + h:
        sx = x - (sw / 2 if row % 2 else 0)
        while sx < x + w:
            sw_j = sw + rng.uniform(-jitter, jitter)
            shade = rng.choice(shades)
            frags.append(_shingle_rect(sx, cy, sw_j, sh, shade))
            sx += sw_j
        cy += sh
        row += 1
    return frags


def _gable_sides(
    px: float, py: float, pw: float, ph: float,
    horizontal: bool,
    sunlit_shades: list[str], shadow_shades: list[str],
    rng: random.Random,
) -> list[str]:
    """Shingle-filled halves plus the central ridge line."""
    frags: list[str] = []
    if horizontal:
        frags.extend(_shingle_region(
            px, py, pw, ph / 2, shadow_shades, rng,
        ))
        frags.extend(_shingle_region(
            px, py + ph / 2, pw, ph / 2, sunlit_shades, rng,
        ))
        frags.append(
            f'<line x1="{px:.1f}" y1="{py + ph / 2:.1f}" '
            f'x2="{px + pw:.1f}" y2="{py + ph / 2:.1f}" '
            f'stroke="{ROOF_RIDGE_STROKE}" '
            f'stroke-width="{ROOF_RIDGE_WIDTH}"/>'
        )
    else:
        frags.extend(_shingle_region(
            px, py, pw / 2, ph, shadow_shades, rng,
        ))
        frags.extend(_shingle_region(
            px + pw / 2, py, pw / 2, ph, sunlit_shades, rng,
        ))
        frags.append(
            f'<line x1="{px + pw / 2:.1f}" y1="{py:.1f}" '
            f'x2="{px + pw / 2:.1f}" y2="{py + ph:.1f}" '
            f'stroke="{ROOF_RIDGE_STROKE}" '
            f'stroke-width="{ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def _pyramid_sides(
    polygon: list[tuple[float, float]],
    sunlit_shades: list[str], shadow_shades: list[str],
    rng: random.Random,
) -> list[str]:
    """N triangles from polygon centre, shaded by edge midpoint
    direction (north/west = shadow, south/east = sunlit), plus
    ridges from centre to each polygon vertex."""
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    frags: list[str] = []
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        mx = (a[0] + b[0]) / 2
        my = (a[1] + b[1]) / 2
        is_shadow = my < cy - 1e-3 or (
            mx < cx - 1e-3 and my < cy + 1e-3
        )
        shades = shadow_shades if is_shadow else sunlit_shades
        fill = rng.choice(shades)
        pts = (
            f"{a[0]:.1f},{a[1]:.1f} "
            f"{b[0]:.1f},{b[1]:.1f} "
            f"{cx:.1f},{cy:.1f}"
        )
        frags.append(
            f'<polygon points="{pts}" fill="{fill}" '
            f'stroke="{ROOF_SHINGLE_STROKE}" '
            f'stroke-opacity="{ROOF_SHINGLE_STROKE_OPACITY}" '
            f'stroke-width="{ROOF_SHINGLE_STROKE_WIDTH}"/>'
        )
    for (vx, vy) in polygon:
        frags.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
            f'x2="{vx:.1f}" y2="{vy:.1f}" '
            f'stroke="{ROOF_RIDGE_STROKE}" '
            f'stroke-width="{ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def building_roof_fragments(
    site: "Site", seed: int = 0,
) -> list[str]:
    """One-roof-per-building SVG fragments plus a shared ``<defs>``
    block. Each roof clips to the building's footprint polygon so
    L-shape notches and octagon corners stay clean.
    """
    defs: list[str] = []
    body: list[str] = []
    for i, b in enumerate(site.buildings):
        polygon = _footprint_polygon_px(b)
        if polygon is None:
            continue
        mode = _roof_mode(b)
        if mode == "skip":
            continue

        rng = random.Random(seed + 0xCAFE + i)
        tint = rng.choice(ROOF_TINTS)
        sunlit_shades = _shade_palette(tint, sunlit=True)
        shadow_shades = _shade_palette(tint, sunlit=False)

        clip_id = f"roof_fp_{i}"
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in polygon)
        defs.append(
            f'<clipPath id="{clip_id}">'
            f'<polygon points="{pts}"/>'
            f'</clipPath>'
        )

        r = b.base_rect
        px = PADDING + r.x * CELL
        py = PADDING + r.y * CELL
        pw = r.width * CELL
        ph = r.height * CELL

        body.append(f'<g clip-path="url(#{clip_id})">')
        if mode == "gable":
            body.extend(
                _gable_sides(
                    px, py, pw, ph, r.width >= r.height,
                    sunlit_shades, shadow_shades, rng,
                )
            )
        else:
            body.extend(
                _pyramid_sides(
                    polygon, sunlit_shades, shadow_shades, rng,
                )
            )
        body.append('</g>')

    if not body:
        return []
    return [f'<defs>{"".join(defs)}</defs>'] + body
