"""Tests for guaranteed digging tool placement on early levels."""

from __future__ import annotations

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.pipeline import generate_level

DIGGING_TOOLS = {"pick", "shovel", "pickaxe", "mattock"}


class TestDiggingToolGuarantee:
    """Levels 1-5 must contain at least one digging tool."""

    def test_digging_tool_on_early_levels(self):
        for depth in range(1, 6):
            found = 0
            for seed in range(50):
                level = generate_level(GenerationParams(
                    width=120, height=40, depth=depth, seed=seed,
                ))
                has_tool = any(
                    e.entity_type == "item" and e.entity_id in DIGGING_TOOLS
                    for e in level.entities
                )
                if has_tool:
                    found += 1
            assert found == 50, (
                f"Depth {depth}: only {found}/50 seeds had a digging tool"
            )

    def test_no_guarantee_on_deep_levels(self):
        """Depth 6+ may or may not have tools — no guarantee needed."""
        # Just verify the populator doesn't crash at depth 6
        level = generate_level(GenerationParams(
            width=120, height=40, depth=6, seed=0,
        ))
        assert level is not None
