"""Game loop and session management."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nhc.ai.behavior import decide_action
from nhc.core.actions import (
    BumpAction,
    DescendStairsAction,
    PickupItemAction,
    UseItemAction,
    WaitAction,
)
from nhc.core.ecs import World
from nhc.core.events import (
    EventBus,
    GameWon,
    MessageEvent,
    PlayerDied,
)
from nhc.dungeon.loader import get_player_start, load_level
from nhc.dungeon.model import Level
from nhc.entities.components import (
    BlocksMovement,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.rendering.terminal.renderer import TerminalRenderer
from nhc.utils.fov import compute_fov

if TYPE_CHECKING:
    from nhc.core.actions import Action
    from nhc.llm import LLMBackend

FOV_RADIUS = 8


class Game:
    """Main game controller. Owns the world, event bus, and loop."""

    def __init__(
        self,
        backend: "LLMBackend | None" = None,
        seed: int | None = None,
    ) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.backend = backend
        self.seed = seed
        self.running = False
        self.game_over = False
        self.won = False
        self.turn = 0
        self.player_id: int = -1
        self.level: Level | None = None
        self.renderer = TerminalRenderer()

    async def initialize(self, level_path: str | Path) -> None:
        """Set up initial game state from a level file."""
        if self.seed is not None:
            from nhc.utils.rng import set_seed
            set_seed(self.seed)

        # Discover all entity types
        EntityRegistry.discover_all()

        # Load level
        self.level = load_level(level_path)
        px, py = get_player_start(level_path)

        # Create player entity
        self.player_id = self.world.create_entity({
            "Position": Position(x=px, y=py, level_id=self.level.id),
            "Renderable": Renderable(glyph="@", color="bright_yellow",
                                     render_order=10),
            "Stats": Stats(strength=2, dexterity=2, constitution=2,
                           intelligence=1, wisdom=1, charisma=0),
            "Health": Health(current=12, maximum=12),
            "Inventory": Inventory(max_slots=12),
            "Player": Player(),
            "Description": Description(name="You"),
            "Equipment": Equipment(),
        })

        # Spawn level entities
        self._spawn_level_entities()

        # Subscribe event handlers
        self.event_bus.subscribe(MessageEvent, self._on_message)
        self.event_bus.subscribe(GameWon, self._on_game_won)

        # Compute initial FOV
        self._update_fov()

        # Initialize renderer
        self.renderer.initialize()

        # Welcome message
        self.renderer.add_message(f"Welcome to {self.level.name}.")
        if self.level.metadata.ambient:
            self.renderer.add_message(self.level.metadata.ambient)

    def _spawn_level_entities(self) -> None:
        """Spawn all entities defined in the level file."""
        for placement in self.level.entities:
            try:
                if placement.entity_type == "creature":
                    components = EntityRegistry.get_creature(
                        placement.entity_id,
                    )
                    components["BlocksMovement"] = BlocksMovement()
                elif placement.entity_type == "item":
                    components = EntityRegistry.get_item(placement.entity_id)
                elif placement.entity_type == "feature":
                    components = EntityRegistry.get_feature(
                        placement.entity_id,
                    )
                    # Apply extra data (e.g. trap overrides)
                    if "Trap" in components and placement.extra:
                        trap = components["Trap"]
                        if "dc" in placement.extra:
                            trap.dc = placement.extra["dc"]
                        if "hidden" in placement.extra:
                            trap.hidden = placement.extra["hidden"]
                else:
                    continue

                components["Position"] = Position(
                    x=placement.x,
                    y=placement.y,
                    level_id=self.level.id,
                )
                self.world.create_entity(components)

            except KeyError:
                # Unknown entity type, skip
                pass

    def _update_fov(self) -> None:
        """Recompute field of view centered on player."""
        pos = self.world.get_component(self.player_id, "Position")
        if not pos or not self.level:
            return

        # Clear visibility
        for row in self.level.tiles:
            for tile in row:
                tile.visible = False

        def is_blocking(x: int, y: int) -> bool:
            tile = self.level.tile_at(x, y)
            if not tile:
                return True
            return tile.blocks_sight

        visible = compute_fov(pos.x, pos.y, FOV_RADIUS, is_blocking)

        for vx, vy in visible:
            tile = self.level.tile_at(vx, vy)
            if tile:
                tile.visible = True
                tile.explored = True

    async def run(self) -> None:
        """Main game loop."""
        self.running = True

        while self.running:
            # Render
            self.renderer.render(
                self.world, self.level, self.player_id, self.turn,
            )

            # Get player input
            intent, data = await self.renderer.get_input()

            # Convert intent to action
            action = self._intent_to_action(intent, data)
            if action is None:
                continue

            # Resolve player action
            events = await self._resolve(action)

            # Check win
            if self.won:
                self.renderer.show_end_screen(won=True, turn=self.turn)
                break

            # Advance turn
            self.turn += 1

            # Process creature turns
            creature_actions = []
            for eid, ai, cpos in self.world.query("AI", "Position"):
                if cpos is None:
                    continue
                ai_action = decide_action(
                    eid, self.world, self.level, self.player_id,
                )
                if ai_action:
                    creature_actions.append(ai_action)

            for ca in creature_actions:
                events += await self._resolve(ca)

            # Check player death
            health = self.world.get_component(self.player_id, "Health")
            if health and health.current <= 0:
                self.game_over = True
                self.renderer.add_message("You have died!")
                self.renderer.render(
                    self.world, self.level, self.player_id, self.turn,
                )
                self.renderer.show_end_screen(won=False, turn=self.turn)
                break

            # Recompute FOV
            self._update_fov()

    async def _resolve(self, action: "Action") -> list:
        """Validate and execute an action, emitting events."""
        if not await action.validate(self.world, self.level):
            return []

        events = await action.execute(self.world, self.level)
        for event in events:
            await self.event_bus.emit(event)
        return events

    def _intent_to_action(
        self, intent: str, data: tuple[int, int] | None,
    ) -> "Action | None":
        """Convert a player input intent to a game action."""
        if intent == "move" and data:
            dx, dy = data
            return BumpAction(actor=self.player_id, dx=dx, dy=dy)

        if intent == "wait":
            return WaitAction(actor=self.player_id)

        if intent == "pickup":
            return self._find_pickup_action()

        if intent == "use_item":
            return self._find_use_action()

        if intent == "inventory":
            self._show_inventory()
            return None

        if intent == "descend":
            return DescendStairsAction(actor=self.player_id)

        if intent == "scroll_up":
            self.renderer.scroll_messages(1)
            return None

        if intent == "scroll_down":
            self.renderer.scroll_messages(-1)
            return None

        if intent == "quit":
            self.running = False
            return None

        return None

    def _find_pickup_action(self) -> "Action | None":
        """Find an item at the player's position to pick up."""
        pos = self.world.get_component(self.player_id, "Position")
        if not pos:
            return None

        for eid, _, ipos in self.world.query("Description", "Position"):
            if ipos is None:
                continue
            if ipos.x == pos.x and ipos.y == pos.y and eid != self.player_id:
                # Check it's an item (has no AI/BlocksMovement)
                if (not self.world.has_component(eid, "AI")
                        and not self.world.has_component(eid, "BlocksMovement")
                        and not self.world.has_component(eid, "Trap")):
                    return PickupItemAction(
                        actor=self.player_id, item=eid,
                    )

        self.renderer.add_message("Nothing to pick up here.")
        return None

    def _find_use_action(self) -> "Action | None":
        """Show inventory menu and return a use action."""
        item_id = self.renderer.show_inventory_menu(
            self.world, self.player_id, "Use which item?",
        )
        if item_id is None:
            return None
        return UseItemAction(actor=self.player_id, item=item_id)

    def _show_inventory(self) -> None:
        """Show inventory without action (just display)."""
        self.renderer.show_inventory_menu(
            self.world, self.player_id, "Inventory (ESC to close)",
        )

    def _on_message(self, event: MessageEvent) -> None:
        """Handle message events by adding to renderer log."""
        self.renderer.add_message(event.text)

    def _on_game_won(self, event: GameWon) -> None:
        """Handle game won event."""
        self.won = True

    async def shutdown(self) -> None:
        """Clean up resources."""
        self.renderer.shutdown()
