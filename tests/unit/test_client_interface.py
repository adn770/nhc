"""Tests for the GameClient abstract interface."""

import inspect

import pytest

from nhc.rendering.client import GameClient
from nhc.rendering.terminal.renderer import TerminalRenderer


class TestGameClientInterface:
    """Verify the abstract interface is complete and implemented."""

    def test_game_client_is_abstract(self):
        """GameClient cannot be instantiated directly."""
        with pytest.raises(TypeError):
            GameClient()

    def test_terminal_renderer_inherits_game_client(self):
        """TerminalRenderer must be a subclass of GameClient."""
        assert issubclass(TerminalRenderer, GameClient)

    def test_all_abstract_methods_implemented(self):
        """TerminalRenderer implements every abstract method."""
        abstract = {
            name for name, _ in inspect.getmembers(
                GameClient, predicate=inspect.isfunction,
            )
            if getattr(
                getattr(GameClient, name, None), "__isabstractmethod__", False,
            )
        }
        assert abstract, "GameClient should have abstract methods"
        for method_name in abstract:
            impl = getattr(TerminalRenderer, method_name, None)
            assert impl is not None, (
                f"TerminalRenderer missing method: {method_name}"
            )
            assert not getattr(impl, "__isabstractmethod__", False), (
                f"TerminalRenderer.{method_name} is still abstract"
            )

    def test_show_selection_menu_exists(self):
        """show_selection_menu (renamed from _draw_selection_menu)."""
        assert hasattr(TerminalRenderer, "show_selection_menu")
