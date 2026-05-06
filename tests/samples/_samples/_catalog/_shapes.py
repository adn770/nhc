"""Cell-shape outline builders for catalog pages.

Each builder returns an ``OutlineT`` in pixel-space coords, sized
to fit inside the cell's bounding box ``(x0, y0, x1, y1)``. The
catalog page-builder dispatches one outline per cell so the same
material can be visually compared across rect / octagon / circle
shapes — surfacing per-shape bleed bugs.
"""

from __future__ import annotations

import math

from nhc.rendering.ir._fb.Outline import OutlineT
from nhc.rendering.ir._fb.OutlineKind import OutlineKind
from nhc.rendering.ir._fb.Vec2 import Vec2T


def _v2(x: float, y: float) -> Vec2T:
    v = Vec2T()
    v.x = float(x)
    v.y = float(y)
    return v


def rect_outline(x0: float, y0: float, x1: float, y1: float) -> OutlineT:
    """Axis-aligned rectangle outline through the bbox corners."""
    o = OutlineT()
    o.vertices = [
        _v2(x0, y0),
        _v2(x1, y0),
        _v2(x1, y1),
        _v2(x0, y1),
    ]
    o.closed = True
    o.descriptorKind = OutlineKind.Polygon
    o.rings = []
    return o


def octagon_outline(
    x0: float, y0: float, x1: float, y1: float,
    *, chamfer_frac: float = 0.30,
) -> OutlineT:
    """Octagon inscribed in the bbox with corner chamfers."""
    w = x1 - x0
    h = y1 - y0
    cx = min(w, h) * chamfer_frac
    cy = min(w, h) * chamfer_frac
    o = OutlineT()
    o.vertices = [
        _v2(x0 + cx, y0),
        _v2(x1 - cx, y0),
        _v2(x1, y0 + cy),
        _v2(x1, y1 - cy),
        _v2(x1 - cx, y1),
        _v2(x0 + cx, y1),
        _v2(x0, y1 - cy),
        _v2(x0, y0 + cy),
    ]
    o.closed = True
    o.descriptorKind = OutlineKind.Polygon
    o.rings = []
    return o


def circle_outline(
    x0: float, y0: float, x1: float, y1: float,
    *, segments: int = 32,
) -> OutlineT:
    """Polygonised ellipse inscribed in the bbox.

    Painters that consume ``OutlineKind.Polygon`` walk the vertex
    list directly — no native circle primitive needed. 32 segments
    keeps the silhouette smooth at the catalog cell scale (≈ 128 px).
    """
    cx_pix = (x0 + x1) * 0.5
    cy_pix = (y0 + y1) * 0.5
    rx = (x1 - x0) * 0.5
    ry = (y1 - y0) * 0.5
    verts = []
    for i in range(segments):
        theta = i * 2.0 * math.pi / segments
        verts.append(_v2(cx_pix + rx * math.cos(theta), cy_pix + ry * math.sin(theta)))
    o = OutlineT()
    o.vertices = verts
    o.closed = True
    o.descriptorKind = OutlineKind.Polygon
    o.rings = []
    return o


# Shape kind → outline factory. Catalog pages dispatch on this
# table so the per-shape row sweep is uniform.
SHAPE_BUILDERS = {
    "rect": rect_outline,
    "octagon": octagon_outline,
    "circle": circle_outline,
}


__all__ = [
    "rect_outline", "octagon_outline", "circle_outline",
    "SHAPE_BUILDERS",
]
