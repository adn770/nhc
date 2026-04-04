"""SVG query tools for inspecting rendered map elements."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from nhc.debug_tools.base import BaseTool

# Must match nhc/rendering/svg.py constants
CELL = 32
PADDING = 32

NS = {"svg": "http://www.w3.org/2000/svg"}


def _parse_rect(el: ET.Element) -> dict | None:
    """Extract rect attributes."""
    try:
        return {
            "x": float(el.get("x", 0)),
            "y": float(el.get("y", 0)),
            "w": float(el.get("width", 0)),
            "h": float(el.get("height", 0)),
            "fill": el.get("fill", ""),
            "stroke": el.get("stroke", ""),
            "opacity": el.get("opacity", ""),
        }
    except (ValueError, TypeError):
        return None


def _rect_overlaps(
    r: dict, tx: float, ty: float, tw: float, th: float,
) -> bool:
    """True if rect overlaps the tile bounding box."""
    return (r["x"] < tx + tw and r["x"] + r["w"] > tx
            and r["y"] < ty + th and r["y"] + r["h"] > ty)


def _parse_path_segments(
    d: str,
) -> list[tuple[float, float, float, float]]:
    """Parse SVG path 'd' into (x1, y1, x2, y2) line segments.

    Handles M, L, H, V, Z and C commands.  Cubic bezier curves
    are sampled with 8 line segments for tile overlap detection.
    """
    segments: list[tuple[float, float, float, float]] = []
    tokens = re.findall(r"[MLHVCZ][^MLHVCZ]*", d)
    cx, cy = 0.0, 0.0
    start_x, start_y = 0.0, 0.0  # for Z
    for token in tokens:
        cmd = token[0]
        nums = [float(n) for n in re.findall(r"-?[\d.]+", token)]
        if cmd == "M":
            if len(nums) >= 2:
                cx, cy = nums[0], nums[1]
                start_x, start_y = cx, cy
        elif cmd == "L":
            if len(nums) >= 2:
                x, y = nums[0], nums[1]
                segments.append((cx, cy, x, y))
                cx, cy = x, y
        elif cmd == "H":
            if nums:
                segments.append((cx, cy, nums[0], cy))
                cx = nums[0]
        elif cmd == "V":
            if nums:
                segments.append((cx, cy, cx, nums[0]))
                cy = nums[0]
        elif cmd == "C":
            # C c1x,c1y c2x,c2y ex,ey — possibly multiple triples
            # Sample each cubic with 8 line segments
            i = 0
            while i + 5 < len(nums):
                c1x, c1y = nums[i], nums[i + 1]
                c2x, c2y = nums[i + 2], nums[i + 3]
                ex, ey = nums[i + 4], nums[i + 5]
                prev_x, prev_y = cx, cy
                steps = 8
                for s in range(1, steps + 1):
                    t = s / steps
                    u = 1 - t
                    bx = (u**3 * cx + 3 * u**2 * t * c1x
                          + 3 * u * t**2 * c2x + t**3 * ex)
                    by = (u**3 * cy + 3 * u**2 * t * c1y
                          + 3 * u * t**2 * c2y + t**3 * ey)
                    segments.append((prev_x, prev_y, bx, by))
                    prev_x, prev_y = bx, by
                cx, cy = ex, ey
                i += 6
        elif cmd == "Z":
            segments.append((cx, cy, start_x, start_y))
            cx, cy = start_x, start_y
    return segments


def _segment_overlaps_tile(
    x1: float, y1: float, x2: float, y2: float,
    tx: float, ty: float, tw: float, th: float,
) -> bool:
    """True if a line segment passes through a tile bounding box."""
    # Check if either endpoint is inside the tile
    for px, py in [(x1, y1), (x2, y2)]:
        if tx <= px <= tx + tw and ty <= py <= ty + th:
            return True
    # Check if the segment crosses tile edges
    # Vertical segment
    if x1 == x2:
        if tx <= x1 <= tx + tw:
            lo, hi = min(y1, y2), max(y1, y2)
            if lo <= ty + th and hi >= ty:
                return True
    # Horizontal segment
    if y1 == y2:
        if ty <= y1 <= ty + th:
            lo, hi = min(x1, x2), max(x1, x2)
            if lo <= tx + tw and hi >= tx:
                return True
    return False


def _classify_element(
    el: ET.Element, parent_idx: int,
) -> str:
    """Classify an SVG element by its rendering layer."""
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    fill = el.get("fill", "")
    stroke = el.get("stroke", "")
    opacity = el.get("opacity", "")

    if tag == "rect":
        if fill == "#000000" and opacity:
            return "shadow"
        if fill == "#D0D0D0":
            return "hatch_underlay"
        if fill == "#FFFFFF" and stroke == "none":
            return "floor_fill"
        if fill != "":
            return f"rect({fill})"
    elif tag == "path":
        sw = el.get("stroke-width", "")
        if stroke == "#000000" and sw:
            w = float(sw)
            if w >= 3.0:
                return "wall_segment"
            elif w >= 1.0:
                return "hatch_line"
            else:
                return "grid_line"
        if fill == "none" and stroke:
            return "outline"
    elif tag == "polygon":
        if fill == "#000000" and opacity:
            return "shadow"
        if fill == "none":
            return "wall_outline"
        return "room_fill"
    elif tag == "circle":
        if fill == "none":
            return "wall_outline"
        return "room_fill"
    elif tag == "ellipse":
        return "hatch_stone"
    elif tag == "line":
        return "stair_line"
    return f"{tag}"


def _query_tile_elements(
    svg_path: Path, tile_x: int, tile_y: int,
) -> list[dict]:
    """Find SVG elements overlapping a tile at (tile_x, tile_y).

    Coordinates are in SVG-local space (inside the translate
    group), so tile pixel bounds are (x*CELL, y*CELL) to
    ((x+1)*CELL, (y+1)*CELL).
    """
    tx = tile_x * CELL
    ty = tile_y * CELL
    tw = CELL
    th = CELL

    tree = ET.parse(svg_path)
    root = tree.getroot()
    results: list[dict] = []

    # Find the main translate group
    groups = root.findall("svg:g", NS)
    if not groups:
        # Try without namespace
        groups = root.findall("g")
    if not groups:
        return [{"error": "no <g> group found in SVG"}]

    main_g = groups[0]

    for idx, el in enumerate(main_g):
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag

        if tag == "rect":
            r = _parse_rect(el)
            if r and _rect_overlaps(r, tx, ty, tw, th):
                layer = _classify_element(el, idx)
                results.append({
                    "type": layer,
                    "element": "rect",
                    "x": r["x"], "y": r["y"],
                    "w": r["w"], "h": r["h"],
                    "fill": r["fill"],
                })

        elif tag == "path":
            d = el.get("d", "")
            segs = _parse_path_segments(d)
            matching = [
                s for s in segs
                if _segment_overlaps_tile(*s, tx, ty, tw, th)
            ]
            if matching:
                layer = _classify_element(el, idx)
                for s in matching:
                    results.append({
                        "type": layer,
                        "element": "path_segment",
                        "x1": s[0], "y1": s[1],
                        "x2": s[2], "y2": s[3],
                        "stroke_width": el.get(
                            "stroke-width", ""),
                    })

        elif tag == "polygon":
            pts_str = el.get("points", "")
            pts = re.findall(r"([\d.]+),([\d.]+)", pts_str)
            if pts:
                xs = [float(p[0]) for p in pts]
                ys = [float(p[1]) for p in pts]
                px_min, px_max = min(xs), max(xs)
                py_min, py_max = min(ys), max(ys)
                if (px_min < tx + tw and px_max > tx
                        and py_min < ty + th and py_max > ty):
                    layer = _classify_element(el, idx)
                    results.append({
                        "type": layer,
                        "element": "polygon",
                        "bounds": {
                            "x": px_min, "y": py_min,
                            "w": px_max - px_min,
                            "h": py_max - py_min,
                        },
                    })

        elif tag == "circle":
            cx_v = float(el.get("cx", 0))
            cy_v = float(el.get("cy", 0))
            r_v = float(el.get("r", 0))
            if (cx_v - r_v < tx + tw and cx_v + r_v > tx
                    and cy_v - r_v < ty + th and cy_v + r_v > ty):
                layer = _classify_element(el, idx)
                results.append({
                    "type": layer,
                    "element": "circle",
                    "cx": cx_v, "cy": cy_v, "r": r_v,
                })

        elif tag == "ellipse":
            cx_v = float(el.get("cx", 0))
            cy_v = float(el.get("cy", 0))
            rx = float(el.get("rx", 0))
            ry = float(el.get("ry", 0))
            if (cx_v - rx < tx + tw and cx_v + rx > tx
                    and cy_v - ry < ty + th and cy_v + ry > ty):
                layer = _classify_element(el, idx)
                results.append({
                    "type": layer,
                    "element": "ellipse",
                    "cx": cx_v, "cy": cy_v,
                    "rx": rx, "ry": ry,
                })

        # Recurse into nested <g> groups (e.g. shadow offsets)
        elif tag == "g":
            transform = el.get("transform", "")
            g_dx, g_dy = 0.0, 0.0
            m = re.search(
                r"translate\(([\d.]+),([\d.]+)\)", transform)
            if m:
                g_dx = float(m.group(1))
                g_dy = float(m.group(2))
            adj_tx = tx - g_dx
            adj_ty = ty - g_dy
            for child in el:
                ctag = (child.tag.split("}")[-1]
                        if "}" in child.tag else child.tag)
                if ctag == "rect":
                    r = _parse_rect(child)
                    if r and _rect_overlaps(
                            r, adj_tx, adj_ty, tw, th):
                        layer = _classify_element(child, idx)
                        results.append({
                            "type": layer,
                            "element": "rect",
                            "x": r["x"] + g_dx,
                            "y": r["y"] + g_dy,
                            "w": r["w"], "h": r["h"],
                            "fill": r["fill"],
                            "group_offset": [g_dx, g_dy],
                        })
                elif ctag == "polygon":
                    pts_str = child.get("points", "")
                    pts = re.findall(
                        r"([\d.]+),([\d.]+)", pts_str)
                    if pts:
                        xs = [float(p[0]) for p in pts]
                        ys = [float(p[1]) for p in pts]
                        px_min, px_max = min(xs), max(xs)
                        py_min, py_max = min(ys), max(ys)
                        if (px_min < adj_tx + tw
                                and px_max > adj_tx
                                and py_min < adj_ty + th
                                and py_max > adj_ty):
                            layer = _classify_element(
                                child, idx)
                            results.append({
                                "type": layer,
                                "element": "polygon",
                                "bounds": {
                                    "x": px_min + g_dx,
                                    "y": py_min + g_dy,
                                    "w": px_max - px_min,
                                    "h": py_max - py_min,
                                },
                                "group_offset": [g_dx, g_dy],
                            })

    return results


class GetSVGTileElementsTool(BaseTool):
    """Query SVG elements at a specific tile coordinate."""

    name = "get_svg_tile_elements"
    description = (
        "Find all SVG elements (floor fills, wall segments, "
        "shadows, hatching) overlapping a tile at (x, y) from "
        "the most recent map SVG export."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {
                "type": "integer",
                "description": "Tile X coordinate",
            },
            "y": {
                "type": "integer",
                "description": "Tile Y coordinate",
            },
        },
        "required": ["x", "y"],
    }

    def _latest_svg(self) -> Path | None:
        if not self.exports_dir.exists():
            return None
        matches = sorted(
            self.exports_dir.glob("map_*.svg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        x, y = kwargs["x"], kwargs["y"]
        svg_path = self._latest_svg()
        if not svg_path:
            return {"error": "No map SVG export found"}

        elements = _query_tile_elements(svg_path, x, y)

        # Build summary by type
        summary: dict[str, int] = {}
        for el in elements:
            t = el["type"]
            summary[t] = summary.get(t, 0) + 1

        return {
            "tile": {"x": x, "y": y},
            "pixel_bounds": {
                "x": x * CELL, "y": y * CELL,
                "w": CELL, "h": CELL,
            },
            "element_count": len(elements),
            "summary": summary,
            "elements": elements,
        }


class GetSVGRoomWallsTool(BaseTool):
    """Return wall-stroke path elements that overlap a room.

    Reads the game_state export to find the room's tile set,
    then scans the SVG for stroked wall paths whose segments
    fall within the room's bounding pixel area.  Reports each
    path's raw d attribute, whether it is closed (has Z), and
    how many segments fall inside the room.
    """

    name = "get_svg_room_walls"
    description = (
        "Return wall-stroke path elements from the SVG that "
        "overlap a given room's bounding box.  Useful for "
        "diagnosing missing cave wall segments."
    )
    parameters = {
        "type": "object",
        "properties": {
            "room_index": {
                "type": "integer",
                "description": "Room index from the rooms list",
            },
        },
        "required": ["room_index"],
    }

    def _latest_svg(self) -> Path | None:
        if not self.exports_dir.exists():
            return None
        matches = sorted(
            self.exports_dir.glob("map_*.svg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        idx = kwargs["room_index"]
        # Load the room's tile set from game_state
        game_path = self._latest_export("game_state")
        if not game_path or not game_path.exists():
            return {"error": "No game_state export found"}
        import json as _json
        game = _json.loads(game_path.read_text())
        rooms = game.get("level", {}).get("rooms", [])
        if idx < 0 or idx >= len(rooms):
            return {
                "error": f"Room index {idx} out of range "
                         f"(0-{len(rooms) - 1})",
            }
        room = rooms[idx]
        shape = room.get("shape", "rect")
        rect = room.get("rect", {})
        rx, ry = rect.get("x", 0), rect.get("y", 0)
        rw, rh = rect.get("width", 0), rect.get("height", 0)

        # Build pixel bounding box (expand by 1 tile for margin)
        px_min = (rx - 1) * CELL
        py_min = (ry - 1) * CELL
        px_max = (rx + rw + 1) * CELL
        py_max = (ry + rh + 1) * CELL

        svg_path = self._latest_svg()
        if not svg_path:
            return {"error": "No SVG export found"}

        svg_text = svg_path.read_text()
        # Find all wall-stroke paths (stroke-width >= 3)
        path_re = re.compile(
            r'<path\s+d="([^"]+)"[^>]*stroke-width="([\d.]+)"',
            re.DOTALL,
        )
        walls = []
        for m in path_re.finditer(svg_text):
            d = m.group(1)
            sw = float(m.group(2))
            if sw < 3.0:
                continue
            segs = _parse_path_segments(d)
            if not segs:
                continue
            # Count segments overlapping the room bounding box
            overlapping = 0
            for s in segs:
                if _segment_overlaps_tile(
                    *s, px_min, py_min,
                    px_max - px_min, py_max - py_min,
                ):
                    overlapping += 1
            if overlapping == 0:
                continue
            walls.append({
                "d": d if len(d) < 500 else d[:500] + "...",
                "d_full_length": len(d),
                "stroke_width": sw,
                "closed": "Z" in d,
                "segment_count": len(segs),
                "segments_in_room": overlapping,
                "subpath_count": d.count("M"),
            })

        return {
            "room_index": idx,
            "shape": shape,
            "rect": rect,
            "bbox_px": {
                "x": px_min, "y": py_min,
                "w": px_max - px_min, "h": py_max - py_min,
            },
            "wall_count": len(walls),
            "walls": walls,
        }
