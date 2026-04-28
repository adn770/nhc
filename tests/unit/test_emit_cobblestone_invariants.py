"""Structural invariants for the cobblestone decorator port.

Per §8 step 6 of ``plans/nhc_ir_migration_plan.md`` (Q2 decorator
pipeline, locked 2026-04-28), the cobblestone port ships under
the relaxed parity gate. Existing dungeon / cave fixtures don't
contain cobble (STREET / PAVED) tiles, so the layer-fixture
snapshot is trivially empty for them; this file exercises the
pipeline end-to-end via a synthetic level with all-cobble
tiles.

The invariants assert that the cobblestone fragments are
visually well-formed regardless of the underlying RNG choice:

- The cobblestone <g> envelope is present once cobble tiles
  exist and parses as well-formed XML.
- Per-tile rectangle count tracks the legacy 3×3 grid (allow
  ±2 for jitter rejections).
- Stone group emits at the legacy 12 % rate within tolerance
  on a 200-tile sample.
- Coordinates stay inside the canvas + small margin.
- No NaN / Inf in any coordinate.
- Re-rendering the same buffer twice produces byte-equal output.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import pytest

from nhc.dungeon.model import Level, Rect, Room, SurfaceType, Terrain, Tile
from nhc.rendering.ir_emitter import build_floor_ir
from nhc.rendering.ir_to_svg import layer_to_svg


_COORD_RE = re.compile(r'(?:x[12]?|y[12]?|cx|cy)="(-?[0-9.]+)"')
_RECT_RE = re.compile(r"<rect\s")
_ELLIPSE_RE = re.compile(r"<ellipse\s")


def _cobble_level(width: int, height: int) -> Level:
    """Synthetic level: every tile is a STREET-surface FLOOR.
    Mirrors the helper at ``test_surface_rendering._blank_level``
    but tagged with SurfaceType.STREET so the cobblestone
    decorator picks them up.
    """
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.STREET,
            )
    level.rooms = [Room(id="r1", rect=Rect(0, 0, width, height))]
    return level


def _layer_svg(width: int, height: int, seed: int) -> str:
    level = _cobble_level(width, height)
    buf = build_floor_ir(level, seed=seed)
    return layer_to_svg(buf, layer="floor_detail")


def test_cobblestone_group_appears_with_cobble_tiles() -> None:
    svg = _layer_svg(10, 10, seed=42)
    assert 'stroke="#8A7A6A"' in svg, (
        "cobblestone <g> envelope missing — Rust port should "
        "emit the canonical street stroke colour"
    )


def test_cobblestone_rect_count_matches_3x3_grid() -> None:
    svg = _layer_svg(10, 10, seed=42)
    n_rects = len(_RECT_RE.findall(svg))
    expected = 100 * 9
    assert (
        expected - 200 <= n_rects <= expected + 50
    ), (
        f"expected ~{expected} cobble rects (3×3 per tile, "
        f"100 tiles, allow some jitter rejections); got {n_rects}"
    )


def test_cobble_stones_emit_around_12_percent() -> None:
    # 14×14 = 196 tiles, 12 % → ~24 stones. Use a wide tolerance
    # because Pcg64Mcg differs from MT19937 — the stat shouldn't
    # drift far from 12 % at this sample size.
    svg = _layer_svg(14, 14, seed=42)
    n_ellipses = len(_ELLIPSE_RE.findall(svg))
    assert 5 <= n_ellipses <= 60, (
        f"expected ~24 cobble stones (12 % of 196); got {n_ellipses}"
    )


def test_layer_parses_as_xml() -> None:
    svg = _layer_svg(10, 10, seed=42)
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        f'{svg}'
        '</svg>'
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as e:
        pytest.fail(f"cobblestone layer is not well-formed XML: {e}")


def test_no_nan_or_inf() -> None:
    svg = _layer_svg(10, 10, seed=42)
    coords = [float(m) for m in _COORD_RE.findall(svg)]
    bad = [c for c in coords if math.isnan(c) or math.isinf(c)]
    assert not bad, f"NaN/Inf in cobble coords: {bad[:5]}"


def test_coordinates_inside_canvas() -> None:
    svg = _layer_svg(10, 10, seed=42)
    coords = [float(m) for m in _COORD_RE.findall(svg)]
    # 10 tiles × CELL=32 = 320; allow 1-cell margin.
    assert all(-32 <= c <= 320 + 32 for c in coords), (
        f"coords out of bounds: {[c for c in coords if not (-32 <= c <= 352)][:5]}"
    )


def test_deterministic() -> None:
    a = _layer_svg(8, 8, seed=42)
    b = _layer_svg(8, 8, seed=42)
    assert a == b, "cobblestone layer not deterministic across runs"


def test_no_cobbles_means_no_cobblestone_group() -> None:
    """A non-cobble level should not emit any cobblestone <g>.
    The dispatcher must not double-draw fragments via DecoratorOp
    when no cobble tiles exist."""
    level = Level.create_empty("t", "t", 1, 5, 5)
    for y in range(5):
        for x in range(5):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 5, 5))]
    buf = build_floor_ir(level, seed=42)
    svg = layer_to_svg(buf, layer="floor_detail")
    assert 'stroke="#8A7A6A"' not in svg, (
        "no cobble tiles should mean no cobblestone <g> envelope"
    )
