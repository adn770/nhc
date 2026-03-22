"""Game loop and session management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nhc.ai.behavior import decide_action

logger = logging.getLogger(__name__)
from nhc.core.actions import (
    BumpAction,
    DescendStairsAction,
    LookAction,
    PickupItemAction,
    UseItemAction,
    WaitAction,
)
from nhc.core.ecs import World
from nhc.core.events import (
    CreatureDied,
    EventBus,
    GameWon,
    LevelEntered,
    MessageEvent,
    PlayerDied,
)
from nhc.dungeon.loader import get_player_start, load_level
from nhc.i18n import t
from nhc.dungeon.model import Level
from nhc.entities.components import (
    BlocksMovement,
    Cursed,
    Description,
    Equipment,
    Health,
    Inventory,
    Player,
    Position,
    Regeneration,
    Renderable,
    Stats,
    StatusEffect,
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
        self._seen_creatures: set[int] = set()
        self.killed_by: str = ""

    async def initialize(
        self,
        level_path: str | Path | None = None,
        generate: bool = False,
        depth: int = 1,
    ) -> None:
        """Set up initial game state from a level file or generator."""
        if self.seed is not None:
            from nhc.utils.rng import set_seed
            set_seed(self.seed)
            logger.info("RNG seed set to %d", self.seed)

        # Discover all entity types
        EntityRegistry.discover_all()

        if generate:
            from nhc.dungeon.classic import ClassicGenerator
            from nhc.dungeon.generator import GenerationParams
            from nhc.dungeon.populator import populate_level

            params = GenerationParams(depth=depth)
            gen = ClassicGenerator()
            self.level = gen.generate(params)
            populate_level(self.level)
            logger.info(
                "Generated level depth=%d (%dx%d, %d rooms)",
                depth, self.level.width, self.level.height,
                len(self.level.rooms),
            )

            # Player starts at stairs_up (first room center)
            if self.level.rooms:
                px, py = self.level.rooms[0].rect.center
            else:
                px, py = 1, 1
        else:
            # Load from YAML file
            self.level = load_level(level_path)
            px, py = get_player_start(level_path)
            logger.info("Loaded level %r from %s", self.level.name, level_path)

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
            "Description": Description(name=t("game.player_name")),
            "Equipment": Equipment(),
        })

        # Spawn level entities
        self._spawn_level_entities()

        # Subscribe event handlers
        self.event_bus.subscribe(MessageEvent, self._on_message)
        self.event_bus.subscribe(GameWon, self._on_game_won)
        self.event_bus.subscribe(CreatureDied, self._on_creature_died)
        self.event_bus.subscribe(LevelEntered, self._on_level_entered)

        # Compute initial FOV
        self._update_fov()

        # Initialize renderer
        self.renderer.initialize()

        # Welcome message
        self.renderer.add_message(t("game.welcome", name=self.level.name))
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
                logger.warning(
                    "Unknown entity %s/%s at (%d,%d), skipping",
                    placement.entity_type, placement.entity_id,
                    placement.x, placement.y,
                )

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

        # Announce newly spotted creatures
        for eid, _, cpos in self.world.query("AI", "Position"):
            if cpos is None:
                continue
            tile = self.level.tile_at(cpos.x, cpos.y)
            if tile and tile.visible:
                if eid not in self._seen_creatures:
                    self._seen_creatures.add(eid)
                    desc = self.world.get_component(eid, "Description")
                    if desc:
                        self.renderer.add_message(
                            t("explore.spot_creature",
                              creature=desc.short),
                        )
            else:
                self._seen_creatures.discard(eid)

    async def run(self) -> None:
        """Main game loop."""
        self.running = True
        logger.info("Game loop started")

        while self.running:
            # Render
            self.renderer.render(
                self.world, self.level, self.player_id, self.turn,
            )

            # Get player input
            intent, data = await self.renderer.get_input()
            logger.debug("Input: intent=%s data=%s", intent, data)

            # Convert intent to action
            action = self._intent_to_action(intent, data)
            if action is None:
                continue

            # Status effects override player action
            player_status = self.world.get_component(
                self.player_id, "StatusEffect",
            )
            if player_status and player_status.paralyzed > 0:
                player_status.paralyzed -= 1
                self.renderer.add_message(t("combat.paralyzed_turn"))
                action = WaitAction(actor=self.player_id)
            elif player_status and player_status.sleeping > 0:
                player_status.sleeping -= 1
                self.renderer.add_message(t("combat.sleeping_turn"))
                action = WaitAction(actor=self.player_id)

            # Resolve player action
            logger.debug("Turn %d: resolving %s", self.turn, type(action).__name__)
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

            # Tick poison on all affected entities
            self._tick_poison()
            self._tick_regeneration()
            self._tick_mummy_rot()

            # Check player death
            health = self.world.get_component(self.player_id, "Health")
            if health and health.current <= 0:
                self.game_over = True
                # Find killer from events
                from nhc.core.events import CreatureAttacked
                for ev in events:
                    if (isinstance(ev, CreatureAttacked)
                            and ev.target == self.player_id and ev.hit):
                        desc = self.world.get_component(
                            ev.attacker, "Description",
                        )
                        if desc:
                            self.killed_by = desc.name
                death_msg = t("game.died")
                if self.killed_by:
                    death_msg = t("game.slain_by", killer=self.killed_by)
                self.renderer.add_message(death_msg)
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
            logger.debug("Action %s failed validation", type(action).__name__)
            return []

        try:
            events = await action.execute(self.world, self.level)
        except Exception:
            logger.error(
                "Exception executing %s (actor=%d)",
                type(action).__name__, action.actor,
                exc_info=True,
            )
            return []
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

        if intent == "look":
            return LookAction(actor=self.player_id)

        if intent == "descend":
            return DescendStairsAction(actor=self.player_id)

        if intent == "scroll_up":
            self.renderer.scroll_messages(1)
            return None

        if intent == "scroll_down":
            self.renderer.scroll_messages(-1)
            return None

        if intent == "save":
            self._save_game()
            return None

        if intent == "load":
            self._load_game()
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

        # Check if inventory is full
        inv = self.world.get_component(self.player_id, "Inventory")
        if inv and len(inv.slots) >= inv.max_slots:
            self.renderer.add_message(t("item.full_inventory"))
            return None

        self.renderer.add_message(t("item.nothing_to_pickup"))
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

    def _save_game(self) -> None:
        """Save current game state."""
        from nhc.core.save import save_game
        try:
            path = save_game(
                self.world, self.level, self.player_id,
                self.turn, self.renderer.messages,
            )
            logger.info("Game saved at turn %d", self.turn)
            self.renderer.add_message(t("game.game_saved"))
        except Exception:
            logger.error("Failed to save game", exc_info=True)
            self.renderer.add_message(t("game.save_failed", error="see log"))

    def _load_game(self) -> None:
        """Load game state from save file."""
        from nhc.core.save import has_save, load_game
        if not has_save():
            self.renderer.add_message(t("game.no_save"))
            return
        try:
            world, level, player_id, turn, messages = load_game()
            self.world = world
            self.level = level
            self.player_id = player_id
            self.turn = turn
            self.renderer.messages = messages
            self._seen_creatures.clear()
            self._update_fov()
            logger.info("Game loaded at turn %d", self.turn)
            self.renderer.add_message(t("game.game_loaded"))
        except Exception:
            logger.error("Failed to load game", exc_info=True)
            self.renderer.add_message(t("game.load_failed", error="see log"))

    def _tick_poison(self) -> None:
        """Apply ongoing poison damage and decrement counters."""
        from nhc.rules.combat import apply_damage, is_dead
        expired = []
        for eid, poison, health in self.world.query("Poison", "Health"):
            if health is None:
                continue
            actual = apply_damage(health, poison.damage_per_turn)
            desc = self.world.get_component(eid, "Description")
            name = desc.name if desc else "?"
            self.renderer.add_message(
                t("combat.poison_tick", target=name, damage=actual),
            )
            if is_dead(health):
                self.world.destroy_entity(eid)
            else:
                poison.turns_remaining -= 1
                if poison.turns_remaining <= 0:
                    expired.append(eid)
        for eid in expired:
            self.world.remove_component(eid, "Poison")

    def _creature_name(self, eid: int) -> str:
        desc = self.world.get_component(eid, "Description")
        return desc.name if desc else "?"

    def _tick_regeneration(self) -> None:
        """Troll-like regeneration: heal hp_per_turn if not fire-damaged."""
        from nhc.rules.combat import heal
        for eid, regen, health in self.world.query("Regeneration", "Health"):
            if health is None:
                continue
            if regen.fire_damaged:
                regen.fire_damaged = False  # reset flag; no heal this turn
                continue
            healed = heal(health, regen.hp_per_turn)
            if healed > 0:
                self.renderer.add_message(
                    t("combat.regenerates", creature=self._creature_name(eid)),
                )

    def _tick_mummy_rot(self) -> None:
        """Mummy rot curse: tick Cursed components and drain 1 max HP when due."""
        for eid, cursed, health in self.world.query("Cursed", "Health"):
            if health is None:
                continue
            cursed.ticks_until_drain -= 1
            if cursed.ticks_until_drain <= 0:
                if health.maximum > 1:
                    health.maximum -= 1
                    health.current = min(health.current, health.maximum)
                    self.renderer.add_message(
                        t("combat.rot_drain",
                          target=self._creature_name(eid)),
                    )
                cursed.ticks_until_drain = 2

    def _on_level_entered(self, event: LevelEntered) -> None:
        """Transition to a new dungeon level."""
        from nhc.dungeon.classic import ClassicGenerator
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.populator import populate_level

        new_depth = event.depth
        logger.info("Descending to depth %d", new_depth)

        # Remove all non-player entities (creatures, items on map)
        player_inv = self.world.get_component(self.player_id, "Inventory")
        keep_ids = {self.player_id}
        if player_inv:
            keep_ids.update(player_inv.slots)

        all_eids = list(self.world._entities)
        for eid in all_eids:
            if eid not in keep_ids:
                self.world.destroy_entity(eid)

        # Generate new level
        params = GenerationParams(depth=new_depth)
        gen = ClassicGenerator()
        self.level = gen.generate(params)
        populate_level(
            self.level,
            creature_count=3 + new_depth,
            item_count=2 + new_depth // 2,
            trap_count=1 + new_depth // 3,
        )

        # Spawn level entities
        self._spawn_level_entities()

        # Move player to stairs_up in new level
        if self.level.rooms:
            px, py = self.level.rooms[0].rect.center
            pos = self.world.get_component(self.player_id, "Position")
            if pos:
                pos.x = px
                pos.y = py
                pos.level_id = self.level.id

        self._seen_creatures.clear()
        self._update_fov()

    def _on_creature_died(self, event: CreatureDied) -> None:
        """Award XP when the player kills a creature."""
        if event.killer != self.player_id:
            return

        from nhc.rules.advancement import award_xp, check_level_up

        xp = award_xp(self.world, self.player_id, event.entity)
        if xp > 0:
            self.renderer.add_message(t("game.xp_gained", xp=xp))

        level_msgs = check_level_up(self.world, self.player_id)
        for msg in level_msgs:
            self.renderer.add_message(msg)

    def _on_message(self, event: MessageEvent) -> None:
        """Handle message events by adding to renderer log."""
        self.renderer.add_message(event.text)

    def _on_game_won(self, event: GameWon) -> None:
        """Handle game won event."""
        self.won = True

    async def shutdown(self) -> None:
        """Clean up resources."""
        self.renderer.shutdown()
