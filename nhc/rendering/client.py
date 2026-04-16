"""Abstract game client interface.

Defines the contract between the game engine and any rendering/input
frontend. Both the terminal renderer and the web client implement
this interface.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level
    from nhc.hexcrawl.coords import HexCoord
    from nhc.hexcrawl.model import HexWorld


class GameClient(abc.ABC):
    """Abstract base class for game frontends."""

    game_mode: str
    messages: list[str]
    edge_doors: bool  # True = doors on tile edges (web), False = center (terminal)

    # ── Lifecycle ────────────────────────────────────────────────

    @abc.abstractmethod
    def initialize(self) -> None:
        """Set up the frontend (enter fullscreen, open connection, etc.)."""

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Tear down the frontend."""

    # ── Display ──────────────────────────────────────────────────

    @abc.abstractmethod
    def add_message(self, text: str) -> None:
        """Append a message to the game log."""

    @abc.abstractmethod
    def render(
        self,
        world: "World",
        level: "Level",
        player_id: int,
        turn: int,
    ) -> None:
        """Render the full game state (dungeon mode)."""

    def render_hex(
        self,
        hex_world: "HexWorld",
        player_coord: "HexCoord",
        turn: int,
    ) -> None:
        """Render the overland state (hex mode).

        Default implementation is a no-op so existing clients (the
        terminal renderer until M-3) don't have to implement the
        method on day one. The web client overrides this.
        """
        return None

    @abc.abstractmethod
    def scroll_messages(self, direction: int) -> None:
        """Scroll the message log. +1 = older, -1 = newer."""

    @abc.abstractmethod
    def show_help(self) -> None:
        """Display the help screen."""

    @abc.abstractmethod
    def show_end_screen(
        self, won: bool, turn: int, killed_by: str = "",
    ) -> None:
        """Display the game over or victory screen."""

    # ── Input ────────────────────────────────────────────────────

    @abc.abstractmethod
    async def get_input(self) -> tuple[str, Any]:
        """Wait for player input. Returns (intent, data)."""

    @abc.abstractmethod
    async def get_typed_input(
        self,
        world: "World",
        level: "Level",
        player_id: int,
        turn: int,
    ) -> str | tuple[str, Any]:
        """Run typed input mode. Returns typed text or (intent, data)."""

    # ── Menus ────────────────────────────────────────────────────

    @abc.abstractmethod
    def show_inventory_menu(
        self, world: "World", player_id: int, prompt: str = "",
    ) -> int | None:
        """Show full inventory and return selected item ID."""

    @abc.abstractmethod
    def show_filtered_inventory(
        self, world: "World", player_id: int,
        title: str,
        filter_component: str | None = None,
    ) -> int | None:
        """Show inventory filtered by component. Returns item ID."""

    @abc.abstractmethod
    def show_ground_menu(
        self, items: list[tuple[int, str]],
    ) -> int | None:
        """Show selection menu for items on the ground."""

    @abc.abstractmethod
    def show_target_menu(
        self, world: "World", level: "Level", player_id: int,
        title: str,
    ) -> int | None:
        """Show list of visible creatures to target. Returns entity ID."""

    @abc.abstractmethod
    def show_selection_menu(
        self, title: str, items: list[tuple[int, str]],
    ) -> int | None:
        """Show a generic selection menu. Returns selected ID."""

    # ── Interactive modes ────────────────────────────────────────

    @abc.abstractmethod
    def farlook_mode(
        self, world: "World", level: "Level", player_id: int,
        turn: int, start_x: int, start_y: int,
        *, god_mode: bool = False,
    ) -> None:
        """Interactive cursor examination of the map."""

    @abc.abstractmethod
    def fullmap_mode(
        self, world: "World", level: "Level", player_id: int,
        turn: int,
    ) -> None:
        """Full map reveal with scrollable viewport (god mode)."""
