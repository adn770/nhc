"""Tests for new MCP diagnostic tools used to debug map rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhc.debug_tools.tools.dungeon import GetRoomTilesTool
from nhc.debug_tools.tools.svg_query import GetSVGRoomWallsTool


@pytest.fixture()
def tmp_exports(tmp_path, monkeypatch):
    """Create a tmp exports dir and point the tools at it."""
    exp_dir = tmp_path / "debug" / "exports"
    exp_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return exp_dir


def _make_game_state(exports: Path) -> None:
    """Write a minimal game_state with a cave room."""
    data = {
        "timestamp": "2026-04-04T15:00:00",
        "turn": 0,
        "level": {
            "id": "test", "name": "Test",
            "depth": 1, "width": 20, "height": 15,
            "tiles": [
                [{"terrain": "VOID"} for _ in range(20)]
                for _ in range(15)
            ],
            "rooms": [
                {
                    "id": "cave_1",
                    "rect": {"x": 5, "y": 5, "width": 3, "height": 2},
                    "tags": [],
                    "description": "",
                    "connections": [],
                    "shape": "cave",
                    "tiles": [
                        [5, 5], [6, 5], [7, 5],
                        [5, 6], [6, 6],
                    ],
                },
                {
                    "id": "rect_1",
                    "rect": {"x": 10, "y": 3, "width": 4, "height": 3},
                    "tags": [],
                    "description": "",
                    "connections": [],
                },
            ],
            "corridors": [],
            "metadata": {
                "theme": "cave", "difficulty": 1,
                "narrative_hooks": [], "faction": None,
                "ambient": "",
            },
        },
    }
    (exports / "game_state_20260404.json").write_text(
        json.dumps(data)
    )


def _make_svg(exports: Path) -> None:
    """Write a minimal SVG with cave wall bezier paths."""
    svg = """<svg>
<g transform="translate(32,32)">
<path d="M160,160 C170,155 180,155 192,160 C200,165 210,165 224,160"
      fill="none" stroke="#000000" stroke-width="4.0"/>
<path d="M320,96 L448,96 L448,192 L320,192 Z"
      fill="none" stroke="#000000" stroke-width="4.0"/>
</g>
</svg>"""
    (exports / "map_20260404_d1.svg").write_text(svg)


class TestGetRoomTilesTool:
    @pytest.mark.asyncio
    async def test_cave_room_returns_tile_set(self, tmp_exports):
        _make_game_state(tmp_exports)
        tool = GetRoomTilesTool()
        result = await tool.execute(room_index=0)
        assert "tiles" in result
        assert result["shape"] == "cave"
        tiles = {tuple(t) for t in result["tiles"]}
        assert tiles == {
            (5, 5), (6, 5), (7, 5), (5, 6), (6, 6),
        }
        assert result["tile_count"] == 5

    @pytest.mark.asyncio
    async def test_rect_room_derives_tiles_from_rect(
        self, tmp_exports,
    ):
        _make_game_state(tmp_exports)
        tool = GetRoomTilesTool()
        result = await tool.execute(room_index=1)
        assert result["shape"] == "rect"
        tiles = {tuple(t) for t in result["tiles"]}
        # 4x3 rect at (10, 3)
        expected = {
            (x, y) for x in range(10, 14) for y in range(3, 6)
        }
        assert tiles == expected

    @pytest.mark.asyncio
    async def test_invalid_room_index(self, tmp_exports):
        _make_game_state(tmp_exports)
        tool = GetRoomTilesTool()
        result = await tool.execute(room_index=99)
        assert "error" in result


class TestGetSVGRoomWallsTool:
    @pytest.mark.asyncio
    async def test_finds_cave_wall_paths(self, tmp_exports):
        _make_game_state(tmp_exports)
        _make_svg(tmp_exports)
        tool = GetSVGRoomWallsTool()
        result = await tool.execute(room_index=0)
        assert "walls" in result
        assert result["wall_count"] >= 1
        # The cave wall path should be identified
        walls = result["walls"]
        # Each wall should have a path string
        assert all("d" in w for w in walls)

    @pytest.mark.asyncio
    async def test_reports_open_vs_closed(self, tmp_exports):
        _make_game_state(tmp_exports)
        _make_svg(tmp_exports)
        tool = GetSVGRoomWallsTool()
        result = await tool.execute(room_index=0)
        # The test SVG has an open cave path and a closed rect path
        walls = result["walls"]
        has_open = any(not w.get("closed") for w in walls)
        assert has_open, "Expected at least one open wall path"
