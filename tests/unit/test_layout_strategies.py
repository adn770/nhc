"""Tests for BSP layout strategies."""

import random

from nhc.dungeon.generators._layout import (
    LAYOUT_STRATEGIES,
    plan_default,
    plan_linear,
    plan_radial,
)
from nhc.dungeon.model import Rect


def _sample_rects() -> list[Rect]:
    """5 rooms in a rough grid for testing."""
    return [
        Rect(5, 5, 6, 6),     # center-ish
        Rect(20, 5, 5, 5),    # right
        Rect(5, 20, 5, 5),    # bottom-left
        Rect(20, 20, 5, 5),   # bottom-right
        Rect(35, 10, 5, 5),   # far right
    ]


class TestLayoutRegistry:
    def test_all_strategies_registered(self):
        assert "default" in LAYOUT_STRATEGIES
        assert "radial" in LAYOUT_STRATEGIES
        assert "linear" in LAYOUT_STRATEGIES


class TestPlanDefault:
    def test_returns_pairs_and_indices(self):
        rects = _sample_rects()
        pairs, entrance, exit_idx = plan_default(rects, 0.8, random.Random(42))
        assert len(pairs) > 0
        assert 0 <= entrance < len(rects)
        assert 0 <= exit_idx < len(rects)

    def test_all_rooms_reachable(self):
        rects = _sample_rects()
        pairs, entrance, _ = plan_default(rects, 0.8, random.Random(42))
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for a, b in pairs:
            adj[a].add(b)
            adj[b].add(a)
        visited = set()
        stack = [entrance]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj[n])
        assert visited == set(range(len(rects)))


class TestPlanRadial:
    def test_hub_connects_to_all(self):
        rects = _sample_rects()
        pairs, entrance, exit_idx = plan_radial(rects, 0.8, random.Random(42))
        # entrance is the hub in radial
        hub = entrance
        hub_connections = {b for a, b in pairs if a == hub} | \
                          {a for a, b in pairs if b == hub}
        non_hub = set(range(len(rects))) - {hub}
        assert hub_connections >= non_hub

    def test_all_rooms_reachable(self):
        rects = _sample_rects()
        pairs, entrance, _ = plan_radial(rects, 0.8, random.Random(42))
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for a, b in pairs:
            adj[a].add(b)
            adj[b].add(a)
        visited = set()
        stack = [entrance]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj[n])
        assert visited == set(range(len(rects)))

    def test_exit_is_farthest_from_hub(self):
        rects = _sample_rects()
        _, entrance, exit_idx = plan_radial(rects, 0.8, random.Random(42))
        hub = entrance
        from nhc.dungeon.generators._connectivity import _center_dist
        exit_dist = _center_dist(rects[hub], rects[exit_idx])
        for i in range(len(rects)):
            if i == hub:
                continue
            assert _center_dist(rects[hub], rects[i]) <= exit_dist


class TestPlanLinear:
    def test_all_rooms_reachable(self):
        rects = _sample_rects()
        pairs, entrance, _ = plan_linear(rects, 0.8, random.Random(42))
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for a, b in pairs:
            adj[a].add(b)
            adj[b].add(a)
        visited = set()
        stack = [entrance]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj[n])
        assert visited == set(range(len(rects)))

    def test_trunk_is_chain(self):
        """Linear layout produces at least n-1 pairs (chain)."""
        rects = _sample_rects()
        pairs, _, _ = plan_linear(rects, 0.0, random.Random(42))
        # With connectivity=0 no extra branches
        assert len(pairs) == len(rects) - 1

    def test_entrance_and_exit_at_ends(self):
        rects = _sample_rects()
        pairs, entrance, exit_idx = plan_linear(
            rects, 0.0, random.Random(42),
        )
        assert entrance != exit_idx


class TestPipelineWithLayout:
    def test_tower_generates_with_radial(self):
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.pipeline import generate_level

        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:radial",
        )
        level = generate_level(params)
        assert len(level.rooms) >= 3

    def test_mine_generates_with_linear(self):
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.pipeline import generate_level

        params = GenerationParams(
            width=80, height=40, depth=1, seed=42,
            template="procedural:mine",
        )
        level = generate_level(params)
        assert len(level.rooms) >= 3
