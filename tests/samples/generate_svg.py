#!/usr/bin/env python3
"""Generate sample SVG maps for visual inspection.

Usage:
    python -m tests.samples.generate_svg [--outdir DIR] [--seeds S1,S2,...]
    python -m tests.samples.generate_svg --seeds 32244540 --shape-variety 0.3
    python -m tests.samples.generate_svg --sites-only --seeds 7
    python -m tests.samples.generate_svg --buildings-only --seeds 7

Default run (no flags) produces a complete catalog under
``debug/``:

* BSP shape-variety samples (0.0 / 0.5 / 1.0 sweep, or one exact
  level via ``--shape-variety``) with room / door / corridor /
  feature labels overlaid.
* Structural template samples (tower / crypt / mine).
* Underworld biome samples (cave / fungal_cavern / lava_chamber /
  underground_lake).
* Settlement size classes (hamlet / village / town / city).
* Building wall + enclosure + surface reference sheets.
* Macro site samples -- one surface SVG plus per-floor SVGs for
  each kind in :data:`nhc.sites._site.SITE_KINDS` (tower, farm,
  mansion, keep, town, temple, cottage, ruin, mage_residence).
* Sub-hex site samples -- one surface SVG per
  centerpiece variant for wayside / clearing / sacred / den /
  graveyard / campsite / orchard.

``--sites-only`` skips the references / dungeons / settlements
and produces only macro + sub-hex site samples for fast graphical
iteration.

The catalog also includes:

* Wells + fountains demo (well / well_square / fountain /
  fountain_square + a tree row + grove for visual reference).
* Floor variants demo (cobblestone family STREET / BRICK /
  FLAGSTONE side by side, plus wood vs stone interior
  comparison).
* Vegetation demo (tree cluster progression 1/2/3/5/10 with
  per-tile vs grove-union split, per-tile hue jitter grid,
  bush layout sampler, combined cartographer-style scene).
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import nhc_render

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import HybridShape, SurfaceType, Terrain
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import ir_to_svg
from nhc.rendering.svg import (
    CELL, PADDING,
    _room_svg_outline, _find_doorless_openings, _outline_with_gaps,
    _room_shapely_polygon,
)
from nhc.utils.rng import set_seed


# ── IR-driven render helpers ───────────────────────────────────────
#
# The sample generator runs every category through the production
# IR pipeline so each sample produces the exact bytes the web
# server emits. ``_floor_pair`` builds the IR once and rasterises
# to both SVG (via ``ir_to_svg``) and PNG (via the Rust tiny-skia
# rasteriser). ``_save_pair`` writes the matching ``<base>.svg``
# and ``<base>.png`` files side by side so visual diffs surface
# IR bugs that show only in one path.


def _floor_pair(
    level, *, seed: int = 0, **kwargs,
) -> tuple[bytes, str, bytes]:
    """Build a FloorIR for ``level`` and rasterise both ways.

    Returns ``(buf, svg_text, png_bytes)``. ``kwargs`` forward to
    :func:`build_floor_ir` (``site=``, ``building_footprint=``,
    ``building_polygon=``, ``vegetation=``, ``hatch_distance=``).
    """
    buf = build_floor_ir(level, seed=seed, **kwargs)
    svg = ir_to_svg(buf)
    png = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    return buf, svg, png


def _ir_to_pair(buf: bytes) -> tuple[str, bytes]:
    """Rasterise an existing IR buffer to both SVG and PNG.

    For synthetic IR fixtures (wall + enclosure reference sheets)
    that hand-build a buffer rather than going through
    ``build_floor_ir``.
    """
    svg = ir_to_svg(buf)
    png = bytes(nhc_render.ir_to_png(buf, 1.0, None))
    return svg, png


def _save_pair(base: Path, svg: str, png: bytes) -> None:
    """Write ``<base>.svg`` and ``<base>.png`` side by side."""
    base.with_suffix(".svg").write_text(svg)
    base.with_suffix(".png").write_bytes(png)


# ── Synthetic-IR scaffolding for wall + enclosure references ───────
#
# The standalone wall and enclosure reference sheets live entirely
# inside the IR pipeline: each one builds a ``FloorIR`` buffer with
# just enough metadata to drive a single primitive (BuildingWallOp,
# EnclosureOp), then rasterises it through the same ir_to_svg /
# ir_to_png path the production server uses. The dataclasses below
# stand in for ``RenderContext`` / ``Level`` / ``Building`` — they
# carry only the attributes ``FloorIRBuilder.finish()`` and the
# building-wall emit helpers actually read.


@dataclass
class _DemoLevel:
    """Minimal Level stand-in: width/height + interior_edges +
    a no-op ``tile_at``. Matches the test fixtures'
    ``_StubLevelWithEdges`` shape so emit_building_walls is happy.
    """

    width: int = 32
    height: int = 32
    interior_edges: list[tuple[int, int, str]] = dc_field(
        default_factory=list,
    )

    def tile_at(self, x: int, y: int):
        return None


@dataclass
class _DemoCtx:
    """Minimal RenderContext stand-in. Only fields
    ``FloorIRBuilder.finish`` and ``_build_flags`` consume."""

    level: object
    seed: int = 0
    theme: str = "dungeon"
    floor_kind: str = "surface"
    shadows_enabled: bool = True
    hatching_enabled: bool = True
    atmospherics_enabled: bool = True
    macabre_detail: bool = False
    vegetation_enabled: bool = True
    interior_finish: str = ""


@dataclass
class _DemoBuildingForWalls:
    """Stand-in for ``nhc.dungeon.building.Building`` carrying just
    the attributes ``emit_building_walls`` reads."""

    base_shape: object
    base_rect: object
    wall_material: str = "brick"
    interior_wall_material: str = "stone"


DEFAULT_SEEDS = [7, 42, 99]
VARIETIES = [
    ("rect", 0.0),
    ("mixed", 0.5),
    ("shapes", 1.0),
]

LABEL_FONT = "monospace"
LABEL_BG = "rgba(255,255,240,0.85)"
LABEL_BORDER = "#888"

DOOR_FEATURES = {
    "door_closed": "C",
    "door_open": "O",
    "door_secret": "S",
    "door_locked": "L",
}
DOOR_RECT_COLOR = "#1565C0"
DOOR_LABEL_COLOR = "#0D47A1"
DOOR_RECT_BG = "rgba(200,220,255,0.8)"


def _shape_label(shape) -> str:
    """Human-readable shape description."""
    name = type(shape).__name__.replace("Shape", "").lower()
    if isinstance(shape, HybridShape):
        left = type(shape.left).__name__.replace("Shape", "").lower()
        right = type(shape.right).__name__.replace("Shape", "").lower()
        axis = "v" if shape.split == "vertical" else "h"
        return f"hybrid({left}+{right},{axis})"
    return name


def _inject_room_labels(svg_text: str, level) -> str:
    """Parse the SVG and append room number + detail overlays."""
    # Parse, preserving the SVG namespace
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.fromstring(svg_text)

    # Build a group for all labels, rendered on top of everything
    label_group = ET.SubElement(root, f"{{{ns}}}g")
    label_group.set("id", "room-labels")

    for i, room in enumerate(level.rooms):
        r = room.rect
        # Pixel center of bounding rect
        cx = PADDING + (r.x + r.width / 2) * CELL
        cy = PADDING + (r.y + r.height / 2) * CELL

        shape_desc = _shape_label(room.shape)
        line1 = f"#{i}"
        line2 = f"{shape_desc}"
        line3 = f"{r.width}x{r.height}"

        # Background rect for readability
        bw, bh = 120, 44
        bg = ET.SubElement(label_group, f"{{{ns}}}rect")
        bg.set("x", f"{cx - bw / 2:.1f}")
        bg.set("y", f"{cy - bh / 2:.1f}")
        bg.set("width", f"{bw}")
        bg.set("height", f"{bh}")
        bg.set("rx", "4")
        bg.set("fill", LABEL_BG)
        bg.set("stroke", LABEL_BORDER)
        bg.set("stroke-width", "0.5")

        # Room number (bold, larger)
        num = ET.SubElement(label_group, f"{{{ns}}}text")
        num.set("x", f"{cx:.1f}")
        num.set("y", f"{cy - 8:.1f}")
        num.set("text-anchor", "middle")
        num.set("font-family", LABEL_FONT)
        num.set("font-size", "13")
        num.set("font-weight", "bold")
        num.set("fill", "#D32F2F")
        num.text = line1

        # Shape type
        desc = ET.SubElement(label_group, f"{{{ns}}}text")
        desc.set("x", f"{cx:.1f}")
        desc.set("y", f"{cy + 4:.1f}")
        desc.set("text-anchor", "middle")
        desc.set("font-family", LABEL_FONT)
        desc.set("font-size", "9")
        desc.set("fill", "#333")
        desc.text = line2

        # Dimensions
        dims = ET.SubElement(label_group, f"{{{ns}}}text")
        dims.set("x", f"{cx:.1f}")
        dims.set("y", f"{cy + 15:.1f}")
        dims.set("text-anchor", "middle")
        dims.set("font-family", LABEL_FONT)
        dims.set("font-size", "9")
        dims.set("fill", "#555")
        dims.text = line3

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _inject_door_labels(svg_text: str, level) -> str:
    """Overlay numbered door markers on each door tile."""
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.fromstring(svg_text)

    door_group = ET.SubElement(root, f"{{{ns}}}g")
    door_group.set("id", "door-labels")

    # Collect all door tiles with their positions
    door_idx = 0
    expand = CELL * 0.1  # 20% wider = 10% each side

    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            if tile.feature not in DOOR_FEATURES:
                continue

            kind = DOOR_FEATURES[tile.feature]
            side = tile.door_side

            # Pixel position of the tile top-left
            px = PADDING + x * CELL
            py_ = PADDING + y * CELL

            # Door edge rectangle: spans the full tile edge,
            # 20% wider than a tile edge on the perpendicular axis
            thickness = CELL * 0.2
            if side == "north":
                rx = px - expand
                ry = py_ - thickness / 2
                rw = CELL + 2 * expand
                rh = thickness
            elif side == "south":
                rx = px - expand
                ry = py_ + CELL - thickness / 2
                rw = CELL + 2 * expand
                rh = thickness
            elif side == "west":
                rx = px - thickness / 2
                ry = py_ - expand
                rw = thickness
                rh = CELL + 2 * expand
            elif side == "east":
                rx = px + CELL - thickness / 2
                ry = py_ - expand
                rw = thickness
                rh = CELL + 2 * expand
            else:
                # No door_side set — fallback to full tile highlight
                rx = px - expand
                ry = py_ - expand
                rw = CELL + 2 * expand
                rh = CELL + 2 * expand

            # Door edge highlight rectangle
            rect = ET.SubElement(door_group, f"{{{ns}}}rect")
            rect.set("x", f"{rx:.1f}")
            rect.set("y", f"{ry:.1f}")
            rect.set("width", f"{rw:.1f}")
            rect.set("height", f"{rh:.1f}")
            rect.set("rx", "2")
            rect.set("fill", DOOR_RECT_BG)
            rect.set("stroke", DOOR_RECT_COLOR)
            rect.set("stroke-width", "1.5")

            # Label: "D0 C", "D1 S", etc.
            tcx = px + CELL / 2
            tcy = py_ + CELL / 2
            label_text = f"D{door_idx} {kind}"

            # Small background for text readability
            lbw, lbh = 36, 14
            lbg = ET.SubElement(door_group, f"{{{ns}}}rect")
            lbg.set("x", f"{tcx - lbw / 2:.1f}")
            lbg.set("y", f"{tcy - lbh / 2:.1f}")
            lbg.set("width", f"{lbw}")
            lbg.set("height", f"{lbh}")
            lbg.set("rx", "2")
            lbg.set("fill", DOOR_RECT_BG)
            lbg.set("stroke", "none")

            txt = ET.SubElement(door_group, f"{{{ns}}}text")
            txt.set("x", f"{tcx:.1f}")
            txt.set("y", f"{tcy + 4:.1f}")
            txt.set("text-anchor", "middle")
            txt.set("font-family", LABEL_FONT)
            txt.set("font-size", "10")
            txt.set("font-weight", "bold")
            txt.set("fill", DOOR_LABEL_COLOR)
            txt.text = label_text

            door_idx += 1

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _find_corridor_segments(level):
    """Flood-fill corridor tiles into connected segments.

    Returns list of segments, each a sorted list of (x, y) tiles.
    """
    corridor_tiles = set()
    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            if (tile.terrain == Terrain.FLOOR
                    and tile.surface_type == SurfaceType.CORRIDOR):
                corridor_tiles.add((x, y))

    segments = []
    visited = set()
    for start in sorted(corridor_tiles):
        if start in visited:
            continue
        # Flood fill
        seg = []
        queue = [start]
        while queue:
            pos = queue.pop()
            if pos in visited:
                continue
            visited.add(pos)
            seg.append(pos)
            x, y = pos
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = (x + dx, y + dy)
                if nb in corridor_tiles and nb not in visited:
                    queue.append(nb)
        segments.append(sorted(seg))
    return segments


def _inject_corridor_labels(svg_text: str, level) -> str:
    """Overlay corridor segment numbers at each segment's center."""
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.fromstring(svg_text)

    cor_group = ET.SubElement(root, f"{{{ns}}}g")
    cor_group.set("id", "corridor-labels")

    segments = _find_corridor_segments(level)

    for i, seg in enumerate(segments):
        # Place label at the middle tile of the segment
        mid = seg[len(seg) // 2]
        cx = PADDING + (mid[0] + 0.5) * CELL
        cy = PADDING + (mid[1] + 0.5) * CELL

        label = f"C{i}"

        # Background pill
        lbw, lbh = 28, 14
        bg = ET.SubElement(cor_group, f"{{{ns}}}rect")
        bg.set("x", f"{cx - lbw / 2:.1f}")
        bg.set("y", f"{cy - lbh / 2:.1f}")
        bg.set("width", f"{lbw}")
        bg.set("height", f"{lbh}")
        bg.set("rx", "3")
        bg.set("fill", "rgba(220,240,220,0.85)")
        bg.set("stroke", "#4a7a4a")
        bg.set("stroke-width", "0.5")

        txt = ET.SubElement(cor_group, f"{{{ns}}}text")
        txt.set("x", f"{cx:.1f}")
        txt.set("y", f"{cy + 4:.1f}")
        txt.set("text-anchor", "middle")
        txt.set("font-family", LABEL_FONT)
        txt.set("font-size", "9")
        txt.set("font-weight", "bold")
        txt.set("fill", "#2e5a2e")
        txt.text = label

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


_FEATURE_MARKER_SKIP = {
    "door_closed", "door_open", "door_secret", "door_locked",
    "stairs_up", "stairs_down",
}
_FEATURE_LABEL_BG = "rgba(255,235,200,0.92)"
_FEATURE_LABEL_BORDER = "#a0651e"
_FEATURE_LABEL_FILL = "#7a3e00"


def _inject_feature_markers(svg_text: str, level) -> str:
    """Pin a small label on each non-door / non-stairs feature tile.

    Surface features such as ``well``, ``shrine``, ``campfire``, or
    ``tomb_entrance`` carry no glyph in ``render_floor_svg`` (they
    are spawned as ECS entities at runtime). For visual debugging
    we want to see where the centerpiece sits, so this overlay
    drops a labelled marker on each one.
    """
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.fromstring(svg_text)

    grp = ET.SubElement(root, f"{{{ns}}}g")
    grp.set("id", "feature-markers")

    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            feat = tile.feature
            if not feat or feat in _FEATURE_MARKER_SKIP:
                continue
            cx = PADDING + (x + 0.5) * CELL
            cy = PADDING + (y + 0.5) * CELL

            # Crosshair on the tile centre
            for (dx0, dy0, dx1, dy1) in (
                (-5, 0, 5, 0), (0, -5, 0, 5),
            ):
                line = ET.SubElement(grp, f"{{{ns}}}line")
                line.set("x1", f"{cx + dx0:.1f}")
                line.set("y1", f"{cy + dy0:.1f}")
                line.set("x2", f"{cx + dx1:.1f}")
                line.set("y2", f"{cy + dy1:.1f}")
                line.set("stroke", _FEATURE_LABEL_BORDER)
                line.set("stroke-width", "1.2")

            text = feat
            char_w = 5.6
            font_size = 9
            pill_w = max(28.0, len(text) * char_w + 10)
            pill_h = font_size + 6

            bg = ET.SubElement(grp, f"{{{ns}}}rect")
            bg.set("x", f"{cx - pill_w / 2:.1f}")
            bg.set("y", f"{cy - pill_h - 6:.1f}")
            bg.set("width", f"{pill_w:.1f}")
            bg.set("height", f"{pill_h:.1f}")
            bg.set("rx", "3")
            bg.set("fill", _FEATURE_LABEL_BG)
            bg.set("stroke", _FEATURE_LABEL_BORDER)
            bg.set("stroke-width", "0.5")

            txt = ET.SubElement(grp, f"{{{ns}}}text")
            txt.set("x", f"{cx:.1f}")
            txt.set("y", f"{cy - 8:.1f}")
            txt.set("text-anchor", "middle")
            txt.set("font-family", LABEL_FONT)
            txt.set("font-size", f"{font_size}")
            txt.set("font-weight", "bold")
            txt.set("fill", _FEATURE_LABEL_FILL)
            txt.text = text

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _inject_tile_coords(svg_text: str, level) -> str:
    """Label each floor tile with its x,y coordinates."""
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.fromstring(svg_text)

    grp = ET.SubElement(root, f"{{{ns}}}g")
    grp.set("id", "tile-coords")
    grp.set("opacity", "0.45")

    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            if tile.terrain != Terrain.FLOOR:
                continue
            px = PADDING + x * CELL + 2
            py_ = PADDING + y * CELL + 7

            txt = ET.SubElement(grp, f"{{{ns}}}text")
            txt.set("x", f"{px:.0f}")
            txt.set("y", f"{py_:.0f}")
            txt.set("font-family", LABEL_FONT)
            txt.set("font-size", "6")
            txt.set("fill", "#333")
            txt.text = f"{x},{y}"

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _build_level_json(level, seed: int, variety: float) -> dict:
    """Build a detailed JSON structure for the level."""
    door_feats = {
        "door_closed", "door_open", "door_secret", "door_locked",
    }

    # Collect all doors
    doors = []
    for y, row in enumerate(level.tiles):
        for x, tile in enumerate(row):
            if tile.feature in door_feats:
                doors.append({
                    "x": x, "y": y,
                    "feature": tile.feature,
                    "door_side": tile.door_side,
                    "px": x * CELL, "py": y * CELL,
                })

    # Build room details
    rooms = []
    for i, room in enumerate(level.rooms):
        r = room.rect
        shape = room.shape
        floor = sorted(room.floor_tiles())

        # Doors adjacent to this room
        room_floor_set = set(floor)
        room_doors = []
        for d in doors:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                if (d["x"] + dx, d["y"] + dy) in room_floor_set:
                    room_doors.append(d)
                    break

        # Doorless openings
        openings = _find_doorless_openings(room, level)
        opening_list = []
        for fx, fy, cx, cy in openings:
            opening_list.append({
                "room_tile": [fx, fy],
                "corridor_tile": [cx, cy],
                "direction": (
                    "north" if cy < fy else
                    "south" if cy > fy else
                    "west" if cx < fx else "east"
                ),
            })

        # SVG outline info
        outline = _room_svg_outline(room)
        outline_info = {"has_smooth_outline": outline is not None}
        if outline:
            outline_info["original_svg"] = outline
            if openings:
                gapped, extensions = _outline_with_gaps(
                    room, outline, openings,
                )
                outline_info["gapped_svg"] = gapped
                outline_info["wall_extensions"] = extensions

        # Shape details
        shape_info = {
            "type": _shape_label(shape),
            "type_name": shape.type_name,
        }
        if isinstance(shape, HybridShape):
            shape_info["split"] = shape.split
            shape_info["left"] = type(shape.left).__name__
            shape_info["right"] = type(shape.right).__name__

        # Tile grid around room (2 tile margin)
        tile_map = {}
        for ty in range(max(0, r.y - 2), min(level.height, r.y2 + 2)):
            for tx in range(max(0, r.x - 2),
                            min(level.width, r.x2 + 2)):
                t = level.tiles[ty][tx]
                key = f"{tx},{ty}"
                cell = {"terrain": t.terrain.name}
                if t.feature:
                    cell["feature"] = t.feature
                if t.surface_type != SurfaceType.NONE:
                    cell["surface_type"] = t.surface_type.value
                if t.door_side:
                    cell["door_side"] = t.door_side
                if (tx, ty) in room_floor_set:
                    cell["room_floor"] = True
                tile_map[key] = cell

        rooms.append({
            "index": i,
            "id": room.id,
            "shape": shape_info,
            "rect": {
                "x": r.x, "y": r.y,
                "w": r.width, "h": r.height,
                "px": r.x * CELL, "py": r.y * CELL,
                "pw": r.width * CELL, "ph": r.height * CELL,
            },
            "floor_tile_count": len(floor),
            "doors": room_doors,
            "doorless_openings": opening_list,
            "outline": outline_info,
            "tile_grid": tile_map,
        })

    # Corridor segments
    segments = _find_corridor_segments(level)
    corridors_json = []
    for i, seg in enumerate(segments):
        corridors_json.append({
            "index": i,
            "tile_count": len(seg),
            "tiles": [[x, y] for x, y in seg],
        })

    return {
        "seed": seed,
        "shape_variety": variety,
        "width": level.width,
        "height": level.height,
        "total_doors": len(doors),
        "total_rooms": len(level.rooms),
        "total_corridors": len(segments),
        "rooms": rooms,
        "corridors": corridors_json,
    }


POLY_COLORS = [
    "#E53935", "#1E88E5", "#43A047", "#FB8C00",
    "#8E24AA", "#00ACC1", "#D81B60", "#6D4C41",
]


def _inject_polygon_overlays(svg_text: str, level) -> str:
    """Draw each room's Shapely polygon as a scaled-down outline
    centered on the room, so the clip shape is visible."""
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    root = ET.fromstring(svg_text)

    grp = ET.SubElement(root, f"{{{ns}}}g")
    grp.set("id", "polygon-overlays")

    for i, room in enumerate(level.rooms):
        poly = _room_shapely_polygon(room)
        if poly is None or poly.is_empty:
            continue

        color = POLY_COLORS[i % len(POLY_COLORS)]
        r = room.rect
        # Room center in pixel coords (with PADDING offset)
        cx = PADDING + (r.x + r.width / 2) * CELL
        cy = PADDING + (r.y + r.height / 2) * CELL

        # Polygon center and extents
        bounds = poly.bounds  # (minx, miny, maxx, maxy)
        px = (bounds[0] + bounds[2]) / 2
        py = (bounds[1] + bounds[3]) / 2
        pw = bounds[2] - bounds[0]
        ph = bounds[3] - bounds[1]

        # Scale to fit in ~40% of room pixel size
        target = min(r.width * CELL, r.height * CELL) * 0.4
        scale = target / max(pw, ph) if max(pw, ph) > 0 else 1

        # Build path from polygon exterior
        geoms = (poly.geoms if hasattr(poly, 'geoms')
                 else [poly])
        d = ""
        for geom in geoms:
            coords = list(geom.exterior.coords)
            # Transform: center on room, scale down
            pts = []
            for gx, gy in coords:
                sx = cx + (gx - px) * scale
                sy = cy + (gy - py) * scale
                pts.append((sx, sy))
            d += f"M{pts[0][0]:.1f},{pts[0][1]:.1f} "
            d += " ".join(
                f"L{x:.1f},{y:.1f}" for x, y in pts[1:])
            d += " Z "

        path = ET.SubElement(grp, f"{{{ns}}}path")
        path.set("d", d)
        path.set("fill", color)
        path.set("fill-opacity", "0.15")
        path.set("stroke", color)
        path.set("stroke-width", "1.5")
        path.set("stroke-opacity", "0.8")

        # Small label
        lbl = ET.SubElement(grp, f"{{{ns}}}text")
        lbl.set("x", f"{cx:.1f}")
        lbl.set("y", f"{cy + target / 2 + 10:.1f}")
        lbl.set("text-anchor", "middle")
        lbl.set("font-family", LABEL_FONT)
        lbl.set("font-size", "7")
        lbl.set("fill", color)
        lbl.text = f"P{i}"

    return ET.tostring(root, encoding="unicode",
                       xml_declaration=True)


def generate(outdir: Path, seeds: list[int],
             varieties: list[tuple[str, float]] | None = None,
             ) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    gen = BSPGenerator()
    varieties = varieties or VARIETIES

    for seed in seeds:
        for label, variety in varieties:
            set_seed(seed)
            params = GenerationParams(seed=seed, shape_variety=variety)
            level = gen.generate(params)
            _, svg, png = _floor_pair(level, seed=seed)
            # Debug overlays only land on the SVG; the PNG is the
            # raw IR rasteriser output (matches the web .png).
            svg = _inject_tile_coords(svg, level)
            svg = _inject_polygon_overlays(svg, level)
            svg = _inject_room_labels(svg, level)
            svg = _inject_door_labels(svg, level)
            svg = _inject_corridor_labels(svg, level)

            base = outdir / f"sample_seed{seed}_{label}"
            _save_pair(base, svg, png)

            level_data = _build_level_json(level, seed, variety)
            base.with_suffix(".json").write_text(
                json.dumps(level_data, indent=2))

            shapes: dict[str, int] = {}
            for room in level.rooms:
                name = type(room.shape).__name__
                shapes[name] = shapes.get(name, 0) + 1
            print(f"{base.with_suffix('.svg')}: "
                  f"{len(level.rooms)} rooms, {shapes}")


# ── Template-based generation ──────────────────────────────────────

# Each entry: (file_label, template_name, width, height, theme_hint)
TEMPLATE_SPECS: list[tuple[str, str, int, int, str | None]] = [
    ("tower",   "procedural:tower",  60,  40, None),
    ("crypt",   "procedural:crypt",  80,  40, None),
    ("mine",    "procedural:mine",   80,  40, None),
]

# Underworld biome samples: (label, theme, width, height)
UNDERWORLD_SPECS: list[tuple[str, str, int, int]] = [
    ("cave",             "cave",             80, 50),
    ("fungal_cavern",    "fungal_cavern",    90, 55),
    ("lava_chamber",     "lava_chamber",    100, 60),
    ("underground_lake", "underground_lake", 110, 65),
]

# Settlement size classes. Width / height are unused now (the
# town assembler picks the footprint from its own size-class
# preset) but kept in the tuple so the renderer loop below can
# stay structurally aligned with TEMPLATE_SPECS.
SETTLEMENT_SPECS: list[tuple[str, int, int]] = [
    ("hamlet",  30, 22),
    ("village", 50, 30),
    ("town",    62, 36),
    ("city",    74, 42),
]


def _render_and_save(
    level, seed: int, base: Path, label: str,
    inject_labels: bool = True,
    **floor_pair_kwargs,
) -> None:
    """Render a level through the IR pipeline with optional
    debug labels. Writes ``<base>.svg`` and ``<base>.png``.

    ``floor_pair_kwargs`` forward to :func:`_floor_pair` →
    :func:`build_floor_ir` so callers can pass ``site=`` for
    site-aware overlays (RoofOp / EnclosureOp emission), or
    ``vegetation=`` / ``hatch_distance=`` overrides.
    """
    from nhc.rendering._doors_svg import door_overlay_fragments
    _, svg, png = _floor_pair(level, seed=seed, **floor_pair_kwargs)
    door_frags = door_overlay_fragments(level, seed=seed)
    if door_frags:
        svg = svg.replace("</svg>", "".join(door_frags) + "</svg>")
    if inject_labels:
        svg = _inject_room_labels(svg, level)
        svg = _inject_door_labels(svg, level)
        svg = _inject_corridor_labels(svg, level)
        svg = _inject_feature_markers(svg, level)
    _save_pair(base, svg, png)

    tags = {}
    for room in level.rooms:
        for t in room.tags:
            tags[t] = tags.get(t, 0) + 1
    theme = level.metadata.theme if level.metadata else "?"
    print(f"  {base.with_suffix('.svg').name}: "
          f"{len(level.rooms)} rooms, theme={theme}, tags={tags}")


def generate_templates(outdir: Path, seeds: list[int]) -> None:
    """Generate sample SVGs for each structural template."""
    from nhc.dungeon.pipeline import generate_level as gen_level

    tdir = outdir / "templates"
    tdir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        for label, template, w, h, _ in TEMPLATE_SPECS:
            params = GenerationParams(
                width=w, height=h, depth=1, seed=seed,
                shape_variety=0.5, template=template,
            )
            level = gen_level(params)
            base = tdir / f"{label}_seed{seed}"
            _render_and_save(level, seed, base, label)


def generate_underworld(outdir: Path, seeds: list[int]) -> None:
    """Generate sample SVGs for underworld biome themes."""
    from nhc.dungeon.pipeline import generate_level as gen_level

    udir = outdir / "underworld"
    udir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        for label, theme, w, h in UNDERWORLD_SPECS:
            params = GenerationParams(
                width=w, height=h, depth=1, seed=seed,
                shape_variety=0.3, theme=theme,
            )
            level = gen_level(params)
            base = udir / f"{label}_seed{seed}"
            _render_and_save(level, seed, base, label)


def generate_settlements(outdir: Path, seeds: list[int]) -> None:
    """Generate sample SVGs for settlement sizes.

    Renders each size class from the town site assembler; the
    sample shows the town's walkable surface (street grid +
    palisade for non-hamlet sizes) with service-role buildings
    carrying the labelled NPCs.
    """
    import random as rand_mod
    from nhc.sites.town import assemble_town

    sdir = outdir / "settlements"
    sdir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        for label, _w, _h in SETTLEMENT_SPECS:
            site = assemble_town(
                f"settlement_{label}_seed{seed}",
                rand_mod.Random(seed),
                size_class=label,
            )
            base = sdir / f"{label}_seed{seed}"
            # Thread ``site=`` so ``emit_site_overlays`` registers
            # building regions + emits RoofOps and the enclosure
            # ExteriorWallOp (palisade for non-hamlet settlements).
            _render_and_save(
                site.surface, seed, base, label, site=site,
            )


# ── Building generator samples ─────────────────────────────────────

def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def _inject_info_panel(
    svg_text: str, lines: list[str], *,
    x: int = 8, y: int = 8,
) -> str:
    """Overlay a small legend listing the generation parameters.

    Used by every sample generator so the SVG can be eyeballed
    alongside the intent (material, constants, seed, etc.) --
    what was rendered AND why.
    """
    if not lines:
        return svg_text
    font_size = 10
    line_height = font_size + 2
    char_w = 6.3
    panel_w = max(
        220,
        int(max(len(line) for line in lines) * char_w) + 18,
    )
    panel_h = line_height * len(lines) + 14
    parts = [
        f'<g id="info-panel" font-family="monospace" '
        f'font-size="{font_size}">',
        f'<rect x="{x}" y="{y}" width="{panel_w}" '
        f'height="{panel_h}" rx="3" '
        f'fill="rgba(255,255,240,0.95)" stroke="#333" '
        f'stroke-width="0.5"/>',
    ]
    for i, line in enumerate(lines):
        ty = y + 14 + i * line_height
        parts.append(
            f'<text x="{x + 8}" y="{ty}" fill="#111">'
            f'{_xml_escape(line)}</text>'
        )
    parts.append('</g>')
    injection = "".join(parts)
    return svg_text.replace("</svg>", f"{injection}</svg>")


def generate_building_walls(outdir: Path) -> None:
    """Synthetic-IR wall reference sheets — one per
    (shape × wall_material) combination.

    Each sample builds a minimal ``FloorIR`` with one
    ``Region(Building)`` plus one ``BuildingExteriorWallOp`` (and
    a ``BuildingInteriorWallOp`` if interior partitions are
    requested). The IR routes through ``ir_to_svg`` and
    ``ir_to_png`` exactly as it would on the production server,
    so any drift in the masonry primitive shows up identically
    here.
    """
    from nhc.dungeon.model import (
        CircleShape, LShape, OctagonShape, Rect, RectShape,
    )
    from nhc.rendering.ir_emitter import (
        FloorIRBuilder, emit_building_regions, emit_building_walls,
    )

    wdir = outdir / "building_walls"
    wdir.mkdir(parents=True, exist_ok=True)

    # (label, shape, rect, level_w, level_h)
    shape_specs: list[tuple[str, object, object, int, int]] = [
        ("rect",     RectShape(),       Rect(2, 2, 10, 6),  16, 12),
        ("octagon",  OctagonShape(),    Rect(2, 2, 9, 9),   14, 14),
        ("circle",   CircleShape(),     Rect(2, 2, 9, 9),   14, 14),
        ("l_shape",  LShape(corner="se"), Rect(2, 2, 9, 9), 14, 14),
    ]
    materials: list[tuple[str, str]] = [
        ("brick", "stone"),
        ("stone", "wood"),
    ]
    # Interior partition for the rect demos so the
    # BuildingInteriorWallOp pass is also visible.
    interior_edges_for_rect: list[tuple[int, int, str]] = [
        (5, 2, "north"), (5, 3, "north"),
        (5, 4, "north"), (5, 5, "north"),
    ]

    for shape_label, shape, rect, lw, lh in shape_specs:
        for wall_mat, int_mat in materials:
            edges = (
                interior_edges_for_rect if shape_label == "rect"
                else []
            )
            builder = FloorIRBuilder(
                _DemoCtx(level=_DemoLevel(width=lw, height=lh))
            )
            building = _DemoBuildingForWalls(
                base_shape=shape, base_rect=rect,
                wall_material=wall_mat,
                interior_wall_material=int_mat,
            )
            emit_building_regions(builder, [building])
            level = _DemoLevel(
                width=lw, height=lh, interior_edges=edges,
            )
            emit_building_walls(
                builder, building, level,
                base_seed=42, building_index=0,
            )
            buf = builder.finish()
            svg, png = _ir_to_pair(buf)
            info = [
                f"BuildingExteriorWallOp ({wall_mat}) + "
                f"BuildingInteriorWallOp ({int_mat})",
                f"Shape: {shape_label} "
                f"{rect.width}x{rect.height} tiles",
                f"Interior partitions: {len(edges)} edge(s)",
                "IR-only render — same path as web /png endpoint",
            ]
            svg = _inject_info_panel(svg, info)
            base = wdir / (
                f"{shape_label}_{wall_mat}_reference"
            )
            _save_pair(base, svg, png)
            print(f"  {base.name}.{{svg,png}}")


def generate_enclosure_demos(outdir: Path) -> None:
    """Synthetic-IR enclosure reference sheets — one per
    (style × corner × gates) combination.

    Each sample emits a single ``EnclosureOp`` on a shared
    rectangular polygon and rasterises through the IR pipeline.
    Mirrors the synthetic_enclosure_* fixtures in
    tests/fixtures/floor_ir/.
    """
    from nhc.rendering.ir_emitter import (
        FloorIRBuilder, emit_site_enclosure, emit_site_region,
    )
    from nhc.rendering.ir._fb.CornerStyle import CornerStyle
    from nhc.rendering.ir._fb.EnclosureStyle import EnclosureStyle

    edir = outdir / "enclosures"
    edir.mkdir(parents=True, exist_ok=True)

    # Shared 14×10 tile polygon. Gates (when present) sit on the
    # bottom edge midpoint and the right edge midpoint.
    polygon_tiles: list[tuple[float, float]] = [
        (2.0, 2.0), (16.0, 2.0), (16.0, 12.0), (2.0, 12.0),
    ]
    sample_gates: list[tuple[int, float, float]] = [
        (2, 0.5, 40.0),  # bottom-edge mid, 80px-wide gap
        (1, 0.5, 30.0),  # right-edge mid, 60px-wide gap
    ]

    # (label, style, corner_style, gates)
    specs: list[tuple[str, int, int, list | None]] = [
        (
            "palisade_no_gates",
            EnclosureStyle.Palisade, CornerStyle.Merlon, None,
        ),
        (
            "palisade_gated",
            EnclosureStyle.Palisade, CornerStyle.Merlon,
            sample_gates,
        ),
        (
            "fortification_merlon",
            EnclosureStyle.Fortification, CornerStyle.Merlon, None,
        ),
        (
            "fortification_diamond_gated",
            EnclosureStyle.Fortification, CornerStyle.Diamond,
            sample_gates,
        ),
    ]

    for label, style, corner, gates in specs:
        builder = FloorIRBuilder(
            _DemoCtx(level=_DemoLevel(width=20, height=14))
        )
        emit_site_region(builder, (0, 0, 20, 14))
        emit_site_enclosure(
            builder,
            polygon_tiles=polygon_tiles,
            style=style,
            gates=gates,
            base_seed=7,
            corner_style=corner,
        )
        buf = builder.finish()
        svg, png = _ir_to_pair(buf)
        style_name = (
            "palisade" if style == EnclosureStyle.Palisade
            else "fortification"
        )
        corner_name = (
            "merlon" if corner == CornerStyle.Merlon
            else "diamond"
        )
        info = [
            f"EnclosureOp | style: {style_name} | "
            f"corner: {corner_name}",
            "Polygon: 14×10 tiles "
            "(2,2)-(16,2)-(16,12)-(2,12)",
            f"Gates: {len(gates) if gates else 0}",
            "IR-only render — same path as web /png endpoint",
        ]
        svg = _inject_info_panel(svg, info)
        base = edir / f"{label}_reference"
        _save_pair(base, svg, png)
        print(f"  {base.name}.{{svg,png}}")


def _make_surface_patch_level(
    w: int, h: int, patch_w: int = 6, patch_h: int = 4,
    interior_floor: str = "stone",
):
    """Hand-built Level with four surface_type patches side-by-side.

    Patches left→right: STREET, FIELD, GARDEN, plain floor.
    """
    from nhc.dungeon.model import (
        Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
    )
    level = Level.create_empty(
        "surface_demo", "Surface demo", 1, w, h,
    )
    # Fill everything with floor first
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.interior_floor = interior_floor
    level.rooms = [Room(id="demo", rect=Rect(0, 0, w, h))]

    surfaces = (
        SurfaceType.STREET,
        SurfaceType.FIELD,
        SurfaceType.GARDEN,
        SurfaceType.NONE,
    )
    for i, st in enumerate(surfaces):
        x0 = 1 + i * (patch_w + 2)
        if x0 + patch_w >= w:
            break
        for dy in range(patch_h):
            for dx in range(patch_w):
                tile = level.tiles[2 + dy][x0 + dx]
                tile.surface_type = st
                # Phase 3a: GARDEN tiles render on Terrain.GRASS so
                # the theme grass tint paints under the hoe-row
                # overlay.
                if st is SurfaceType.GARDEN:
                    tile.terrain = Terrain.GRASS
    return level


def generate_surface_samples(outdir: Path) -> None:
    """Reference sheet with STREET / FIELD / GARDEN / wood patches."""
    from nhc.rendering._floor_detail import (
        FIELD_STONE_FILL, FIELD_TINT,
        WOOD_FLOOR_FILL, WOOD_GRAIN_DARK,
        WOOD_GRAIN_LIGHT, WOOD_PLANK_LENGTH_MAX,
        WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_WIDTH_PX,
        WOOD_SEAM_STROKE,
    )
    from nhc.rendering.terrain_palette import get_palette

    sdir = outdir / "surface_samples"
    sdir.mkdir(parents=True, exist_ok=True)

    grass_tint = get_palette("dungeon").grass.tint
    stone_info = [
        "Stone interior + surface patch demo",
        "Patches L->R: STREET, FIELD, GARDEN, plain",
        f"FIELD tint: {FIELD_TINT} + stones "
        f"({FIELD_STONE_FILL})",
        f"GARDEN: GRASS terrain tint {grass_tint} (flat tint, "
        "no per-tile overlay)",
        "STREET: cobblestone pattern from legacy renderer",
    ]
    level = _make_surface_patch_level(w=40, h=12, interior_floor="stone")
    _, svg, png = _floor_pair(level, seed=42)
    svg = _inject_info_panel(svg, stone_info)
    _save_pair(sdir / "surface_stone_reference", svg, png)
    print(f"  {sdir}/surface_stone_reference.{{svg,png}}")

    wood_info = [
        "Wood (parquet) interior + surface patch demo",
        f"Plank width: {WOOD_PLANK_WIDTH_PX} px (1/4 tile)",
        f"Plank length: "
        f"{WOOD_PLANK_LENGTH_MIN:.0f}-"
        f"{WOOD_PLANK_LENGTH_MAX:.0f} px (random)",
        f"Fill: {WOOD_FLOOR_FILL}   Seam: {WOOD_SEAM_STROKE}",
        f"Grain streaks: {WOOD_GRAIN_LIGHT} / "
        f"{WOOD_GRAIN_DARK} @ low opacity",
        "Wood short-circuits street/field/garden passes",
    ]
    level = _make_surface_patch_level(w=40, h=12, interior_floor="wood")
    _, svg, png = _floor_pair(level, seed=42)
    svg = _inject_info_panel(svg, wood_info)
    _save_pair(sdir / "surface_wood_reference", svg, png)
    print(f"  {sdir}/surface_wood_reference.{{svg,png}}")


def _make_floor_variants_level(width: int = 44, height: int = 28):
    """Hand-built level showing every floor pattern variant.

    Top band: four cobblestone-family patches side by side --
    STREET, BRICK, FLAGSTONE, OPUS_ROMANO -- so the stones /
    fills / strokes can be eyeballed at the same lighting and
    zoom level. Each patch is 9x7 tiles, big enough that the
    Opus Romano 4-stone arrangement (one 4x4 + 2x2 + 2x4 + 4x2
    on a 6x6 subsquare grid per tile, rotated per tile to break
    the visible repeat) reads clearly.
    """
    from nhc.dungeon.model import (
        Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
    )

    level = Level.create_empty(
        "floor_variants_demo", "Floor variants", 1, width, height,
    )
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(
        id="floor_demo", rect=Rect(0, 0, width, height),
        shape=RectShape(),
    )]

    cobble_specs = (
        ("STREET",           SurfaceType.STREET),
        ("BRICK",            SurfaceType.BRICK),
        ("FLAGSTONE",        SurfaceType.FLAGSTONE),
        ("OPUS_ROMANO", SurfaceType.OPUS_ROMANO),
    )
    patch_w, patch_h = 9, 7
    gap = 1
    for i, (_label, st) in enumerate(cobble_specs):
        x0 = 1 + i * (patch_w + gap)
        if x0 + patch_w >= width:
            break
        for dy in range(patch_h):
            for dx in range(patch_w):
                level.tiles[2 + dy][x0 + dx].surface_type = st

    return level, cobble_specs, patch_w, patch_h, gap


def generate_floor_variants_demo(
    outdir: Path, seeds: list[int],
) -> None:
    """Floor pattern reference: cobblestone family + wood / stone.

    Three SVGs per seed:

    * ``floor_cobblestone_variants_seed<N>.svg`` -- STREET /
      BRICK / FLAGSTONE / OPUS_ROMANO patches side by side
      on a stone interior, with a label pill anchored on each
      patch.
    * ``floor_opus_romano_seed<N>.svg`` -- a dedicated large
      patch of OPUS_ROMANO so the 4-stone Roman arrangement
      can be eyeballed at full clarity (the cobblestone-family
      sheet shrinks each variant for a 4-up comparison).
    * ``floor_wood_vs_stone_seed<N>.svg`` -- two large interior
      rooms (stone vs wood) so the floor-detail decorators can be
      compared on the same seed.
    """
    from nhc.dungeon.model import (
        Level, Rect, Room, RectShape, Terrain, Tile,
    )

    fdir = outdir / "floor_variants"
    fdir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        level, cobble_specs, patch_w, patch_h, gap = (
            _make_floor_variants_level()
        )
        level.interior_floor = "stone"
        _, svg, png = _floor_pair(level, seed=seed)
        # Patch labels.
        label_frags: list[str] = []
        for i, (label, _) in enumerate(cobble_specs):
            x0 = 1 + i * (patch_w + gap)
            cx = PADDING + (x0 + patch_w / 2) * CELL
            cy = PADDING + (2 + patch_h + 0.6) * CELL
            char_w = 5.8
            font_size = 10
            pill_w = len(label) * char_w + 14
            pill_h = font_size + 8
            label_frags.append(
                f'<rect x="{cx - pill_w / 2:.1f}" '
                f'y="{cy - pill_h / 2:.1f}" '
                f'width="{pill_w:.1f}" height="{pill_h:.1f}" '
                f'rx="3" fill="rgba(255,255,240,0.92)" '
                f'stroke="#a0651e" stroke-width="0.5"/>'
                f'<text x="{cx:.1f}" y="{cy + 3:.1f}" '
                f'font-family="monospace" font-size="{font_size}" '
                f'font-weight="bold" text-anchor="middle" '
                f'fill="#7a3e00">{label}</text>'
            )
        svg = svg.replace("</svg>", "".join(label_frags) + "</svg>")
        info = [
            f"Cobblestone family | seed={seed}",
            "L->R: STREET, BRICK, FLAGSTONE, OPUS_ROMANO",
            "  STREET        cobblestone (Dyson-style)",
            "  BRICK         running-bond rectangles",
            "  FLAGSTONE     irregular polygon plates",
            "  OPUS_ROMANO   Versailles 4-stone tiling: 6x6",
            "                subsquare grid grouped into one",
            "                4x4 + 2x4 + 2x2 + 4x2 stones,",
            "                rotated per tile for variety.",
            "All four share the cobblestone wrapping group;",
            "decorators differ in stone shape + stroke colour.",
        ]
        svg = _inject_info_panel(svg, info)
        _save_pair(
            fdir / f"floor_cobblestone_variants_seed{seed}",
            svg, png,
        )
        print(
            f"  {fdir}/floor_cobblestone_variants_seed{seed}"
            ".{svg,png}"
        )

        # ── Dedicated OPUS_ROMANO close-up ──────────────
        # Single large patch so the 4-stone Roman arrangement
        # reads at full clarity. 16x12 tiles at the centre of
        # a 20x16 canvas with stone-floor margin -- mirrors the
        # cobble demo's framing but devoted to one variant.
        from nhc.dungeon.model import SurfaceType as _ST
        opus_w, opus_h = 20, 16
        opus_level = Level.create_empty(
            "opus_demo", "Opus Romano", 1, opus_w, opus_h,
        )
        for y in range(opus_h):
            for x in range(opus_w):
                opus_level.tiles[y][x] = Tile(
                    terrain=Terrain.FLOOR,
                )
        opus_level.rooms = [Room(
            id="opus_demo", rect=Rect(0, 0, opus_w, opus_h),
            shape=RectShape(),
        )]
        opus_level.interior_floor = "stone"
        # Centre patch.
        patch_x0, patch_y0 = 2, 2
        opus_patch_w, opus_patch_h = 16, 12
        for dy in range(opus_patch_h):
            for dx in range(opus_patch_w):
                tile = opus_level.tiles[
                    patch_y0 + dy
                ][patch_x0 + dx]
                tile.surface_type = _ST.OPUS_ROMANO
        _, svg, png = _floor_pair(opus_level, seed=seed)
        # Single label below the patch.
        label_cx = (
            PADDING + (patch_x0 + opus_patch_w / 2) * CELL
        )
        label_cy = (
            PADDING + (patch_y0 + opus_patch_h + 0.6) * CELL
        )
        char_w = 5.8
        font_size = 11
        pill_text = "OPUS_ROMANO"
        pill_w = len(pill_text) * char_w + 16
        pill_h = font_size + 8
        label = (
            f'<rect x="{label_cx - pill_w / 2:.1f}" '
            f'y="{label_cy - pill_h / 2:.1f}" '
            f'width="{pill_w:.1f}" height="{pill_h:.1f}" '
            f'rx="3" fill="rgba(255,255,240,0.92)" '
            f'stroke="#a0651e" stroke-width="0.5"/>'
            f'<text x="{label_cx:.1f}" '
            f'y="{label_cy + 3:.1f}" '
            f'font-family="monospace" font-size="{font_size}" '
            f'font-weight="bold" text-anchor="middle" '
            f'fill="#7a3e00">{pill_text}</text>'
        )
        svg = svg.replace("</svg>", label + "</svg>")
        opus_info = [
            f"Opus Romano close-up | seed={seed}",
            "Classical Roman / Versailles 4-stone tiling.",
            "Each tile is divided into a 6x6 subsquare grid",
            "partitioned into 4 stones:",
            "  4x4 large square + 2x4 vertical rect",
            "  2x2 small square + 4x2 horizontal rect",
            "Per-tile rotation (4 quarter-turns, deterministic",
            "on (tx, ty)) breaks the visible repeat.",
            f"Patch: {opus_patch_w}x{opus_patch_h} tiles, ",
            f"      {opus_patch_w * opus_patch_h * 4} stones.",
            "Stroke: #7A5A3A @ opacity 0.45.",
        ]
        svg = _inject_info_panel(svg, opus_info)
        _save_pair(fdir / f"floor_opus_romano_seed{seed}", svg, png)
        print(
            f"  {fdir}/floor_opus_romano_seed{seed}.{{svg,png}}"
        )

        # Two-room wood vs stone comparison. Each room is its own
        # Room so the renderer's per-room interior_floor gate
        # picks up the material distinction.
        w, h = 28, 14
        rooms_level = Level.create_empty(
            "wood_vs_stone", "Wood vs stone floor", 1, w, h,
        )
        for y in range(h):
            for x in range(w):
                rooms_level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        # Single Room covering the whole grid; the interior_floor
        # is set on the Level (not per-room) so we render twice
        # with a manual flip.
        rooms_level.rooms = [Room(
            id="all", rect=Rect(0, 0, w, h),
            shape=RectShape(),
        )]
        # Two IR pairs (stone + wood) instead of a side-by-side
        # composite. The composite was SVG-only chrome that mixed
        # two IRs into one canvas; the IR pipeline produces one
        # buffer per level, so emitting two separate pairs keeps
        # each .svg / .png pair pinned to a single IR for accurate
        # cross-rasteriser comparison.
        for material in ("stone", "wood"):
            rooms_level.interior_floor = material
            _, svg, png = _floor_pair(rooms_level, seed=seed)
            info = [
                f"{material.capitalize()} interior | seed={seed}",
                "Same Level rendered with interior_floor="
                f"{material!r}.",
                (
                    "Wood decorator short-circuits the stone-floor "
                    "passes."
                ) if material == "wood" else (
                    "Stone interior: cracks, ellipse stones, "
                    "scratches."
                ),
            ]
            svg = _inject_info_panel(svg, info)
            base = fdir / f"floor_{material}_interior_seed{seed}"
            _save_pair(base, svg, png)
            print(f"  {base}.{{svg,png}}")


def _make_vegetation_level(
    width: int, height: int, *, surface_type=None,
):
    """Empty FIELD-grass level for stamping vegetation features."""
    from nhc.dungeon.model import (
        Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
    )
    if surface_type is None:
        surface_type = SurfaceType.FIELD
    level = Level.create_empty(
        "vegetation_demo", "Vegetation demo", 1, width, height,
    )
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.GRASS,
                surface_type=surface_type,
            )
    level.metadata.prerevealed = True
    level.rooms = [Room(
        id="veg", rect=Rect(0, 0, width, height),
        shape=RectShape(),
    )]
    return level


def _stamp_feature_run(
    level, x0: int, y: int, count: int, feature: str,
) -> list[tuple[int, int]]:
    out = []
    for i in range(count):
        x = x0 + i
        level.tiles[y][x].feature = feature
        out.append((x, y))
    return out


def _stamp_feature_block(
    level, x0: int, y0: int, w: int, h: int, feature: str,
) -> list[tuple[int, int]]:
    out = []
    for dy in range(h):
        for dx in range(w):
            level.tiles[y0 + dy][x0 + dx].feature = feature
            out.append((x0 + dx, y0 + dy))
    return out


def _band_label_fragment(
    cx: float, cy: float, text: str,
    *, color_fill: str = "#7a3e00",
    bg_fill: str = "rgba(255,255,240,0.92)",
    border: str = "#a0651e",
    font_size: int = 10,
) -> str:
    char_w = 5.8
    pill_w = len(text) * char_w + 14
    pill_h = font_size + 8
    return (
        f'<rect x="{cx - pill_w / 2:.1f}" '
        f'y="{cy - pill_h / 2:.1f}" '
        f'width="{pill_w:.1f}" height="{pill_h:.1f}" '
        f'rx="3" fill="{bg_fill}" '
        f'stroke="{border}" stroke-width="0.5"/>'
        f'<text x="{cx:.1f}" y="{cy + 3:.1f}" '
        f'font-family="monospace" font-size="{font_size}" '
        f'font-weight="bold" text-anchor="middle" '
        f'fill="{color_fill}">{_xml_escape(text)}</text>'
    )


def generate_vegetation_demo(
    outdir: Path, seeds: list[int],
) -> None:
    """Trees + bushes reference SVGs.

    Three SVGs per seed:

    * ``trees_progression_seed<N>.svg`` -- five tree clusters of
      increasing size (1, 2, 3, 5, 10) so the per-tile / grove
      union threshold can be eyeballed: groves of 1-2 keep the
      shadow + canopy + highlight + trunk stack; groves of 3+
      collapse into a single Shapely-unioned silhouette.
    * ``trees_jitter_grid_seed<N>.svg`` -- a 6x6 grid of isolated
      trees (one per tile) showing the per-tile hue / sat /
      light jitter (+/-6deg H, +/-5% S, +/-4% L). Adjacent tiles
      look distinct rather than tiled.
    * ``bushes_neighbour_bias_seed<N>.svg`` -- bush clusters of
      sizes 1, 2, 5 (row), 9 (block) so the smaller pom-pom +
      no-trunk + tile-bounded canopy can be eyeballed without
      the tree silhouette dominating the read.
    * ``vegetation_combined_seed<N>.svg`` -- a synthetic field
      with both features mixed: a couple of groves, a scatter of
      lone trees, and bushes filling the gaps with a row near
      one edge to show the cartographer-style read.
    """
    vdir = outdir / "vegetation"
    vdir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        # ── Trees: cluster-size progression ──────────────────
        level = _make_vegetation_level(48, 14)
        cluster_sizes = [1, 2, 3, 5, 10]
        cluster_x = [3, 8, 14, 21, 32]
        for x0, size in zip(cluster_x, cluster_sizes):
            _stamp_feature_run(level, x0, 6, size, "tree")
        _, svg, png = _floor_pair(level, seed=seed)
        # Per-cluster label below each cluster.
        labels: list[str] = []
        for x0, size in zip(cluster_x, cluster_sizes):
            cx = PADDING + (x0 + size / 2) * CELL
            cy = PADDING + (6 + 1.6) * CELL
            kind = "grove union" if size >= 3 else "per-tile"
            labels.append(_band_label_fragment(
                cx, cy, f"size={size} ({kind})",
            ))
        svg = svg.replace("</svg>", "".join(labels) + "</svg>")
        info = [
            f"Tree cluster progression | seed={seed}",
            "Sizes 1, 2, 3, 5, 10 -- per-tile vs grove union.",
            "Single + pair: shadow / canopy / highlight / silhouette",
            "  + brown trunk dot.",
            "3+: Shapely unary_union over canopy circles --",
            "  one fragment per grove anchored at min(tx,ty),",
            "  trunks dropped (fused foliage).",
        ]
        svg = _inject_info_panel(svg, info)
        _save_pair(vdir / f"trees_progression_seed{seed}", svg, png)
        print(f"  {vdir}/trees_progression_seed{seed}.{{svg,png}}")

        # ── Trees: per-tile hue jitter grid ──────────────────
        # 6x6 grid with 1-tile gaps so canopies never touch and
        # the grove union never fires (each tree is a size-1
        # cluster).
        grid_n = 6
        gap = 2
        size = grid_n * gap + 2
        level = _make_vegetation_level(size, size)
        for gy in range(grid_n):
            for gx in range(grid_n):
                tx = 1 + gx * gap
                ty = 1 + gy * gap
                level.tiles[ty][tx].feature = "tree"
        _, svg, png = _floor_pair(level, seed=seed)
        info = [
            f"Per-tile hue jitter grid | seed={seed}",
            f"{grid_n}x{grid_n} isolated trees on a "
            f"{gap}-tile lattice.",
            "Each canopy fill jitters HSL deterministically:",
            "  +/-6deg H, +/-5% S, +/-4% L per tile.",
            "Same algorithm produces stable per-grove hue (M2):",
            "  the hue seeds from min(grove) so adding a 4th",
            "  tree nudges colour rather than flipping it.",
        ]
        svg = _inject_info_panel(svg, info)
        _save_pair(vdir / f"trees_jitter_grid_seed{seed}", svg, png)
        print(f"  {vdir}/trees_jitter_grid_seed{seed}.{{svg,png}}")

        # ── Bushes: cluster sizes ───────────────────────────
        level = _make_vegetation_level(40, 14)
        bush_layouts: list[tuple[int, int, str, list[tuple[int, int]]]] = []
        # solo
        positions = _stamp_feature_run(level, 3, 6, 1, "bush")
        bush_layouts.append((3, 6, "solo", positions))
        # pair
        positions = _stamp_feature_run(level, 6, 6, 2, "bush")
        bush_layouts.append((6, 6, "pair", positions))
        # row of 5
        positions = _stamp_feature_run(level, 11, 6, 5, "bush")
        bush_layouts.append((11, 6, "row x5", positions))
        # 3x3 block (9 bushes)
        positions = _stamp_feature_block(level, 19, 4, 3, 3, "bush")
        bush_layouts.append((19, 4, "3x3 block", positions))
        # plus column
        positions = []
        positions += _stamp_feature_run(level, 25, 4, 1, "bush")
        positions += _stamp_feature_run(level, 25, 5, 1, "bush")
        positions += _stamp_feature_run(level, 25, 6, 1, "bush")
        positions += _stamp_feature_run(level, 25, 7, 1, "bush")
        bush_layouts.append((25, 4, "col x4", positions))

        _, svg, png = _floor_pair(level, seed=seed)
        labels = []
        for x0, y0, label, _pos in bush_layouts:
            cx = PADDING + (x0 + 1.0) * CELL
            cy = PADDING + (y0 + 4.0) * CELL
            labels.append(_band_label_fragment(cx, cy, label))
        svg = svg.replace("</svg>", "".join(labels) + "</svg>")
        info = [
            f"Bush layouts | seed={seed}",
            "Solo, pair, row x5, 3x3 block, col x4.",
            "Bushes stay per-tile (no grove union) so their",
            "  small silhouettes layer instead of fusing.",
            "Canopy radius 0.32 cell + jitter 0.10 cell -- the",
            "  silhouette is bounded inside its own tile so a",
            "  bush touching a wall never bleeds onto the roof.",
            "Highlight offset (-0.07, -0.07) cell, lit +12% L.",
        ]
        svg = _inject_info_panel(svg, info)
        _save_pair(vdir / f"bushes_layouts_seed{seed}", svg, png)
        print(f"  {vdir}/bushes_layouts_seed{seed}.{{svg,png}}")

        # ── Combined cartographer-style scene ────────────────
        level = _make_vegetation_level(40, 22)
        # Two groves of 4 (M2 union).
        _stamp_feature_block(level, 3, 3, 4, 1, "tree")
        _stamp_feature_block(level, 18, 3, 1, 4, "tree")
        # A grove of 3 and 5
        _stamp_feature_block(level, 25, 3, 5, 1, "tree")
        # Some isolated trees / pairs
        _stamp_feature_block(level, 4, 12, 1, 1, "tree")
        _stamp_feature_block(level, 7, 13, 2, 1, "tree")
        # Bush "hedge" along the bottom
        _stamp_feature_run(level, 5, 18, 12, "bush")
        # Bushes with neighbour-bias-style clusters
        _stamp_feature_block(level, 28, 12, 2, 2, "bush")
        _stamp_feature_block(level, 32, 14, 2, 2, "bush")
        _stamp_feature_run(level, 22, 16, 4, "bush")
        # Sprinkle isolated bushes
        for (bx, by) in [(11, 8), (15, 11), (35, 5), (3, 16)]:
            level.tiles[by][bx].feature = "bush"

        _, svg, png = _floor_pair(level, seed=seed)
        info = [
            f"Combined vegetation scene | seed={seed}",
            "Top:  two groves of 4 + one grove of 5 (Shapely",
            "      unary_union at 3+ adjacency).",
            "Mid:  a couple of isolated trees + a pair (per-tile).",
            "Bot:  bush hedge of 12 + neighbour-bias clusters",
            "      and a sprinkle of solitary shrubs.",
            "Cartographer-style: trees fuse, bushes accumulate.",
        ]
        svg = _inject_info_panel(svg, info)
        _save_pair(vdir / f"vegetation_combined_seed{seed}", svg, png)
        print(
            f"  {vdir}/vegetation_combined_seed{seed}.{{svg,png}}"
        )


def _feature_label_fragment(
    cell_x: float, cell_y: float, text: str,
    *, color: str = "#7a3e00",
    bg: str = "rgba(255,255,240,0.92)",
    border: str = "#a0651e",
    font_size: int = 9,
) -> str:
    """A small pill label centred at a fractional cell position.

    Use to annotate features without dropping the marker on top
    of the feature itself."""
    cx = PADDING + (cell_x + 0.5) * CELL
    cy = PADDING + (cell_y + 0.5) * CELL
    char_w = 5.4
    pill_w = max(40, len(text) * char_w + 12)
    pill_h = font_size + 7
    return (
        f'<rect x="{cx - pill_w / 2:.1f}" '
        f'y="{cy - pill_h / 2:.1f}" '
        f'width="{pill_w:.1f}" height="{pill_h:.1f}" '
        f'rx="3" fill="{bg}" '
        f'stroke="{border}" stroke-width="0.5"/>'
        f'<text x="{cx:.1f}" y="{cy + 3:.1f}" '
        f'font-family="monospace" font-size="{font_size}" '
        f'font-weight="bold" text-anchor="middle" '
        f'fill="{color}">{_xml_escape(text)}</text>'
    )


def generate_well_demo(outdir: Path, seeds: list[int]) -> None:
    """Side-by-side comparison sheet: every well + fountain
    variant (1x1 well, 1x1 well_square, 2x2 fountain, 2x2
    fountain_square, 3x3 fountain_large, 3x3 fountain_large_square,
    3x3 fountain_cross) plus a tree row + grove for vegetation
    cross-reference.

    All decorations bypass the site assemblers -- this is a
    synthetic level with hand-stamped feature tags so we can
    eyeball the rendering primitives in isolation, particularly
    the unified stone size across feature footprints."""
    from nhc.dungeon.model import (
        Level, Rect, Room, SurfaceType, Terrain, Tile,
    )

    wdir = outdir / "well_demo"
    wdir.mkdir(parents=True, exist_ok=True)

    # Layout: 32 x 26. Info panel anchors top-right (out of the
    # way of all features). Labels sit BELOW each feature so the
    # central pedestal / spout aren't occluded.
    #
    # Anchors:
    #   y=2..2  wells (1x1):     well @ (3,2),  well_square @ (8,2)
    #   y=6..7  fountains 2x2:   fountain @ (2,6),  fountain_square @ (8,6)
    #   y=11..13 3x3 fountains:  fountain_large @ (2,11),
    #                            fountain_large_square @ (10,11),
    #                            fountain_cross @ (18,11)
    #   y=18..18 tree row:       tree solo @ (3,18),
    #                            tree grove @ (10,18)..(13,18)
    width, height = 32, 26
    layouts = [
        # (anchor_x, anchor_y, feature_tag, label_text,
        #  label_cell_x, label_cell_y)
        (3, 2, "well", "well (1x1)", 3, 4),
        (8, 2, "well_square", "well_square (1x1)", 8, 4),
        (2, 6, "fountain", "fountain (2x2)", 3, 9),
        (8, 6, "fountain_square", "fountain_square (2x2)", 9, 9),
        (2, 11, "fountain_large", "fountain_large (3x3)", 3, 15),
        (
            10, 11, "fountain_large_square",
            "fountain_large_square (3x3)", 11, 15,
        ),
        (
            18, 11, "fountain_cross",
            "fountain_cross (3x3 plus)", 19, 15,
        ),
    ]
    tree_solo = (3, 19)
    tree_grove = [(10, 19), (11, 19), (12, 19), (13, 19)]

    for seed in seeds:
        level = Level.create_empty(
            "well_fountain_demo", "Wells + fountains",
            1, width, height,
        )
        for y in range(height):
            for x in range(width):
                level.tiles[y][x] = Tile(
                    terrain=Terrain.FLOOR,
                    surface_type=SurfaceType.FIELD,
                )
        level.rooms = [Room(
            id="r0", rect=Rect(0, 0, width, height),
        )]
        for ax, ay, tag, *_ in layouts:
            level.tiles[ay][ax].feature = tag
        level.tiles[tree_solo[1]][tree_solo[0]].feature = "tree"
        for tx, ty in tree_grove:
            level.tiles[ty][tx].feature = "tree"

        _, svg, png = _floor_pair(level, seed=seed)

        # Custom labels below each feature -- avoids the
        # in-feature pill the generic _inject_feature_markers
        # would drop on top of multi-tile fountains.
        labels = [
            _feature_label_fragment(lx, ly, txt)
            for (_, _, _, txt, lx, ly) in layouts
        ]
        labels.append(_feature_label_fragment(
            tree_solo[0], tree_solo[1] + 1.6, "tree (solo)",
        ))
        labels.append(_feature_label_fragment(
            (tree_grove[0][0] + tree_grove[-1][0]) / 2.0,
            tree_grove[0][1] + 1.6,
            "tree grove (4)",
        ))
        svg = svg.replace("</svg>", "".join(labels) + "</svg>")

        info = [
            f"Wells + fountains + trees | seed={seed}",
            "Top   row: 1x1 wells (circle / square)",
            "2x2   row: 2x2 fountains (circle / square)",
            "3x3   row: 3x3 fountains (circle / square / cross)",
            "Tree  row: isolated tree + 4-tile grove",
            "Stones share a unified physical size (~11 px) so",
            "the masonry reads consistently across footprints.",
        ]
        # Anchor the info panel top-RIGHT so it's clear of
        # all features (top-left would overlap the well row).
        info_x = (width * CELL + 2 * PADDING) - 460
        svg = _inject_info_panel(svg, info, x=info_x, y=8)

        base = wdir / f"well_fountain_demo_seed{seed}"
        _save_pair(base, svg, png)
        print(f"  {base.name}.{{svg,png}}")


# ── Sub-hex site samples ───────────────────────────────────────────
#
# The dispatcher (``nhc.sites._site.assemble_site``) only knows about
# the structured macro kinds. Sub-hex sites (wayside, clearing,
# sacred, den, graveyard, campsite, orchard) are called directly
# with a feature kwarg from the hexcrawl model. The variant list
# below picks one entry per visually-distinct centerpiece so a
# single sample run captures every surface flavour the player can
# walk into from the flower view.

# The hexcrawl enums (Biome, HexFeatureType, MinorFeatureType) are
# resolved lazily inside ``_build_sub_hex_specs`` to keep this
# module's top-level import cheap and avoid pulling the full
# hexcrawl model when callers only want the building-wall demos.
def _build_sub_hex_specs() -> list[tuple[str, str, dict]]:
    """Lazily resolve the feature/biome kwargs for every sub-hex
    sample. Returns ``(kind, label, assemble_kwargs)`` tuples."""
    from nhc.hexcrawl.model import Biome, HexFeatureType, MinorFeatureType

    return [
        ("wayside",   "well",          {
            "feature": MinorFeatureType.WELL,
        }),
        ("wayside",   "signpost",      {
            "feature": MinorFeatureType.SIGNPOST,
        }),
        ("clearing",  "mushroom_ring", {
            "feature": MinorFeatureType.MUSHROOM_RING,
        }),
        ("clearing",  "herb_patch",    {
            "feature": MinorFeatureType.HERB_PATCH,
        }),
        ("clearing",  "hollow_log",    {
            "feature": MinorFeatureType.HOLLOW_LOG,
        }),
        ("clearing",  "bone_pile",     {
            "feature": MinorFeatureType.BONE_PILE,
        }),
        ("sacred",    "shrine",        {
            "feature": MinorFeatureType.SHRINE,
        }),
        ("sacred",    "standing_stone", {
            "feature": MinorFeatureType.STANDING_STONE,
        }),
        ("sacred",    "cairn",         {
            "feature": MinorFeatureType.CAIRN,
        }),
        ("sacred",    "crystals",      {
            "feature": HexFeatureType.CRYSTALS,
        }),
        ("sacred",    "stones",        {
            "feature": HexFeatureType.STONES,
        }),
        ("sacred",    "wonder",        {
            "feature": HexFeatureType.WONDER,
        }),
        ("sacred",    "portal",        {
            "feature": HexFeatureType.PORTAL,
        }),
        ("den",       "forest",        {
            "feature": MinorFeatureType.ANIMAL_DEN,
            "biome": Biome.FOREST,
        }),
        ("den",       "mountain",      {
            "feature": MinorFeatureType.LAIR,
            "biome": Biome.MOUNTAIN,
        }),
        ("graveyard", "default",       {}),
        ("campsite",  "default",       {}),
        ("orchard",   "default",       {}),
    ]


_SUB_HEX_DISPATCH: dict[str, str] = {
    "wayside":   "nhc.sites.wayside.assemble_wayside",
    "clearing":  "nhc.sites.clearing.assemble_clearing",
    "sacred":    "nhc.sites.sacred.assemble_sacred",
    "den":       "nhc.sites.den.assemble_den",
    "graveyard": "nhc.sites.graveyard.assemble_graveyard",
    "campsite":  "nhc.sites.campsite.assemble_campsite",
    "orchard":   "nhc.sites.orchard.assemble_orchard",
}


def _resolve_sub_hex_assembler(kind: str):
    mod_path, _, fn_name = _SUB_HEX_DISPATCH[kind].rpartition(".")
    import importlib
    return getattr(importlib.import_module(mod_path), fn_name)


def generate_sub_hex_sites(outdir: Path, seeds: list[int]) -> None:
    """Render every sub-hex site variant for each seed.

    Output layout: ``<outdir>/sub_hex_sites/<kind>_<label>_seed<N>.svg``.
    Sub-hex sites have no buildings -- the surface is the whole
    interactable level -- so each entry is a single SVG with
    info panel + room/door/corridor/feature labels.
    """
    import random as rand_mod
    from nhc.rendering._doors_svg import door_overlay_fragments

    sdir = outdir / "sub_hex_sites"
    sdir.mkdir(parents=True, exist_ok=True)

    specs = _build_sub_hex_specs()
    for seed in seeds:
        for kind, label, kwargs in specs:
            assembler = _resolve_sub_hex_assembler(kind)
            site_id = f"{kind}_{label}_s{seed}"
            site = assembler(
                site_id, rand_mod.Random(seed), **kwargs,
            )
            # Sub-hex sites have no buildings or enclosure; passing
            # ``site=site`` registers a Site region (informative
            # only) and keeps the IR shape consistent with macro
            # site samples.
            _, svg, png = _floor_pair(
                site.surface, seed=seed, site=site,
            )
            door_frags = door_overlay_fragments(
                site.surface, seed=seed,
            )
            if door_frags:
                svg = svg.replace(
                    "</svg>", "".join(door_frags) + "</svg>",
                )
            svg = _inject_room_labels(svg, site.surface)
            svg = _inject_door_labels(svg, site.surface)
            svg = _inject_corridor_labels(svg, site.surface)
            svg = _inject_feature_markers(svg, site.surface)

            feature_arg = kwargs.get("feature")
            biome_arg = kwargs.get("biome")
            info = [
                f"Sub-hex site: {kind} | label: {label} | "
                f"seed={seed}",
                f"Surface: {site.surface.width}x"
                f"{site.surface.height} tiles",
                f"Feature kwarg: "
                + (
                    f"{type(feature_arg).__name__}."
                    f"{feature_arg.name}"
                    if feature_arg is not None else "(default)"
                ),
                f"Biome kwarg: "
                + (
                    f"{biome_arg.name}"
                    if biome_arg is not None else "(default)"
                ),
                "No buildings; centerpiece marked by overlay.",
            ]
            svg = _inject_info_panel(svg, info)

            base = sdir / f"{kind}_{label}_seed{seed}"
            _save_pair(base, svg, png)
            print(f"  {base.name}.{{svg,png}}")


def generate_building_sites(outdir: Path, seeds: list[int]) -> None:
    """Render every site kind for each seed through the IR pipeline.

    Per site, per seed:
      <kind>_seed<N>_surface.{svg,png} -- outdoor surface, roofs
                                          and enclosure emitted as
                                          IR ops (RoofOp,
                                          EnclosureOp).
      <kind>_seed<N>_b<bi>_f<fi>.{svg,png} -- each building floor,
                                              walls emitted as IR
                                              ops (Building*WallOp).

    Routing through ``build_floor_ir(level, site=site)`` matches
    what the production web server emits — the legacy composite
    overlay path is gone.
    """
    import random as rand_mod
    from nhc.sites._site import SITE_KINDS, assemble_site
    from nhc.rendering._doors_svg import door_overlay_fragments
    from nhc.rendering.building import _perimeter_polygon

    bdir = outdir / "building_sites"
    bdir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        for kind in SITE_KINDS:
            site = assemble_site(
                kind, f"{kind}_s{seed}", rand_mod.Random(seed),
            )
            # Surface IR includes RoofOp + EnclosureOp via
            # emit_site_overlays. Door overlay stays as SVG-only
            # sample chrome so wall edges read clearly outside
            # the game; the PNG is the raw IR rasterisation.
            _, surface_svg, surface_png = _floor_pair(
                site.surface, seed=seed, site=site,
            )
            door_frags = door_overlay_fragments(
                site.surface, seed=seed,
            )
            if door_frags:
                surface_svg = surface_svg.replace(
                    "</svg>", "".join(door_frags) + "</svg>",
                )
            enc_kind = (
                site.enclosure.kind if site.enclosure else "none"
            )
            shapes = sorted({
                type(b.base_shape).__name__
                for b in site.buildings
            })
            materials = sorted({b.wall_material for b in site.buildings})
            floors_used = sorted({
                f.interior_floor
                for b in site.buildings for f in b.floors
            })
            surface_info = [
                f"Site: {kind} | seed={seed}",
                f"Buildings: {len(site.buildings)}",
                f"Shapes: {', '.join(shapes)}",
                f"Wall materials: {', '.join(materials)}",
                f"Interior floors: {', '.join(floors_used)}",
                f"Enclosure: {enc_kind}"
                + (
                    f" ({len(site.enclosure.gates)} gate(s))"
                    if site.enclosure else ""
                ),
                f"Surface size: {site.surface.width}x"
                f"{site.surface.height} tiles",
            ]
            surface_svg = _inject_info_panel(surface_svg, surface_info)
            _save_pair(
                bdir / f"{kind}_seed{seed}_surface",
                surface_svg, surface_png,
            )

            for bi, building in enumerate(site.buildings):
                # Mirror render_building_floor_svg's footprint /
                # polygon prep so the IR's wall pass + wood-floor
                # clip see the same hints the legacy renderer fed
                # to render_floor_svg.
                footprint = building.base_shape.floor_tiles(
                    building.base_rect,
                )
                perimeter = _perimeter_polygon(building)
                if perimeter is not None:
                    polygon = [
                        (x - PADDING, y - PADDING)
                        for x, y in perimeter
                    ]
                else:
                    polygon = None
                for fi in range(len(building.floors)):
                    floor = building.floors[fi]
                    _, floor_svg, floor_png = _floor_pair(
                        floor, seed=seed + fi, site=site,
                        building_footprint=footprint,
                        building_polygon=polygon,
                    )
                    floor_info = [
                        f"Site: {kind} | seed={seed}",
                        f"Building b{bi} of {len(site.buildings)-1}"
                        f" | floor f{fi} of {len(building.floors)-1}",
                        f"Shape: "
                        f"{type(building.base_shape).__name__} "
                        f"{building.base_rect.width}x"
                        f"{building.base_rect.height}",
                        f"Wall material: {building.wall_material}",
                        f"Interior floor: {floor.interior_floor}",
                        f"Stair links: "
                        f"{len(building.stair_links)} total",
                        "Descent: "
                        + (
                            str(building.descent.template)
                            if building.descent else "none"
                        ),
                    ]
                    floor_svg = _inject_info_panel(
                        floor_svg, floor_info,
                    )
                    _save_pair(
                        bdir / f"{kind}_seed{seed}_b{bi}_f{fi}",
                        floor_svg, floor_png,
                    )

            bldg_floor_count = sum(
                len(b.floors) for b in site.buildings
            )
            shapes = {
                type(b.base_shape).__name__
                for b in site.buildings
            }
            enc = (
                site.enclosure.kind if site.enclosure else "none"
            )
            print(
                f"  {kind} seed={seed}: "
                f"{len(site.buildings)} buildings, "
                f"{bldg_floor_count} floors, "
                f"shapes={sorted(shapes)}, enclosure={enc}"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir", type=Path, default=Path("debug"),
        help="output directory (default: debug/)",
    )
    parser.add_argument(
        "--seeds", type=str, default=None,
        help="comma-separated seeds (default: 7,42,99)",
    )
    parser.add_argument(
        "--shape-variety", type=float, default=None,
        help="exact shape_variety value (omit for 0.0/0.5/1.0 sweep)",
    )
    parser.add_argument(
        "--templates-only", action="store_true",
        help="only generate template samples (skip BSP varieties)",
    )
    parser.add_argument(
        "--buildings-only", action="store_true",
        help=(
            "only generate building-generator samples "
            "(walls, enclosures, surfaces, sites)"
        ),
    )
    parser.add_argument(
        "--sites-only", action="store_true",
        help=(
            "only generate per-site samples (macro + sub-hex). "
            "Skips wall / enclosure / surface references for "
            "fast graphical iteration."
        ),
    )
    args = parser.parse_args(argv)

    seeds = (
        [int(s) for s in args.seeds.split(",")]
        if args.seeds else DEFAULT_SEEDS
    )

    if args.sites_only:
        print("── Building site samples (macro) ──")
        generate_building_sites(args.outdir, seeds)
        print("\n── Sub-hex site samples ──")
        generate_sub_hex_sites(args.outdir, seeds)
        print("\n── Wells + fountains demo ──")
        generate_well_demo(args.outdir, seeds)
        print("\n── Floor variants demo ──")
        generate_floor_variants_demo(args.outdir, seeds)
        print("\n── Vegetation demo ──")
        generate_vegetation_demo(args.outdir, seeds)
        return

    if args.buildings_only:
        print("── Building wall references ──")
        generate_building_walls(args.outdir)
        print("\n── Enclosure references ──")
        generate_enclosure_demos(args.outdir)
        print("\n── Surface references ──")
        generate_surface_samples(args.outdir)
        print("\n── Floor variants demo ──")
        generate_floor_variants_demo(args.outdir, seeds)
        print("\n── Vegetation demo ──")
        generate_vegetation_demo(args.outdir, seeds)
        print("\n── Building site samples (macro) ──")
        generate_building_sites(args.outdir, seeds)
        print("\n── Sub-hex site samples ──")
        generate_sub_hex_sites(args.outdir, seeds)
        return

    if not args.templates_only:
        varieties = None
        if args.shape_variety is not None:
            sv = args.shape_variety
            label = f"sv{sv:.2f}".replace(".", "_")
            varieties = [(label, sv)]
        print("── BSP shape variety samples ──")
        generate(args.outdir, seeds, varieties)

    print("\n── Structural template samples ──")
    generate_templates(args.outdir, seeds)
    print("\n── Underworld biome samples ──")
    generate_underworld(args.outdir, seeds)
    print("\n── Settlement samples ──")
    generate_settlements(args.outdir, seeds)
    print("\n── Building wall references ──")
    generate_building_walls(args.outdir)
    print("\n── Enclosure references ──")
    generate_enclosure_demos(args.outdir)
    print("\n── Surface references ──")
    generate_surface_samples(args.outdir)
    print("\n── Building site samples (macro) ──")
    generate_building_sites(args.outdir, seeds)
    print("\n── Sub-hex site samples ──")
    generate_sub_hex_sites(args.outdir, seeds)
    print("\n── Wells + fountains demo ──")
    generate_well_demo(args.outdir, seeds)
    print("\n── Floor variants demo ──")
    generate_floor_variants_demo(args.outdir, seeds)
    print("\n── Vegetation demo ──")
    generate_vegetation_demo(args.outdir, seeds)


if __name__ == "__main__":
    main()
