"""Death and resurrection handling.

Extracted from Game to keep the god-object under control.
Manages permadeath vs cheat-death decisions and the respawn
penalty logic for both hex and dungeon modes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.hexcrawl.mode import WorldType
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.game import Game


class DeathHandler:
    """Handles player death, cheat-death dialog, and respawn."""

    def __init__(self, game: Game) -> None:
        self.game = game

    def handle_player_death(self) -> bool:
        """Decide what happens when the player's HP hits 0.

        On an ``easy`` difficulty game (any world type) shows a
        Permadeath / Cheat-Death selection menu via
        :meth:`renderer.show_selection_menu`. On a cheat-death
        pick, applies :meth:`cheat_death` and returns ``True``
        so the game loop resumes. Any other pick (or any other
        difficulty) returns ``False``, letting the loop proceed
        with the classic end-screen path.

        A renderer that lacks ``show_selection_menu`` (or returns
        ``None``) defaults to permadeath so a headless / scripted
        flow doesn't hang waiting on a prompt.
        """
        if not self.allows_cheat_death_now():
            return False
        prompt = getattr(
            self.game.renderer, "show_selection_menu", None,
        )
        if prompt is None:
            return False
        options: list[tuple[int, str]] = [
            (0, t("death.permadeath")),
            (1, t("death.cheat_death")),
        ]
        choice = prompt(t("death.prompt"), options)
        if choice != 1:
            return False
        try:
            if self.game.world_type is WorldType.HEXCRAWL:
                self.cheat_death()
            else:
                self.cheat_death_dungeon()
        except RuntimeError:
            # Mode-gate tripped; treat as permadeath.
            return False
        return True

    def allows_cheat_death_now(self) -> bool:
        """True when the current world mode offers the cheat-death
        dialog on player death (easy difficulty in any world)."""
        return self.game.difficulty.allows_cheat_death

    def cheat_death(self) -> None:
        """Respawn the player at the last hub with penalties.

        Only valid in an easy-difficulty hexcrawl game. Resets the player's
        gold to 0, strips their carried inventory (items destroyed),
        disbands the expedition party (henchmen destroyed),
        teleports the player to ``hex_world.last_hub``, advances the
        day clock by one full day (same time-of-day), and restores
        HP to maximum. World state (revealed / visited / cleared /
        looted sets) is preserved so the player's prior progress
        still counts.

        Raises :class:`RuntimeError` when called in a mode that does
        not permit it.
        """
        if not self.allows_cheat_death_now():
            raise RuntimeError(
                f"cheat_death is only available in HEX_EASY; "
                f"current world={self.game.world_type.value}, difficulty={self.game.difficulty.value}"
            )
        assert self.game.hex_world is not None
        assert self.game.hex_world.last_hub is not None

        world = self.game.world

        # Gold -> 0.
        player = world.get_component(self.game.player_id, "Player")
        if player is not None:
            player.gold = 0

        # Strip inventory items (destroyed).
        inv = world.get_component(self.game.player_id, "Inventory")
        if inv is not None:
            for iid in list(inv.slots):
                if iid in world._entities:
                    world.destroy_entity(iid)
            inv.slots.clear()

        # Disband expedition party.
        for henchman in list(self.game.hex_world.expedition_party):
            if henchman in world._entities:
                world.destroy_entity(henchman)
        self.game.hex_world.expedition_party.clear()

        # Teleport + HP reset.
        self.game.hex_player_position = self.game.hex_world.last_hub
        health = world.get_component(self.game.player_id, "Health")
        if health is not None:
            health.current = health.maximum

        # Clock: +1 full day, same time-of-day segment.
        self.game.hex_world.advance_clock(4)

    def cheat_death_dungeon(self) -> None:
        """Respawn the player in place with penalties (dungeon mode).

        Only valid on easy difficulty (where
        :meth:`Difficulty.allows_cheat_death` is True). Resets gold
        to 0, strips inventory, and restores HP
        to maximum. Dungeon state is preserved — cleared rooms stay
        cleared.
        """
        if not self.game.difficulty.allows_cheat_death:
            raise RuntimeError(
                f"cheat_death_dungeon requires easy difficulty; "
                f"current world={self.game.world_type.value}, difficulty={self.game.difficulty.value}"
            )

        world = self.game.world

        # Gold -> 0.
        player = world.get_component(self.game.player_id, "Player")
        if player is not None:
            player.gold = 0

        # Strip inventory items (destroyed).
        inv = world.get_component(self.game.player_id, "Inventory")
        if inv is not None:
            for iid in list(inv.slots):
                if iid in world._entities:
                    world.destroy_entity(iid)
            inv.slots.clear()

        # HP to max.
        health = world.get_component(self.game.player_id, "Health")
        if health is not None:
            health.current = health.maximum
