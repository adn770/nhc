"""Tests for nhc.tables.effects — effect handler registry."""

import pytest

from nhc.tables.types import TableEffect


class TestEffects:

    def test_reveal_hex_handler_mutates_fog(self):
        from nhc.tables.effects import apply_effect

        revealed = []

        class FakeWorld:
            def reveal(self, coord):
                revealed.append(coord)

        world = FakeWorld()
        effect = TableEffect(
            kind="reveal_hex",
            payload={"q": 5, "r": 3},
        )
        apply_effect(effect, world=world)
        assert revealed == [(5, 3)]

    def test_reveal_hex_handler_uses_context_source(self):
        from nhc.tables.effects import apply_effect

        revealed = []

        class FakeWorld:
            def reveal(self, coord):
                revealed.append(coord)

        world = FakeWorld()
        effect = TableEffect(
            kind="reveal_hex",
            payload={"source": "context"},
        )
        apply_effect(effect, world=world, q=7, r=2)
        assert revealed == [(7, 2)]

    def test_custom_handler_registers_and_fires(self):
        from nhc.tables.effects import apply_effect, register_effect_handler

        calls = []

        @register_effect_handler("test_custom")
        def handle_custom(payload, **ctx):
            calls.append((payload, ctx))

        effect = TableEffect(kind="test_custom", payload={"foo": "bar"})
        apply_effect(effect, some_key="val")
        assert len(calls) == 1
        assert calls[0][0] == {"foo": "bar"}
        assert calls[0][1]["some_key"] == "val"

    def test_unknown_effect_kind_raises_unknown_effect_error(self):
        from nhc.tables.effects import UnknownEffectError, apply_effect

        effect = TableEffect(kind="nonexistent", payload={})
        with pytest.raises(UnknownEffectError, match="nonexistent"):
            apply_effect(effect)

    def test_entry_without_effect_returns_none(self):
        from nhc.tables.effects import apply_effect

        result = apply_effect(None)
        assert result is None
