"""Tests for the floor renderer's Layer registry.

Phase 5 of the rendering refactor. Verifies the static shape of
:data:`FLOOR_LAYERS` and the behaviour of the orchestrator helper.
"""

from __future__ import annotations

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.rendering._floor_layers import FLOOR_LAYERS
from nhc.rendering._pipeline import Layer, render_layers
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
            "terrain_tints", "floor_grid",
            "terrain_detail", "stairs",
        } <= names


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
        out = render_layers(self._ctx(), [layer])
        # Each active layer is prefixed by a stats comment so a
        # rendered SVG is self-describing for size analysis.
        assert out[0].startswith("<!-- layer.always:")
        assert out[1:] == ["<one/>", "<two/>"]

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
        out = render_layers(self._ctx(), [a, b])
        # Strip the per-layer stats comments to check ordering.
        non_comments = [s for s in out if not s.startswith("<!--")]
        assert non_comments == ["<b/>", "<a/>"]


class TestRenderLayersInstrumentation:
    """Per-layer size + element-count instrumentation.

    The annotation comments and the matching DEBUG log line let
    us profile the rendered SVG without re-instrumenting the
    pipeline -- e.g. trace down the layer responsible for the
    multi-MB town surface output.
    """

    def _ctx(self):
        level = Level.create_empty("L", "L", 0, 3, 3)
        for y in range(3):
            for x in range(3):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        return build_render_context(level, seed=0)

    def test_stats_comment_carries_byte_size_and_element_count(
        self,
    ) -> None:
        layer = Layer(
            name="probe",
            order=10,
            is_active=lambda ctx: True,
            paint=lambda ctx: [
                '<rect x="0" y="0"/>',
                '<g><circle/><line/></g>',
            ],
        )
        out = render_layers(self._ctx(), [layer])
        assert out[0].startswith("<!-- layer.probe:")
        # 4 opening tags: rect, g, circle, line. Bytes = 39.
        joined = "".join(out[1:])
        assert "4 elements" in out[0]
        assert f"{len(joined)} bytes" in out[0]

    def test_inactive_layer_emits_no_stats_comment(self) -> None:
        layer = Layer(
            name="off",
            order=10,
            is_active=lambda ctx: False,
            paint=lambda ctx: ["<x/>"],
        )
        assert render_layers(self._ctx(), [layer]) == []

    def test_render_layers_logs_per_layer_breakdown(
        self, caplog,
    ) -> None:
        import logging
        a = Layer(
            name="a", order=10, is_active=lambda ctx: True,
            paint=lambda ctx: ['<rect/>'],
        )
        b = Layer(
            name="b", order=20, is_active=lambda ctx: True,
            paint=lambda ctx: ['<g/>', '<g/>'],
        )
        with caplog.at_level(
            logging.DEBUG, logger="nhc.rendering._pipeline",
        ):
            render_layers(self._ctx(), [a, b])
        msgs = [r.getMessage() for r in caplog.records]
        # Single summary line carrying every layer's name + bytes.
        summary = next(
            (m for m in msgs if "render_layers" in m),
            None,
        )
        assert summary is not None, msgs
        assert "a=" in summary and "b=" in summary
        assert "total=" in summary
