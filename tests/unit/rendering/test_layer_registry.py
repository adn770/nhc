"""Tests for the floor renderer's Layer registry.

Phase 5 of the rendering refactor. Verifies the static shape of
:data:`FLOOR_LAYERS` and the behaviour of the orchestrator helper.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.rendering._floor_layers import FLOOR_LAYERS
from nhc.rendering._pipeline import (
    Layer, TileWalkLayer, render_layers,
)
from nhc.rendering._render_context import build_render_context


class TestRegistryShape:
    def test_orders_are_strictly_increasing(self) -> None:
        orders = [layer.order for layer in FLOOR_LAYERS]
        assert orders == sorted(orders), (
            f"FLOOR_LAYERS not sorted by order: {orders}"
        )
        assert len(orders) == len(set(orders)), (
            f"FLOOR_LAYERS has duplicate orders: {orders}"
        )

    def test_all_names_unique(self) -> None:
        names = [layer.name for layer in FLOOR_LAYERS]
        assert len(names) == len(set(names))

    def test_every_layer_has_paint_callable(self) -> None:
        for layer in FLOOR_LAYERS:
            assert callable(layer.paint)

    def test_every_layer_has_is_active_callable(self) -> None:
        for layer in FLOOR_LAYERS:
            assert callable(layer.is_active)

    def test_expected_layer_names_present(self) -> None:
        names = {layer.name for layer in FLOOR_LAYERS}
        assert {
            "shadows", "hatching", "walls_and_floors",
            "terrain_tints", "floor_grid", "floor_detail",
            "terrain_detail", "stairs", "surface_features",
        } <= names

    def test_surface_features_is_a_tile_walk_layer(self) -> None:
        sf = next(
            layer for layer in FLOOR_LAYERS
            if layer.name == "surface_features"
        )
        assert isinstance(sf, TileWalkLayer)
        # 5 decorators today: well, well_square, fountain,
        # fountain_square, tree.
        assert len(sf.decorators) >= 5


class TestRenderLayersOrchestrator:
    def _ctx(self):
        level = Level.create_empty("L", "L", 0, 3, 3)
        for y in range(3):
            for x in range(3):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        return build_render_context(level, seed=0)

    def test_inactive_layer_emits_nothing(self) -> None:
        emitted: list[str] = []

        layer = Layer(
            name="never",
            order=10,
            is_active=lambda ctx: False,
            paint=lambda ctx: ["<should-not-emit/>"],
        )

        out = render_layers(self._ctx(), [layer])
        assert out == []

    def test_active_layer_emits_paint_output(self) -> None:
        layer = Layer(
            name="always",
            order=10,
            is_active=lambda ctx: True,
            paint=lambda ctx: ["<one/>", "<two/>"],
        )
        assert render_layers(self._ctx(), [layer]) == [
            "<one/>", "<two/>",
        ]

    def test_layers_emit_in_order(self) -> None:
        a = Layer(
            name="a", order=20, is_active=lambda ctx: True,
            paint=lambda ctx: ["<a/>"],
        )
        b = Layer(
            name="b", order=10, is_active=lambda ctx: True,
            paint=lambda ctx: ["<b/>"],
        )
        # Pass in registration order; render_layers sorts.
        assert render_layers(self._ctx(), [a, b]) == ["<b/>", "<a/>"]
