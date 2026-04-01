"""Tests for shape_variety integration into Game and config."""

from __future__ import annotations

from nhc.core.game import Game


class _DummyClient:
    """Minimal GameClient stub."""
    async def send_state(self, *a, **kw): pass
    async def send_message(self, *a, **kw): pass
    async def get_input(self, *a, **kw): return None


class TestShapeVarietyConfig:
    """shape_variety flows from Game to GenerationParams."""

    def test_default_shape_variety(self) -> None:
        game = Game(client=_DummyClient())
        assert game.shape_variety == 0.3

    def test_custom_shape_variety(self) -> None:
        game = Game(client=_DummyClient(), shape_variety=0.6)
        assert game.shape_variety == 0.6

    def test_zero_disables_shapes(self) -> None:
        game = Game(client=_DummyClient(), shape_variety=0.0)
        assert game.shape_variety == 0.0


class TestShapeVarietyDepthScaling:
    """shape_variety increases with depth."""

    def test_depth_1_uses_base(self) -> None:
        from nhc.core.game import _shape_variety_for_depth
        assert _shape_variety_for_depth(0.3, depth=1) == 0.3

    def test_deeper_floors_increase(self) -> None:
        from nhc.core.game import _shape_variety_for_depth
        base = 0.3
        d1 = _shape_variety_for_depth(base, depth=1)
        d5 = _shape_variety_for_depth(base, depth=5)
        assert d5 > d1

    def test_capped_at_0_8(self) -> None:
        from nhc.core.game import _shape_variety_for_depth
        result = _shape_variety_for_depth(0.7, depth=20)
        assert result <= 0.8

    def test_zero_base_stays_zero(self) -> None:
        from nhc.core.game import _shape_variety_for_depth
        assert _shape_variety_for_depth(0.0, depth=10) == 0.0
