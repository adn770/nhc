#!/usr/bin/env python3
"""Generate sample SVG dungeon maps for visual inspection.

Usage:
    python -m tests.samples.generate_svg [--outdir DIR] [--seeds S1,S2,...]

Outputs SVGs at three shape_variety levels (0.0, 0.5, 1.0) for each
seed.  Each room is overlaid with its index number and generation
details (shape, bounding rect dimensions) for easy reference when
discussing rendering glitches.  Files land in debug/ by default.
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

    return {
        "seed": seed,
        "shape_variety": variety,
        "width": level.width,
        "height": level.height,
        "total_doors": len(doors),
        "total_rooms": len(level.rooms),
        "rooms": rooms,
    }


def generate(outdir: Path, seeds: list[int]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    gen = BSPGenerator()

    for seed in seeds:
        for label, variety in VARIETIES:
            set_seed(seed)
            params = GenerationParams(seed=seed, shape_variety=variety)
            level = gen.generate(params)
            svg = render_floor_svg(level, seed=seed)
            svg = _inject_room_labels(svg, level)
            svg = _inject_door_labels(svg, level)

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
    args = parser.parse_args(argv)

    seeds = (
        [int(s) for s in args.seeds.split(",")]
        if args.seeds else DEFAULT_SEEDS
    )
    generate(args.outdir, seeds)


if __name__ == "__main__":
    main()
