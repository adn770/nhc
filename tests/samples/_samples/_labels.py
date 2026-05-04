"""Debug-label overlay for sample SVGs.

Opt-in via the ``--labels`` CLI flag. Reads metadata from the
source :class:`Level` (and optional :class:`Site`) and appends an
SVG ``<g>`` group of labels to the rendered output:

* **Room labels** — text at each room's centroid showing
  ``room.id`` (e.g. ``"room.1"``) plus the shape type.
* **Door labels** — small marker rect + ``D{idx}`` numbering on
  each tile whose ``feature`` is one of the door variants.
* **Corridor labels** — text at each corridor segment's first
  point showing ``corridor.id``.

The overlay sits inside a transform group that mirrors the
rendered body's ``translate(padding) scale(scale)`` envelope, so
label coordinates use raw IR pixel space (tile coord × CELL).

PNG output is always raw — labels appear in the SVG only.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


CELL = 32  # pixels per tile (matches ``nhc.rendering.svg.CELL``).


# Door feature names that should pick up a "D{idx}" marker.
DOOR_FEATURES: tuple[str, ...] = (
    "door_closed", "door_open", "door_locked", "door_secret",
)

DOOR_MARKER_FILL = "#1565C0"
DOOR_MARKER_FG = "#FFFFFF"
ROOM_LABEL_FILL = "#1B5E20"
ROOM_LABEL_BG = "rgba(255,255,240,0.85)"
CORRIDOR_LABEL_FILL = "#5D4037"
CORRIDOR_LABEL_BG = "rgba(255,250,235,0.85)"


def inject_labels(
    svg: str, level: Any, *, site: Any | None = None,
) -> str:
    """Insert a debug-label ``<g>`` group into ``svg``.

    The group is inserted right before the closing ``</svg>`` tag
    and wrapped in a ``<g transform="translate(...) scale(...)">``
    that mirrors the renderer's outer transform so label coords
    can use raw IR pixel space.

    When ``site`` is provided, building floor labels are skipped
    here (the caller renders site surfaces; per-building floor
    labels would need a multi-level overlay tool).
    """
    transform = _extract_outer_transform(svg)
    if transform is None:
        return svg  # No outer transform group — bail rather than guess.

    parts: list[str] = []
    parts.append(f'<g class="debug-labels" transform="{transform}" '
                 f'font-family="monospace" font-size="10">')
    parts.append(_render_room_labels(level))
    parts.append(_render_door_labels(level))
    parts.append(_render_corridor_labels(level))
    parts.append("</g>")
    overlay = "".join(parts)

    return svg.replace("</svg>", overlay + "</svg>", 1)


# ── Helpers ────────────────────────────────────────────────────────


_TRANSFORM_RE = re.compile(
    r'<g\s+transform="(translate\([^)]+\)\s+scale\([^)]+\))"',
)


def _extract_outer_transform(svg: str) -> str | None:
    """Pull the renderer's outer ``translate(...) scale(...)``
    transform from the first ``<g transform="…">`` envelope so
    the label group can mirror it."""
    m = _TRANSFORM_RE.search(svg)
    return m.group(1) if m else None


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _render_room_labels(level: Any) -> str:
    rooms = getattr(level, "rooms", None) or []
    out: list[str] = []
    for room in rooms:
        rect = getattr(room, "rect", None)
        if rect is None:
            continue
        cx_tile, cy_tile = rect.center
        cx = cx_tile * CELL + CELL // 2
        cy = cy_tile * CELL + CELL // 2
        label = _xml_escape(getattr(room, "id", "?"))
        shape = type(getattr(room, "shape", object())).__name__
        # Two-line label: id over shape type. The background rect
        # sits behind both lines.
        text_w = max(len(label), len(shape)) * 6 + 8
        text_h = 26
        out.append(
            f'<g><rect x="{cx - text_w // 2}" y="{cy - text_h // 2}" '
            f'width="{text_w}" height="{text_h}" '
            f'fill="{ROOM_LABEL_BG}" rx="3" stroke="#888" '
            f'stroke-width="0.5"/>'
            f'<text x="{cx}" y="{cy - 1}" text-anchor="middle" '
            f'fill="{ROOM_LABEL_FILL}" font-weight="bold">'
            f'{label}</text>'
            f'<text x="{cx}" y="{cy + 11}" text-anchor="middle" '
            f'fill="#666">{_xml_escape(shape)}</text></g>'
        )
    return "".join(out)


def _render_door_labels(level: Any) -> str:
    tiles = getattr(level, "tiles", None)
    if not tiles:
        return ""
    out: list[str] = []
    door_idx = 0
    width = getattr(level, "width", 0)
    height = getattr(level, "height", 0)
    for y in range(height):
        for x in range(width):
            try:
                tile = tiles[y][x]
            except IndexError:
                continue
            feature = getattr(tile, "feature", None)
            if feature not in DOOR_FEATURES:
                continue
            # Marker abbreviation per door state.
            short = {
                "door_closed": "C", "door_open": "O",
                "door_locked": "L", "door_secret": "S",
            }[feature]
            px = x * CELL + CELL // 2
            py = y * CELL + CELL // 2
            out.append(
                f'<g><rect x="{px - 8}" y="{py - 8}" width="16" '
                f'height="16" fill="{DOOR_MARKER_FILL}" '
                f'opacity="0.85" rx="2"/>'
                f'<text x="{px}" y="{py + 4}" '
                f'text-anchor="middle" fill="{DOOR_MARKER_FG}" '
                f'font-weight="bold">D{door_idx}{short}</text></g>'
            )
            door_idx += 1
    return "".join(out)


def _render_corridor_labels(level: Any) -> str:
    """Render one label per corridor.

    Corridor placement uses two strategies, in priority order:

    1. ``corridor.points`` — if the generator populated the explicit
       point list, use the centroid of that list.
    2. ``corridor.connects`` — fall back to the midpoint between
       the two connected rooms' centres. The BSP generator stores
       corridors as connectivity records (``connects=[room_a,
       room_b]``) without an explicit point list, so this fallback
       is what yields a meaningful label placement for most
       generator-driven samples.

    Corridors with neither field populated get skipped silently.
    """
    corridors = getattr(level, "corridors", None) or []
    rooms_by_id = {
        getattr(r, "id", None): r
        for r in (getattr(level, "rooms", None) or [])
    }
    out: list[str] = []
    for corridor in corridors:
        cx_t, cy_t = _corridor_centroid(corridor, rooms_by_id)
        if cx_t is None:
            continue
        cx = int(cx_t * CELL) + CELL // 2
        cy = int(cy_t * CELL) + CELL // 2
        label = _xml_escape(getattr(corridor, "id", "?"))
        text_w = len(label) * 6 + 8
        text_h = 14
        out.append(
            f'<g><rect x="{cx - text_w // 2}" y="{cy - text_h // 2}" '
            f'width="{text_w}" height="{text_h}" '
            f'fill="{CORRIDOR_LABEL_BG}" rx="2" stroke="#888" '
            f'stroke-width="0.5"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" '
            f'fill="{CORRIDOR_LABEL_FILL}">{label}</text></g>'
        )
    return "".join(out)


def _corridor_centroid(
    corridor: Any, rooms_by_id: dict[Any, Any],
) -> tuple[float | None, float | None]:
    """Pick a (x_tile, y_tile) anchor for a corridor label."""
    points = getattr(corridor, "points", None) or []
    if points:
        cx, cy = _centroid(points)
        return cx, cy
    connects = getattr(corridor, "connects", None) or []
    if len(connects) < 2:
        return None, None
    centres: list[tuple[float, float]] = []
    for room_id in connects:
        room = rooms_by_id.get(room_id)
        if room is None:
            continue
        rect = getattr(room, "rect", None)
        if rect is None:
            continue
        cx_t, cy_t = rect.center
        centres.append((float(cx_t), float(cy_t)))
    if not centres:
        return None, None
    sx = sum(c[0] for c in centres) / len(centres)
    sy = sum(c[1] for c in centres) / len(centres)
    return sx, sy


def _centroid(points: Iterable[tuple[int, int]]) -> tuple[float, float]:
    pts = list(points)
    if not pts:
        return 0.0, 0.0
    sx = sum(p[0] for p in pts) / len(pts)
    sy = sum(p[1] for p in pts) / len(pts)
    return sx, sy


__all__ = ["inject_labels"]
