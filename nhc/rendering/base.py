"""Abstract renderer protocol.

All rendering backends (terminal, graphical) implement this interface.
The game engine depends only on this protocol, never on concrete renderers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from nhc.core.ecs import World


@dataclass
class InputEvent:
    """Raw input from the user."""
    key: str = ""
    modifiers: set[str] = field(default_factory=set)


@dataclass
class Camera:
    """Viewport configuration."""
    center_x: int = 0
    center_y: int = 0
    viewport_width: int = 80
    viewport_height: int = 24


class Renderer(Protocol):
    """Interface that all rendering backends must implement."""

    def initialize(self) -> None:
        """Set up the rendering surface."""
        ...

    def shutdown(self) -> None:
        """Clean up rendering resources."""
        ...

    def render_world(self, world: World, camera: Camera) -> None:
        """Draw the dungeon and all visible entities."""
        ...

    def render_ui(self, ui_state: dict[str, Any]) -> None:
        """Draw HUD elements: stats, inventory, etc."""
        ...

    def show_message(self, text: str, style: str = "normal") -> None:
        """Display a message in the message log."""
        ...

    async def get_input(self) -> InputEvent:
        """Wait for and return the next input event."""
        ...

    def show_menu(self, title: str, options: list[str]) -> int:
        """Display a menu and return the selected index."""
        ...
