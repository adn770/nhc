#!/usr/bin/env python3
"""Generate sample SVG dungeon maps for visual inspection.

Usage:
    python -m tests.samples.generate_svg [--outdir DIR] [--seeds S1,S2,...]
    python -m tests.samples.generate_svg --seeds 32244540 --shape-variety 0.3

Outputs SVGs at three shape_variety levels (0.0, 0.5, 1.0) for each
seed.  When --shape-variety is given, only that exact level is
generated (filename uses the numeric value).  Each room is overlaid
with its index number and generation details (shape, bounding rect
dimensions) for easy reference when discussing rendering glitches.
Files land in debug/ by default.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import HybridShape, Terrain
from nhc.rendering.svg import (
    CELL, PADDING, render_floor_svg,
    _room_svg_outline, _find_doorless_openings, _outline_with_gaps,
    _room_shapely_polygon,
)
from nhc.utils.rng import set_seed


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
            if tile.terrain == Terrain.FLOOR and tile.is_corridor:
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
                if t.is_corridor:
                    cell["is_corridor"] = True
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
            svg = render_floor_svg(level, seed=seed)
            svg = _inject_tile_coords(svg, level)
            svg = _inject_polygon_overlays(svg, level)
            svg = _inject_room_labels(svg, level)
            svg = _inject_door_labels(svg, level)
            svg = _inject_corridor_labels(svg, level)

            base = outdir / f"sample_seed{seed}_{label}"
            base.with_suffix(".svg").write_text(svg)

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
    ("keep",    "procedural:keep",   60,  40, None),
]

# Underworld biome samples: (label, theme, width, height)
UNDERWORLD_SPECS: list[tuple[str, str, int, int]] = [
    ("cave",             "cave",             80, 50),
    ("fungal_cavern",    "fungal_cavern",    90, 55),
    ("lava_chamber",     "lava_chamber",    100, 60),
    ("underground_lake", "underground_lake", 110, 65),
]

# Settlement size classes: (label, width, height)
SETTLEMENT_SPECS: list[tuple[str, int, int]] = [
    ("village", 40, 30),
    ("town",    60, 40),
    ("city",    80, 50),
]


def _render_and_save(
    level, seed: int, base: Path, label: str,
    inject_labels: bool = True,
) -> None:
    """Render a level to SVG with optional debug labels."""
    svg = render_floor_svg(level, seed=seed)
    if inject_labels:
        svg = _inject_room_labels(svg, level)
        svg = _inject_door_labels(svg, level)
        svg = _inject_corridor_labels(svg, level)
    base.with_suffix(".svg").write_text(svg)

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
    """Generate sample SVGs for settlement sizes."""
    import random as rand_mod
    from nhc.dungeon.generators.settlement import SettlementGenerator

    sdir = outdir / "settlements"
    sdir.mkdir(parents=True, exist_ok=True)

    gen = SettlementGenerator()
    for seed in seeds:
        for label, w, h in SETTLEMENT_SPECS:
            params = GenerationParams(
                width=w, height=h, depth=1, seed=seed,
                template="procedural:settlement",
            )
            level = gen.generate(params, rng=rand_mod.Random(seed))
            base = sdir / f"{label}_seed{seed}"
            _render_and_save(level, seed, base, label)


# ── Building generator samples ─────────────────────────────────────

def _svg_frame(
    width_px: int, height_px: int, body: str, bg: str = "#F5EDE0",
) -> str:
    """Minimal standalone SVG frame for wall / enclosure demos."""
    return (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<svg width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}" '
        f'xmlns="http://www.w3.org/2000/svg">\n'
        f'<rect width="100%" height="100%" fill="{bg}"/>\n'
        f'{body}\n'
        f'</svg>\n'
    )


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
    """Standalone brick / stone wall-run reference sheets."""
    from nhc.rendering._building_walls import (
        BRICK_FILL, BRICK_SEAM,
        MASONRY_CORNER_RADIUS, MASONRY_MEAN_WIDTH,
        MASONRY_STRIP_COUNT, MASONRY_WALL_THICKNESS,
        MASONRY_WIDTH_HIGH, MASONRY_WIDTH_LOW,
        STONE_FILL, STONE_SEAM,
        render_brick_wall_run, render_stone_wall_run,
    )

    wdir = outdir / "building_walls"
    wdir.mkdir(parents=True, exist_ok=True)

    for label, fn, fill, stroke in (
        ("brick", render_brick_wall_run, BRICK_FILL, BRICK_SEAM),
        ("stone", render_stone_wall_run, STONE_FILL, STONE_SEAM),
    ):
        body: list[str] = []
        # Three horizontal runs at increasing lengths, stacked with
        # 40px breathing room. Each run uses a distinct seed so the
        # stagger visibly differs.
        for i, length in enumerate((120, 240, 360)):
            y = 40 + i * 30
            body.extend(fn(30, y, 30 + length, y, seed=7 + i))
        # Two short vertical runs at x=420, x=470 to show the
        # perpendicular path.
        for i, x in enumerate((420, 480)):
            body.extend(fn(x, 40, x, 40 + 200, seed=21 + i))
        info = [
            f"Building wall material: {label}",
            f"Strip count: {MASONRY_STRIP_COUNT} "
            "(running-bond courses)",
            f"Mean unit width: {MASONRY_MEAN_WIDTH} px "
            f"(jitter {MASONRY_WIDTH_LOW:.2f}-"
            f"{MASONRY_WIDTH_HIGH:.2f})",
            f"Wall thickness: {MASONRY_WALL_THICKNESS} px",
            f"Corner radius: {MASONRY_CORNER_RADIUS} px",
            f"Fill: {fill}   Stroke: {stroke}",
            "Fully filled, no missing overlays",
        ]
        svg = _svg_frame(560, 280, "".join(body))
        svg = _inject_info_panel(svg, info)
        (wdir / f"{label}_wall_reference.svg").write_text(svg)
        print(f"  {wdir}/{label}_wall_reference.svg")


def generate_enclosure_demos(outdir: Path) -> None:
    """Fortification + palisade reference SVGs on a shared polygon."""
    from nhc.rendering._enclosures import (
        FORTIFICATION_CORNER_FILL, FORTIFICATION_CORNER_SCALE,
        FORTIFICATION_CORNER_STYLES, FORTIFICATION_CRENEL_FILL,
        FORTIFICATION_MERLON_FILL, FORTIFICATION_RATIO,
        FORTIFICATION_SIZE, FORTIFICATION_STROKE,
        FORTIFICATION_STROKE_WIDTH,
        PALISADE_CIRCLE_STEP, PALISADE_DOOR_LENGTH_PX,
        PALISADE_FILL, PALISADE_RADIUS_JITTER,
        PALISADE_RADIUS_MAX, PALISADE_RADIUS_MIN,
        PALISADE_STROKE,
        render_fortification_enclosure,
        render_palisade_enclosure,
    )

    edir = outdir / "enclosures"
    edir.mkdir(parents=True, exist_ok=True)

    # Shared test polygon: a 320x200 rect with one gate on the
    # bottom edge and one on the right edge.
    polygon = [(40, 40), (360, 40), (360, 240), (40, 240)]
    gates = [
        (2, 0.5, 40.0),  # bottom edge midpoint, 80px-wide gap
        (1, 0.5, 30.0),  # right edge midpoint, 60px-wide gap
    ]

    # One fortification reference per corner style so the variants
    # can be eyeballed side by side.
    for style in FORTIFICATION_CORNER_STYLES:
        frags = render_fortification_enclosure(
            polygon, gates=gates, corner_style=style,
        )
        info = [
            f"Fortification wall | corner style: {style}",
            f"Corner fill: {FORTIFICATION_CORNER_FILL} "
            f"(scale {FORTIFICATION_CORNER_SCALE}x SIZE)",
            f"Merlon fill: {FORTIFICATION_MERLON_FILL} "
            f"(size {FORTIFICATION_SIZE} px)",
            f"Crenel fill: {FORTIFICATION_CRENEL_FILL} "
            f"(DIN A {FORTIFICATION_RATIO:.3f})",
            f"Stroke: {FORTIFICATION_STROKE} @ "
            f"{FORTIFICATION_STROKE_WIDTH} px",
            "Polygon: 320x200, gates on bottom + right edges",
            "Edges inset by SIZE/2; chain centered per edge",
        ]
        svg = _svg_frame(400, 280, "".join(frags))
        svg = _inject_info_panel(svg, info)
        path = edir / f"fortification_{style}_reference.svg"
        path.write_text(svg)
        print(f"  {path}")

    palisade = render_palisade_enclosure(polygon, gates=gates, seed=5)
    palisade_info = [
        "Palisade enclosure",
        f"Circle radius: {PALISADE_RADIUS_MIN}-{PALISADE_RADIUS_MAX}"
        f" px (jitter ±{PALISADE_RADIUS_JITTER})",
        f"Circle step: {PALISADE_CIRCLE_STEP} px (non-overlap)",
        f"Fill: {PALISADE_FILL}   Stroke: {PALISADE_STROKE}",
        f"Door length: {PALISADE_DOOR_LENGTH_PX} px "
        "(gate rects)",
        "Polygon: 320x200, gates on bottom + right edges",
    ]
    svg = _svg_frame(400, 280, "".join(palisade))
    svg = _inject_info_panel(svg, palisade_info)
    (edir / "palisade_reference.svg").write_text(svg)
    print(f"  {edir}/palisade_reference.svg")


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
                level.tiles[2 + dy][x0 + dx].surface_type = st
    return level


def generate_surface_samples(outdir: Path) -> None:
    """Reference sheet with STREET / FIELD / GARDEN / wood patches."""
    from nhc.rendering._floor_detail import (
        FIELD_STONE_FILL, FIELD_TINT, GARDEN_LINE_STROKE,
        GARDEN_TINT, WOOD_FLOOR_FILL, WOOD_GRAIN_DARK,
        WOOD_GRAIN_LIGHT, WOOD_PLANK_LENGTH_MAX,
        WOOD_PLANK_LENGTH_MIN, WOOD_PLANK_WIDTH_PX,
        WOOD_SEAM_STROKE,
    )

    sdir = outdir / "surface_samples"
    sdir.mkdir(parents=True, exist_ok=True)

    stone_info = [
        "Stone interior + surface patch demo",
        "Patches L->R: STREET, FIELD, GARDEN, plain",
        f"FIELD tint: {FIELD_TINT} + stones "
        f"({FIELD_STONE_FILL})",
        f"GARDEN tint: {GARDEN_TINT} + lines "
        f"({GARDEN_LINE_STROKE})",
        "STREET: cobblestone pattern from legacy renderer",
    ]
    level = _make_surface_patch_level(w=40, h=12, interior_floor="stone")
    svg = render_floor_svg(level, seed=42)
    svg = _inject_info_panel(svg, stone_info)
    (sdir / "surface_stone_reference.svg").write_text(svg)
    print(f"  {sdir}/surface_stone_reference.svg")

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
    svg = render_floor_svg(level, seed=42)
    svg = _inject_info_panel(svg, wood_info)
    (sdir / "surface_wood_reference.svg").write_text(svg)
    print(f"  {sdir}/surface_wood_reference.svg")


# Base roof tints. Each is the mid-sunlit shade; shadow side
# uses ~45% of the tint, sunlit uses ~100%, with a small ±10%
# jitter per shingle. Gradients are out -- flat colours only.
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
    """Three flat shades of the tint. Sunlit side brackets 100%
    of the tint; shadow side sits around ROOF_SHADOW_FACTOR of
    the tint so the non-illuminated half reads ~half as bright."""
    if sunlit:
        factors = (1.15, 1.00, 0.88)
    else:
        centre = ROOF_SHADOW_FACTOR
        factors = (centre * 1.15, centre, centre * 0.88)
    return [_scale_hex(tint, f) for f in factors]


def _footprint_polygon_px(b) -> list[tuple[float, float]] | None:
    """Building footprint as a list of pixel-coord polygon
    vertices. Returns None for shapes without orthogonal polygon
    support (currently CircleShape -- we skip its roof)."""
    from nhc.dungeon.model import (
        CircleShape, LShape, OctagonShape, RectShape,
    )
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


def _roof_mode(b) -> str:
    """Pick gable (2-side) or pyramid (N-triangle) roof style."""
    from nhc.dungeon.model import (
        CircleShape, LShape, OctagonShape, RectShape,
    )
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
    shades: list[str], rng,
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


def _building_roof_fragments(site, seed: int) -> list[str]:
    """One-roof-per-building fragments plus a shared <defs> block.

    Each roof clips to the building's footprint polygon so
    L-shape notches and octagon corners stay clean. Rect (w!=h)
    and L-shape get gable roofs (two halves along the longest
    axis with a black ridge line); square (w==h) and octagon get
    pyramid roofs (N triangles from the polygon centre with N
    ridge lines). Circle roofs are skipped.
    """
    import random as rand_mod
    defs: list[str] = []
    body: list[str] = []
    for i, b in enumerate(site.buildings):
        polygon = _footprint_polygon_px(b)
        if polygon is None:
            continue
        mode = _roof_mode(b)
        if mode == "skip":
            continue

        rng = rand_mod.Random(seed + 0xCAFE + i)
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

        if mode == "gable":
            body.append(
                f'<g clip-path="url(#{clip_id})">'
            )
            body.extend(
                _gable_sides(px, py, pw, ph, r.width >= r.height,
                             sunlit_shades, shadow_shades, rng)
            )
            body.append('</g>')
        else:  # pyramid
            body.append(f'<g clip-path="url(#{clip_id})">')
            body.extend(
                _pyramid_sides(polygon, sunlit_shades,
                               shadow_shades, rng)
            )
            body.append('</g>')

    if not body:
        return []
    return [f'<defs>{"".join(defs)}</defs>'] + body


def _gable_sides(
    px: float, py: float, pw: float, ph: float,
    horizontal: bool,
    sunlit_shades: list[str], shadow_shades: list[str],
    rng,
) -> list[str]:
    """Shingle-filled halves plus the central ridge line."""
    frags: list[str] = []
    if horizontal:
        # North half (shadow), south half (sunlit).
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
        # West half (shadow), east half (sunlit).
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
    rng,
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
        # Shadow if the edge midpoint is to the north (my < cy)
        # or strictly to the west (mx < cx) of the polygon
        # centre. Everything else (south / east / SE) is sunlit.
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
    # Ridges: centre to each polygon vertex.
    for (vx, vy) in polygon:
        frags.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
            f'x2="{vx:.1f}" y2="{vy:.1f}" '
            f'stroke="{ROOF_RIDGE_STROKE}" '
            f'stroke-width="{ROOF_RIDGE_WIDTH}"/>'
        )
    return frags


def _enclosure_fragments_for_site(site, seed: int) -> list[str]:
    """Convert Site.enclosure (tile-coord polygon + tile gates) into
    SVG fragments from the enclosure renderers.

    The Enclosure dataclass stores gates as (x, y, length_tiles) in
    tile space; the renderers expect (edge_index, t_center,
    half_len_px). This helper projects each gate midpoint onto its
    nearest polygon edge and emits the parametric form.
    """
    from nhc.rendering._enclosures import (
        render_fortification_enclosure,
        render_palisade_enclosure,
    )
    if site.enclosure is None:
        return []
    poly_px = [
        (PADDING + x * CELL, PADDING + y * CELL)
        for (x, y) in site.enclosure.polygon
    ]
    gates_param: list[tuple[int, float, float]] = []
    for (gx, gy, length_tiles) in site.enclosure.gates:
        gx_px = PADDING + gx * CELL
        gy_px = PADDING + gy * CELL
        # Pick the edge whose midpoint is nearest the gate point.
        best_idx = 0
        best_d = float("inf")
        best_t = 0.5
        for i in range(len(poly_px)):
            ax, ay = poly_px[i]
            bx, by = poly_px[(i + 1) % len(poly_px)]
            dx, dy = bx - ax, by - ay
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                continue
            t = max(0.0, min(1.0, (
                (gx_px - ax) * dx + (gy_px - ay) * dy
            ) / seg_len_sq))
            px = ax + dx * t
            py = ay + dy * t
            d = (px - gx_px) ** 2 + (py - gy_px) ** 2
            if d < best_d:
                best_d = d
                best_idx = i
                best_t = t
        gates_param.append(
            (best_idx, best_t, length_tiles * CELL / 2)
        )

    if site.enclosure.kind == "fortification":
        return render_fortification_enclosure(
            poly_px, gates=gates_param,
        )
    if site.enclosure.kind == "palisade":
        return render_palisade_enclosure(
            poly_px, gates=gates_param, seed=seed,
        )
    return []


def generate_building_sites(outdir: Path, seeds: list[int]) -> None:
    """Render every site kind for each seed.

    Per site, per seed:
      <kind>_seed<N>_surface.svg -- outdoor surface + enclosure
      <kind>_seed<N>_b<bi>_f<fi>.svg -- each building floor
    """
    import random as rand_mod
    from nhc.dungeon.site import SITE_KINDS, assemble_site
    from nhc.rendering.building import render_building_floor_svg

    bdir = outdir / "building_sites"
    bdir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        for kind in SITE_KINDS:
            site = assemble_site(
                kind, f"{kind}_s{seed}", rand_mod.Random(seed),
            )
            # Surface level with roof + enclosure overlay. Roofs
            # paint building footprints with gradient shingles;
            # the enclosure (palisade / fortification) draws on
            # top of roofs so gates remain visible.
            surface_svg = render_floor_svg(site.surface, seed=seed)
            roof_frags = _building_roof_fragments(site, seed)
            enc_frags = _enclosure_fragments_for_site(site, seed)
            overlay = "".join(roof_frags) + "".join(enc_frags)
            if overlay:
                surface_svg = surface_svg.replace(
                    "</svg>", overlay + "</svg>",
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
            base = bdir / f"{kind}_seed{seed}_surface"
            base.with_suffix(".svg").write_text(surface_svg)

            for bi, building in enumerate(site.buildings):
                for fi in range(len(building.floors)):
                    floor_svg = render_building_floor_svg(
                        building, fi, seed=seed + fi,
                    )
                    floor = building.floors[fi]
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
                    floor_base = (
                        bdir
                        / f"{kind}_seed{seed}_b{bi}_f{fi}"
                    )
                    floor_base.with_suffix(".svg").write_text(
                        floor_svg,
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
    args = parser.parse_args(argv)

    seeds = (
        [int(s) for s in args.seeds.split(",")]
        if args.seeds else DEFAULT_SEEDS
    )

    if args.buildings_only:
        print("── Building wall references ──")
        generate_building_walls(args.outdir)
        print("\n── Enclosure references ──")
        generate_enclosure_demos(args.outdir)
        print("\n── Surface references ──")
        generate_surface_samples(args.outdir)
        print("\n── Building site samples ──")
        generate_building_sites(args.outdir, seeds)
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
    print("\n── Building site samples ──")
    generate_building_sites(args.outdir, seeds)


if __name__ == "__main__":
    main()
