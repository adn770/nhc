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
    ItemUsed,
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
from nhc.rendering.client import GameClient
from nhc.utils.fov import compute_fov

if TYPE_CHECKING:
    from nhc.core.actions import Action
    from nhc.llm import LLMBackend

FOV_RADIUS = 8


def _resolve_click(
    world: World, level: "Level", player_id: int,
    target_x: int, target_y: int,
    edge_doors: bool = False,
) -> "Action | None":
    """Translate a map click into a game action.

    - Click on self → wait
    - Click adjacent tile → bump (move/attack/open door)
    - Click distant visible floor → single step toward target
    - Click wall/void/out-of-bounds → None
    """
    pos = world.get_component(player_id, "Position")
    if not pos:
        return None

    # Out of bounds
    if not level.in_bounds(target_x, target_y):
        return None

    tile = level.tile_at(target_x, target_y)
    if not tile:
        return None

    dx = target_x - pos.x
    dy = target_y - pos.y

    # Click on self
    if dx == 0 and dy == 0:
        return WaitAction(actor=player_id)

    # Normalize to single step direction
    step_x = 0 if dx == 0 else (1 if dx > 0 else -1)
    step_y = 0 if dy == 0 else (1 if dy > 0 else -1)

    # Adjacent click (including diagonal)
    if abs(dx) <= 1 and abs(dy) <= 1:
        return BumpAction(actor=player_id, dx=dx, dy=dy,
                          edge_doors=edge_doors)

    # Distant click — check target is walkable floor
    from nhc.dungeon.model import Terrain
    if tile.terrain not in (Terrain.FLOOR, Terrain.WATER):
        return None

    # Step one tile toward the target
    return BumpAction(actor=player_id, dx=step_x, dy=step_y,
                      edge_doors=edge_doors)


class Game:
    """Main game controller. Owns the world, event bus, and loop."""

    def __init__(
        self,
        client: GameClient,
        backend: "LLMBackend | None" = None,
        seed: int | None = None,
        game_mode: str = "classic",
        god_mode: bool = False,
        reset: bool = False,
    ) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.backend = backend
        self.seed = seed
        self.mode = game_mode
        self.god_mode = god_mode
        self.reset = reset
        self.running = False
        self.game_over = False
        self.won = False
        self.turn = 0
        self.player_id: int = -1
        self.level: Level | None = None
        self.renderer = client
        self._seen_creatures: set[int] = set()
        self._knowledge = None  # ItemKnowledge, set in initialize()
        self._floor_cache: dict[int, tuple] = {}  # depth → (level, entity_data)
        self.killed_by: str = ""
        self._gm = None  # GameMaster, set in initialize() for typed mode

    async def initialize(
        self,
        level_path: str | Path | None = None,
        generate: bool = False,
        depth: int = 1,
    ) -> None:
        """Set up initial game state from a level file or generator."""
        # Check for autosave recovery
        from nhc.core.autosave import auto_restore, delete_autosave, has_autosave
        if self.reset and has_autosave():
            delete_autosave()
            logger.info("Autosave deleted (--reset)")
        elif has_autosave():
            logger.info("Autosave found, attempting recovery")
            if auto_restore(self):
                logger.info("Game restored from autosave")
                return

        from nhc.utils.rng import get_seed, set_seed
        if self.seed is not None:
            set_seed(self.seed)
        effective_seed = get_seed()
        logger.info("RNG seed: %d (use --seed %d to reproduce)",
                     effective_seed, effective_seed)

        # Discover all entity types
        EntityRegistry.discover_all()

        # Initialize potion randomization
        from nhc.rules.identification import ItemKnowledge
        from nhc.utils.rng import get_rng as _get_rng
        self._knowledge = ItemKnowledge(rng=_get_rng())
        if self.god_mode:
            from nhc.rules.identification import ALL_IDS
            for item_id in ALL_IDS:
                self._knowledge.identify(item_id)

        if generate:
            from nhc.dungeon.generator import GenerationParams
            from nhc.dungeon.generators.bsp import BSPGenerator
            from nhc.dungeon.populator import populate_level
            from nhc.dungeon.room_types import assign_room_types
            from nhc.dungeon.terrain import apply_terrain

            params = GenerationParams(depth=depth)
            gen = BSPGenerator()
            self.level = gen.generate(params)
            rng = __import__("nhc.utils.rng", fromlist=["get_rng"]).get_rng()
            assign_room_types(self.level, rng)
            apply_terrain(self.level, rng)
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

        # Generate random character
        from nhc.rules.chargen import generate_character
        char = generate_character(seed=self.seed)
        inv_slots = 10 + char.constitution  # CON defense = bonus + 10

        self.player_id = self.world.create_entity({
            "Position": Position(x=px, y=py, level_id=self.level.id),
            "Renderable": Renderable(glyph="@", color="dark_grey",
                                     render_order=10),
            "Stats": Stats(
                strength=char.strength,
                dexterity=char.dexterity,
                constitution=char.constitution,
                intelligence=char.intelligence,
                wisdom=char.wisdom,
                charisma=char.charisma,
            ),
            "Health": Health(current=char.hp, maximum=char.hp),
            "Inventory": Inventory(max_slots=inv_slots),
            "Player": Player(gold=char.gold),
            "Description": Description(
                name=char.name,
                short=t(f"traits.{char.background}"),
            ),
            "Equipment": Equipment(),
        })
        self._character = char

        # Give starting equipment (respecting slot costs)
        from nhc.core.actions import _count_slots_used, _item_slot_cost
        inv = self.world.get_component(self.player_id, "Inventory")
        equip = self.world.get_component(self.player_id, "Equipment")
        for item_id in char.starting_items:
            try:
                item_comps = EntityRegistry.get_item(item_id)
                self._disguise_potion(item_comps, item_id)
                eid = self.world.create_entity(item_comps)
                if inv:
                    cost = _item_slot_cost(self.world, eid)
                    used = _count_slots_used(self.world, inv)
                    if used + cost > inv.max_slots:
                        # Doesn't fit — drop on the ground
                        self.world.destroy_entity(eid)
                        logger.info(
                            "Starting item %s skipped (slots full)", item_id,
                        )
                        continue
                    inv.slots.append(eid)
                    # Auto-equip starting gear
                    if equip:
                        if (equip.weapon is None
                                and self.world.has_component(eid, "Weapon")):
                            equip.weapon = eid
                        armor_comp = self.world.get_component(eid, "Armor")
                        if armor_comp:
                            slot_map = {"body": "armor",
                                        "shield": "shield",
                                        "helmet": "helmet"}
                            attr = slot_map.get(armor_comp.slot, "armor")
                            if getattr(equip, attr) is None:
                                setattr(equip, attr, eid)
            except KeyError:
                logger.warning("Unknown starting item: %s", item_id)

        # Spawn level entities
        self._spawn_level_entities()

        # Subscribe event handlers
        self.event_bus.subscribe(MessageEvent, self._on_message)
        self.event_bus.subscribe(GameWon, self._on_game_won)
        self.event_bus.subscribe(CreatureDied, self._on_creature_died)
        self.event_bus.subscribe(LevelEntered, self._on_level_entered)
        self.event_bus.subscribe(ItemUsed, self._on_item_used)

        # Compute initial FOV
        self._update_fov()

        # Initialize renderer
        self.renderer.initialize()

        # Initialize GM for typed mode
        if self.mode == "typed" and self.backend:
            from nhc.narrative.context import ContextBuilder
            from nhc.narrative.gm import GameMaster
            self._ctx_builder = ContextBuilder()
            self._gm = GameMaster(self.backend, self._ctx_builder)

        # Welcome message with character intro
        self.renderer.add_message(t("game.welcome", name=self.level.name))
        self.renderer.add_message(t(
            "game.char_intro",
            name=char.name,
            background=t(f"traits.{char.background}"),
            virtue=t(f"traits.{char.virtue}"),
            vice=t(f"traits.{char.vice}"),
            alignment=t(f"traits.{char.alignment}"),
        ))
        if self.level.metadata.ambient:
            self.renderer.add_message(self.level.metadata.ambient)

        # In typed mode, generate an LLM intro narration
        if self._gm:
            intro = await self._gm.intro(
                char_name=char.name,
                char_background=t(f"traits.{char.background}"),
                char_virtue=t(f"traits.{char.virtue}"),
                char_vice=t(f"traits.{char.vice}"),
                char_alignment=t(f"traits.{char.alignment}"),
                level_name=self.level.name,
                ambient=self.level.metadata.ambient,
                hooks=", ".join(self.level.metadata.narrative_hooks),
            )
            self.renderer.add_message(intro)

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
                    # Apply potion disguise if unidentified
                    self._disguise_potion(
                        components, placement.entity_id,
                    )
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

    def _disguise_potion(
        self, components: dict, item_id: str,
    ) -> None:
        """Override a potion/scroll description and color if unidentified."""
        if not self._knowledge:
            return
        if not self._knowledge.is_identifiable(item_id):
            return
        if self._knowledge.is_identified(item_id):
            return
        # Store the real item_id so we can identify later
        components["_potion_id"] = item_id
        desc = components.get("Description")
        if desc:
            desc.name = self._knowledge.display_name(item_id)
            desc.short = self._knowledge.display_short(item_id)
        rend = components.get("Renderable")
        if rend:
            rend.color = self._knowledge.glyph_color(item_id)

    def _identify_potion(self, real_id: str = "", item_eid: int = -1) -> None:
        """Identify a potion/scroll after use and update all of that type."""
        if not self._knowledge:
            return
        # Resolve real_id from entity if not provided directly
        if not real_id and item_eid >= 0:
            real_id = self.world.get_component(item_eid, "_potion_id") or ""
        if not real_id:
            return
        if self._knowledge.is_identified(real_id):
            return

        self._knowledge.identify(real_id)
        real_name = t(f"items.{real_id}.name")
        self.renderer.add_message(
            t("potion_appearance.identified", name=real_name),
        )

        # Update all existing items of this type in the world
        potion_store = self.world._components.get("_potion_id", {})
        for eid, pid in potion_store.items():
            if pid == real_id:
                desc = self.world.get_component(eid, "Description")
                if desc:
                    desc.name = self._knowledge.display_name(real_id)
                    desc.short = self._knowledge.display_short(real_id)

    def _update_fov(self) -> None:
        """Recompute field of view centered on player."""
        pos = self.world.get_component(self.player_id, "Position")
        if not pos or not self.level:
            return

        # Clear visibility
        for row in self.level.tiles:
            for tile in row:
                tile.visible = False

        # Check if player is on a closed/secret door tile (edge mode).
        # If so, block FOV in the door_side direction so the room
        # beyond the door isn't revealed while standing on the tile.
        blocked_tiles: set[tuple[int, int]] = set()
        if self.renderer.edge_doors:
            cur = self.level.tile_at(pos.x, pos.y)
            if (cur and cur.feature in ("door_closed", "door_locked",
                                        "door_secret")
                    and cur.door_side):
                # The first tile in the door_side direction acts as a
                # virtual wall, blocking FOV from passing through.
                side = cur.door_side
                if side == "north":
                    blocked_tiles.add((pos.x, pos.y - 1))
                elif side == "south":
                    blocked_tiles.add((pos.x, pos.y + 1))
                elif side == "east":
                    blocked_tiles.add((pos.x + 1, pos.y))
                elif side == "west":
                    blocked_tiles.add((pos.x - 1, pos.y))

        def is_blocking(x: int, y: int) -> bool:
            if (x, y) in blocked_tiles:
                return True
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
        logger.info("Game loop started (mode=%s)", self.mode)

        while self.running:
            # Render
            self.renderer.render(
                self.world, self.level, self.player_id, self.turn,
            )

            if self.mode == "typed":
                actions = await self._get_typed_actions()
            else:
                actions = await self._get_classic_actions()
            if not actions:
                continue

            # Take only the first action for status-effect override
            action = actions[0]

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

            # Resolve player action(s)
            events = []
            for act in actions:
                logger.debug("Turn %d: resolving %s",
                             self.turn, type(act).__name__)
                events += await self._resolve(act)

            # Check win
            if self.won:
                from nhc.core.autosave import delete_autosave
                delete_autosave()
                self.renderer.show_end_screen(won=True, turn=self.turn)
                break

            # Advance turn
            self.turn += 1

            # Process creature turns (only visible creatures act)
            creature_actions = []
            for eid, ai, cpos in self.world.query("AI", "Position"):
                if cpos is None:
                    continue
                tile = self.level.tile_at(cpos.x, cpos.y)
                if not tile or not tile.visible:
                    continue
                ai_action = decide_action(
                    eid, self.world, self.level, self.player_id,
                )
                if ai_action:
                    creature_actions.append(ai_action)

            creature_events = []
            for ca in creature_actions:
                creature_events += await self._resolve(ca)
            events += creature_events

            # Narrate creature actions in typed mode
            if self.mode == "typed" and self._gm and creature_events:
                c_outcomes = self._events_to_outcomes(creature_events)
                if c_outcomes:
                    c_narr = await self._gm.narrate_creatures(c_outcomes)
                    if c_narr.strip():
                        self.renderer.add_message(c_narr)

            # Tick poison on all affected entities
            self._tick_poison()
            self._tick_regeneration()
            self._tick_mummy_rot()
            self._tick_rings()
            self._tick_wand_recharge()

            # God mode: restore HP to max each turn
            health = self.world.get_component(self.player_id, "Health")
            if self.god_mode and health:
                health.current = health.maximum

            # Check player death (None means entity was destroyed)
            if not health or health.current <= 0:
                self.game_over = True
                self._detect_death_cause(events)
                death_msg = t("game.died")
                if self.killed_by:
                    death_msg = t("game.slain_by", killer=self.killed_by)
                self.renderer.add_message(death_msg)
                self.renderer.render(
                    self.world, self.level, self.player_id, self.turn,
                )
                from nhc.core.autosave import delete_autosave
                delete_autosave()
                self.renderer.show_end_screen(
                    won=False, turn=self.turn,
                    killed_by=self.killed_by,
                )
                break

            # Recompute FOV
            self._update_fov()

            # Autosave every turn
            from nhc.core.autosave import autosave as _autosave
            _autosave(self)

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
        # Tag MessageEvents with the acting entity so visibility
        # filtering can suppress messages from off-screen creatures
        for event in events:
            if isinstance(event, MessageEvent) and event.actor is None:
                event.actor = action.actor
            await self.event_bus.emit(event)
        return events

    async def _get_classic_actions(self) -> list:
        """Classic mode: single keypress → single action."""
        intent, data = await self.renderer.get_input()
        logger.debug("Input: intent=%s data=%s", intent, data)
        action = self._intent_to_action(intent, data)
        return [action] if action else []

    async def _get_typed_actions(self) -> list:
        """Typed mode: text input → GM interpret → action list."""
        from nhc.narrative.parser import action_plan_to_actions

        result = await self.renderer.get_typed_input(
            self.world, self.level, self.player_id, self.turn,
        )

        # Movement keys bypass the GM pipeline
        if isinstance(result, tuple):
            intent, data = result
            action = self._intent_to_action(intent, data)
            return [action] if action else []

        # Text input → GM pipeline
        typed_text = result
        if not typed_text:
            return []

        # Single-letter shortcuts: interpret as classic key commands
        # (e.g. "q" → quit, "g" → pickup, "s" → search, "i" → inventory)
        if len(typed_text) == 1:
            from nhc.rendering.terminal.input import map_key_to_intent
            intent, data = map_key_to_intent(typed_text)
            if intent != "unknown":
                action = self._intent_to_action(intent, data)
                return [action] if action else []

        # Text commands: help/ajuda/ayuda
        if typed_text.lower() in ("help", "ajuda", "ayuda", "?"):
            self.renderer.show_help()
            return []

        self.renderer.narrative_log.add_mechanical(f"> {typed_text}")

        if self._gm:
            # Phase 1: Interpret
            game_state = self._ctx_builder.build(
                self.world, self.level, self.player_id, self.turn,
            )
            plan = await self._gm.interpret(typed_text, game_state)

            # Phase 2: Convert to Action objects and resolve
            actions = action_plan_to_actions(
                plan, self.player_id, self.world, self.level,
            )
            all_events = []
            for act in actions:
                evts = await self._resolve(act)
                all_events += evts

            # Phase 2b: Follow-up — if custom checks were resolved,
            # ask the GM what mechanical consequences follow
            from nhc.core.events import CustomActionEvent
            custom_outcomes = [
                e for e in all_events if isinstance(e, CustomActionEvent)
            ]
            if custom_outcomes:
                check_results = self._events_to_outcomes(all_events)
                updated_state = self._ctx_builder.build(
                    self.world, self.level, self.player_id, self.turn,
                )
                follow_plan = await self._gm.follow_up(
                    typed_text, check_results, updated_state,
                )
                follow_actions = action_plan_to_actions(
                    follow_plan, self.player_id, self.world, self.level,
                )
                for act in follow_actions:
                    evts = await self._resolve(act)
                    all_events += evts

            # Phase 3: Narrate all outcomes together
            outcomes = self._events_to_outcomes(all_events)
            char = self._character
            narrative = await self._gm.narrate(
                intent=typed_text,
                outcomes=outcomes,
                char_name=char.name,
                char_background=t(f"traits.{char.background}"),
                char_virtue=t(f"traits.{char.virtue}"),
                char_vice=t(f"traits.{char.vice}"),
                ambient=self.level.metadata.ambient,
            )
            self.renderer.add_message(narrative)

            # Actions already resolved, return empty to skip double-resolve
            return [WaitAction(self.player_id)]
        else:
            # No LLM — use keyword fallback parser
            from nhc.narrative.fallback_parser import parse_intent_keywords
            plan = parse_intent_keywords(
                typed_text, self.world, self.level, self.player_id,
            )
            return action_plan_to_actions(
                plan, self.player_id, self.world, self.level,
            )

    def _events_to_outcomes(self, events: list) -> list[dict]:
        """Convert ECS events to outcome dicts for the narrator."""
        from nhc.core.events import (
            CreatureAttacked, CreatureDied, CustomActionEvent,
            ItemPickedUp, ItemUsed, MessageEvent,
        )
        outcomes = []
        for ev in events:
            if isinstance(ev, CreatureAttacked) and ev.hit:
                target_desc = self.world.get_component(ev.target, "Description")
                name = target_desc.name if target_desc else "creature"
                outcomes.append({
                    "action": "attack", "target": name,
                    "damage": ev.damage, "hit": True,
                })
            elif isinstance(ev, CreatureDied):
                desc = self.world.get_component(ev.entity, "Description")
                name = desc.name if desc else "creature"
                outcomes.append({"action": "kill", "target": name})
            elif isinstance(ev, ItemPickedUp):
                desc = self.world.get_component(ev.item, "Description")
                name = desc.name if desc else "item"
                outcomes.append({"action": "pickup", "result": f"Picked up {name}"})
            elif isinstance(ev, ItemUsed):
                outcomes.append({"action": "use_item", "effect": ev.effect})
            elif isinstance(ev, CustomActionEvent):
                outcomes.append({
                    "action": "custom",
                    "description": ev.description,
                    "ability": ev.ability,
                    "roll": ev.roll,
                    "bonus": ev.bonus,
                    "dc": ev.dc,
                    "success": ev.success,
                })
            elif isinstance(ev, MessageEvent):
                outcomes.append({"action": "message", "text": ev.text})
        return outcomes

    def _intent_to_action(
        self, intent: str, data: tuple[int, int] | None,
    ) -> "Action | None":
        """Convert a player input intent to a game action."""
        if intent == "move" and data:
            dx, dy = data
            return BumpAction(actor=self.player_id, dx=dx, dy=dy,
                              edge_doors=self.renderer.edge_doors)

        if intent == "item_action" and data:
            return self._resolve_item_action(data)

        if intent == "wait":
            return WaitAction(actor=self.player_id)

        if intent == "pickup":
            return self._find_pickup_action()

        if intent == "use_item":
            return self._find_use_action()

        if intent == "quaff":
            return self._find_quaff_action()

        if intent == "throw":
            return self._find_throw_action()

        if intent == "zap":
            return self._find_zap_action()

        if intent == "equip":
            return self._find_equip_action()

        if intent == "drop":
            return self._find_drop_action()

        if intent == "inventory":
            self._show_inventory()
            return None

        if intent == "look":
            return LookAction(actor=self.player_id)

        if intent == "farlook":
            self._farlook_mode()
            return None

        if intent == "pick_lock":
            return self._find_lock_action("pick")

        if intent == "force_door":
            return self._find_lock_action("force")

        if intent == "search":
            from nhc.core.actions import SearchAction
            return SearchAction(actor=self.player_id)

        if intent == "descend":
            return DescendStairsAction(actor=self.player_id)

        if intent == "ascend":
            from nhc.core.actions import AscendStairsAction
            return AscendStairsAction(actor=self.player_id)

        if intent == "scroll_up":
            self.renderer.scroll_messages(1)
            return None

        if intent == "scroll_down":
            self.renderer.scroll_messages(-1)
            return None

        if intent == "reveal_map":
            if self.god_mode:
                self._reveal_full_map()
            return None

        if intent == "help":
            self.renderer.show_help()
            return None

        if intent == "toggle_mode":
            self._toggle_mode()
            return None

        if intent == "click" and data:
            return _resolve_click(
                self.world, self.level, self.player_id,
                data.get("x", 0), data.get("y", 0),
                edge_doors=self.renderer.edge_doors,
            )

        if intent == "quit":
            self.running = False
            return None

        return None

    def _toggle_mode(self) -> None:
        """Switch between classic and typed game modes."""
        if self.mode == "classic":
            self.mode = "typed"
            self.renderer.game_mode = "typed"
            # Initialize GM if backend available and not already set up
            if self.backend and not self._gm:
                from nhc.narrative.context import ContextBuilder
                from nhc.narrative.gm import GameMaster
                self._ctx_builder = ContextBuilder()
                self._gm = GameMaster(self.backend, self._ctx_builder)
        else:
            self.mode = "classic"
            self.renderer.game_mode = "classic"
        logger.info("Switched to %s mode", self.mode)

    def _find_pickup_action(self) -> "Action | None":
        """Find an item at the player's position to pick up.

        If multiple items are on the ground, show a selection menu.
        """
        pos = self.world.get_component(self.player_id, "Position")
        if not pos:
            return None

        # Gather all pickable items at player's feet
        ground_items: list[tuple[int, str]] = []
        for eid, _, ipos in self.world.query("Description", "Position"):
            if ipos is None:
                continue
            if ipos.x == pos.x and ipos.y == pos.y and eid != self.player_id:
                if (not self.world.has_component(eid, "AI")
                        and not self.world.has_component(eid, "BlocksMovement")
                        and not self.world.has_component(eid, "Trap")):
                    desc = self.world.get_component(eid, "Description")
                    name = desc.short or desc.name if desc else "???"
                    ground_items.append((eid, name))

        if not ground_items:
            self.renderer.add_message(t("item.nothing_to_pickup"))
            return None

        # Single item: pick up directly
        if len(ground_items) == 1:
            return PickupItemAction(
                actor=self.player_id, item=ground_items[0][0],
            )

        # Multiple items: show selection menu
        selected = self.renderer.show_ground_menu(ground_items)
        if selected is None:
            return None
        return PickupItemAction(
            actor=self.player_id, item=selected,
        )

    def _find_use_action(self) -> "Action | None":
        """Show inventory menu and return a use action."""
        item_id = self.renderer.show_inventory_menu(
            self.world, self.player_id,
        )
        if item_id is None:
            return None
        return UseItemAction(actor=self.player_id, item=item_id)

    def _find_quaff_action(self) -> "Action | None":
        """Show potions only and quaff one."""
        item_id = self.renderer.show_filtered_inventory(
            self.world, self.player_id,
            title=t("ui.quaff_which"),
            filter_component="Consumable",
        )
        if item_id is None:
            return None
        return UseItemAction(actor=self.player_id, item=item_id)

    def _find_throw_action(self) -> "Action | None":
        """Pick a potion, then a visible target to throw it at."""
        from nhc.core.actions import ThrowAction

        # Step 1: pick a throwable item
        item_id = self.renderer.show_filtered_inventory(
            self.world, self.player_id,
            title=t("ui.throw_which"),
            filter_component="Throwable",
        )
        if item_id is None:
            return None

        # Step 2: pick a visible target
        target_id = self.renderer.show_target_menu(
            self.world, self.level, self.player_id,
            title=t("ui.throw_target"),
        )
        if target_id is None:
            return None

        return ThrowAction(
            actor=self.player_id, item=item_id, target=target_id,
        )

    def _find_zap_action(self) -> "Action | None":
        """Pick a wand, then a visible target to zap."""
        from nhc.core.actions import ZapAction

        # Show wands with charges
        inv = self.world.get_component(self.player_id, "Inventory")
        if not inv:
            return None

        items: list[tuple[int, str]] = []
        for item_id in inv.slots:
            wand = self.world.get_component(item_id, "Wand")
            if not wand:
                continue
            desc = self.world.get_component(item_id, "Description")
            name = desc.name if desc else "???"
            name += f" ({wand.charges}/{wand.max_charges})"
            items.append((item_id, name))

        if not items:
            return None

        selected = self.renderer.show_selection_menu(
            t("ui.zap_which"), items,
        )
        if selected is None:
            return None

        wand = self.world.get_component(selected, "Wand")
        if not wand or wand.charges <= 0:
            self.renderer.add_message(t("item.wand_fizzle"))
            return None

        target_id = self.renderer.show_target_menu(
            self.world, self.level, self.player_id,
            title=t("ui.throw_target"),
        )
        if target_id is None:
            return None

        return ZapAction(
            actor=self.player_id, item=selected, target=target_id,
        )

    def _find_equip_action(self) -> "Action | None":
        """Show equippable items and equip/unequip one."""
        from nhc.core.actions import EquipAction, UnequipAction
        inv = self.world.get_component(self.player_id, "Inventory")
        if not inv or not inv.slots:
            return None

        equip = self.world.get_component(self.player_id, "Equipment")
        equipped_ids = set()
        if equip:
            for attr in ("weapon", "armor", "shield", "helmet",
                          "ring_left", "ring_right"):
                eid = getattr(equip, attr)
                if eid is not None:
                    equipped_ids.add(eid)

        items: list[tuple[int, str]] = []
        for item_id in inv.slots:
            if not (self.world.has_component(item_id, "Weapon")
                    or self.world.has_component(item_id, "Armor")
                    or self.world.has_component(item_id, "Ring")):
                continue
            desc = self.world.get_component(item_id, "Description")
            name = desc.name if desc else "???"
            if item_id in equipped_ids:
                name += " [E]"
            items.append((item_id, name))

        if not items:
            return None

        selected = self.renderer.show_selection_menu(
            t("ui.equip_which"), items,
        )
        if selected is None:
            return None

        # Toggle: if already equipped, unequip; otherwise equip
        if selected in equipped_ids:
            return UnequipAction(actor=self.player_id, item=selected)
        return EquipAction(actor=self.player_id, item=selected)

    def _find_drop_action(self) -> "Action | None":
        """Show full inventory and drop selected item."""
        from nhc.core.actions import DropAction
        item_id = self.renderer.show_inventory_menu(
            self.world, self.player_id,
            prompt=t("ui.drop_which"),
        )
        if item_id is None:
            return None
        return DropAction(actor=self.player_id, item=item_id)

    def _find_lock_action(self, mode: str) -> "Action | None":
        """Find an adjacent locked door and return pick/force action."""
        from nhc.core.actions import ForceDoorAction, PickLockAction
        pos = self.world.get_component(self.player_id, "Position")
        if not pos or not self.level:
            return None

        # Check all 4 cardinal directions for a locked door
        door_dir = None
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            tile = self.level.tile_at(pos.x + dx, pos.y + dy)
            if tile and tile.feature == "door_locked":
                door_dir = (dx, dy)
                break

        if not door_dir:
            self.renderer.add_message(t("explore.no_locked_door"))
            return None

        if mode == "pick":
            return PickLockAction(
                actor=self.player_id, dx=door_dir[0], dy=door_dir[1],
            )

        # Force mode: check inventory for tools/weapons that help
        inv = self.world.get_component(self.player_id, "Inventory")
        tool_id = None
        if inv:
            tools: list[tuple[int, str]] = []
            for eid in inv.slots:
                if self.world.has_component(eid, "ForceTool"):
                    desc = self.world.get_component(eid, "Description")
                    name = desc.name if desc else "???"
                    tools.append((eid, name))
                elif self.world.has_component(eid, "Weapon"):
                    weapon = self.world.get_component(eid, "Weapon")
                    if weapon.type == "melee":
                        desc = self.world.get_component(eid, "Description")
                        name = desc.name if desc else "???"
                        tools.append((eid, name))

            if tools:
                # Add bare hands option
                tools.append((-1, t("explore.bare_hands")))
                selected = self.renderer.show_selection_menu(
                    t("explore.force_with"), tools,
                )
                if selected is None:
                    return None
                if selected != -1:
                    tool_id = selected

        return ForceDoorAction(
            actor=self.player_id, dx=door_dir[0], dy=door_dir[1],
            tool=tool_id,
        )

    def _resolve_item_action(self, data: dict) -> "Action | None":
        """Convert a direct item_action message to an Action.

        Bypasses the menu flow — the client already selected the item.
        For throw/zap, a target menu is still shown.
        """
        from nhc.core.actions import (
            DropAction, EquipAction, ThrowAction, UnequipAction,
            UseItemAction, ZapAction,
        )
        action = data.get("action")
        item_id = data.get("item_id")
        if item_id is None:
            return None

        if action in ("quaff", "use"):
            return UseItemAction(actor=self.player_id, item=item_id)

        if action == "equip":
            return EquipAction(actor=self.player_id, item=item_id)

        if action == "unequip":
            return UnequipAction(actor=self.player_id, item=item_id)

        if action == "drop":
            return DropAction(actor=self.player_id, item=item_id)

        if action == "throw":
            target_id = self.renderer.show_target_menu(
                self.world, self.level, self.player_id,
                title=t("ui.throw_target"),
            )
            if target_id is None:
                return None
            return ThrowAction(
                actor=self.player_id, item=item_id, target=target_id,
            )

        if action == "zap":
            target_id = self.renderer.show_target_menu(
                self.world, self.level, self.player_id,
                title=t("ui.throw_target"),
            )
            if target_id is None:
                return None
            return ZapAction(
                actor=self.player_id, item=item_id, target=target_id,
            )

        return None

    def _reveal_full_map(self) -> None:
        """God mode: reveal entire map and display it scrollably."""
        if not self.level:
            return
        # Mark all tiles as explored and visible
        old_vis: list[tuple[int, int, bool]] = []
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile:
                    old_vis.append((x, y, tile.visible))
                    tile.explored = True
                    tile.visible = True

        # Render the full map with a scrollable camera
        self.renderer.fullmap_mode(
            self.world, self.level, self.player_id, self.turn,
        )

        # Restore original visibility
        for x, y, was_visible in old_vis:
            tile = self.level.tile_at(x, y)
            if tile:
                tile.visible = was_visible

    def _farlook_mode(self) -> None:
        """Interactive cursor to examine tiles at distance."""
        pos = self.world.get_component(self.player_id, "Position")
        if not pos or not self.level:
            return

        self.renderer.farlook_mode(
            self.world, self.level, self.player_id, self.turn,
            pos.x, pos.y,
        )

    def _show_inventory(self) -> None:
        """Show inventory without action (just display)."""
        self.renderer.show_inventory_menu(
            self.world, self.player_id,
            prompt=t("ui.inventory_title"),
        )

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
                if eid == self.player_id:
                    self.killed_by = "poison"
                else:
                    self.world.destroy_entity(eid)
            else:
                poison.turns_remaining -= 1
                if poison.turns_remaining <= 0:
                    expired.append(eid)
        for eid in expired:
            self.world.remove_component(eid, "Poison")

    def _detect_death_cause(self, events: list) -> None:
        """Determine what killed the player from turn events."""
        from nhc.core.events import CreatureAttacked, TrapTriggered
        # Melee attacks take priority
        for ev in events:
            if (isinstance(ev, CreatureAttacked)
                    and ev.target == self.player_id and ev.hit):
                desc = self.world.get_component(ev.attacker, "Description")
                if desc:
                    self.killed_by = desc.name
        if self.killed_by:
            return
        # Check trap damage
        for ev in events:
            if (isinstance(ev, TrapTriggered)
                    and ev.entity == self.player_id and ev.damage > 0):
                self.killed_by = ev.trap_name
                return

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

    def _tick_rings(self) -> None:
        """Apply passive ring effects each turn."""
        equip = self.world.get_component(self.player_id, "Equipment")
        if not equip:
            return
        for slot in ("ring_left", "ring_right"):
            eid = getattr(equip, slot)
            if eid is None:
                continue
            ring = self.world.get_component(eid, "Ring")
            if not ring:
                continue

            if ring.effect == "mending" and self.turn % 5 == 0:
                health = self.world.get_component(
                    self.player_id, "Health",
                )
                if health and health.current < health.maximum:
                    health.current = min(
                        health.current + 1, health.maximum,
                    )

            if ring.effect == "detection":
                # Auto-reveal traps and secret doors in FOV
                for y in range(self.level.height):
                    for x in range(self.level.width):
                        tile = self.level.tile_at(x, y)
                        if not tile or not tile.visible:
                            continue
                        if tile.feature == "door_secret":
                            tile.feature = "door_closed"
                        for eid2, trap, tpos in self.world.query(
                            "Trap", "Position",
                        ):
                            if (tpos and tpos.x == x and tpos.y == y
                                    and trap.hidden):
                                trap.hidden = False

    def _tick_wand_recharge(self) -> None:
        """Recharge wands in inventory over time."""
        inv = self.world.get_component(self.player_id, "Inventory")
        if not inv:
            return
        for item_id in inv.slots:
            wand = self.world.get_component(item_id, "Wand")
            if not wand or wand.charges >= wand.max_charges:
                continue
            wand.recharge_timer -= 1
            if wand.recharge_timer <= 0:
                wand.charges += 1
                wand.recharge_timer = 20

    def _on_level_entered(self, event: LevelEntered) -> None:
        """Transition to a dungeon level (ascending or descending)."""
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.generators.bsp import BSPGenerator
        from nhc.dungeon.populator import populate_level
        from nhc.dungeon.room_types import assign_room_types
        from nhc.dungeon.terrain import apply_terrain

        new_depth = event.depth
        old_depth = self.level.depth
        ascending = new_depth < old_depth
        logger.info("%s to depth %d",
                     "Ascending" if ascending else "Descending", new_depth)

        # Save current floor state (level + non-player entities)
        self._save_floor()

        # Remove all non-player entities from the world
        player_inv = self.world.get_component(self.player_id, "Inventory")
        keep_ids = {self.player_id}
        if player_inv:
            keep_ids.update(player_inv.slots)
        for eid in list(self.world._entities):
            if eid not in keep_ids:
                self.world.destroy_entity(eid)

        # Restore cached floor or generate new one
        if new_depth in self._floor_cache:
            self._restore_floor(new_depth)
            logger.info("Restored cached floor at depth %d", new_depth)
        else:
            params = GenerationParams(depth=new_depth)
            gen = BSPGenerator()
            self.level = gen.generate(params)
            rng = __import__("nhc.utils.rng", fromlist=["get_rng"]).get_rng()
            assign_room_types(self.level, rng)
            apply_terrain(self.level, rng)
            populate_level(self.level)
            self._spawn_level_entities()

        # Place player at the appropriate stairs
        if ascending:
            # Came from below → place at stairs_down
            stair_feature = "stairs_down"
        else:
            # Came from above → place at stairs_up
            stair_feature = "stairs_up"

        placed = False
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile and tile.feature == stair_feature:
                    pos = self.world.get_component(
                        self.player_id, "Position",
                    )
                    if pos:
                        pos.x = x
                        pos.y = y
                        pos.level_id = self.level.id
                    placed = True
                    break
            if placed:
                break

        if not placed:
            # Fallback: entry room center
            entry = next(
                (r for r in self.level.rooms if "entry" in r.tags),
                self.level.rooms[0] if self.level.rooms else None,
            )
            if entry:
                px, py = entry.rect.center
                pos = self.world.get_component(
                    self.player_id, "Position",
                )
                if pos:
                    pos.x = px
                    pos.y = py
                    pos.level_id = self.level.id

        self._seen_creatures.clear()
        self._update_fov()

    def _save_floor(self) -> None:
        """Save the current floor's level and entities to cache."""
        depth = self.level.depth
        player_inv = self.world.get_component(self.player_id, "Inventory")
        keep_ids = {self.player_id}
        if player_inv:
            keep_ids.update(player_inv.slots)

        # Gather components per non-player entity
        entity_data: dict[int, dict[str, object]] = {}
        for eid in self.world._entities:
            if eid in keep_ids:
                continue
            comps: dict[str, object] = {}
            for comp_type, store in self.world._components.items():
                if eid in store:
                    comps[comp_type] = store[eid]
            if comps:
                entity_data[eid] = comps

        self._floor_cache[depth] = (self.level, entity_data)
        logger.info("Saved floor depth %d (%d entities cached)",
                     depth, len(entity_data))

    def _restore_floor(self, depth: int) -> None:
        """Restore a cached floor's level and entities.

        Preserves original entity IDs so cross-references (inventory
        slots, equipment pointers) remain valid.
        """
        level, entity_data = self._floor_cache[depth]
        self.level = level

        for eid, comps in entity_data.items():
            self.world._entities.add(eid)
            for comp_type, comp in comps.items():
                self.world.add_component(eid, comp_type, comp)
            # Keep _next_id above all restored IDs
            if eid >= self.world._next_id:
                self.world._next_id = eid + 1

    def _on_creature_died(self, event: CreatureDied) -> None:
        """Award XP when the player kills a creature."""
        if event.killer != self.player_id:
            return

        from nhc.rules.advancement import award_xp_direct, check_level_up

        xp = award_xp_direct(self.world, self.player_id, event.max_hp)
        if xp > 0:
            self.renderer.add_message(t("game.xp_gained", xp=xp))

        level_msgs = check_level_up(self.world, self.player_id)
        for msg in level_msgs:
            self.renderer.add_message(msg)

    def _on_message(self, event: MessageEvent) -> None:
        """Handle message events by adding to renderer log.

        Messages from off-screen actors are silently dropped so the
        player doesn't learn about things they can't see.
        """
        if event.actor is not None and event.actor != self.player_id:
            pos = self.world.get_component(event.actor, "Position")
            if pos and self.level:
                tile = self.level.tile_at(pos.x, pos.y)
                if not tile or not tile.visible:
                    return
        self.renderer.add_message(event.text)

    def _on_item_used(self, event: ItemUsed) -> None:
        """Identify items when used. Handle identify scroll specially."""
        self._identify_potion(real_id=event.item_id, item_eid=event.item)

        if event.effect == "identify":
            self._use_identify_scroll()

    def _use_identify_scroll(self) -> None:
        """Let the player pick an unidentified item to reveal."""
        if not self._knowledge:
            return
        inv = self.world.get_component(self.player_id, "Inventory")
        if not inv:
            return

        # Gather unidentified items
        items: list[tuple[int, str]] = []
        for item_id in inv.slots:
            real_id = self.world.get_component(item_id, "_potion_id")
            if not real_id:
                continue
            if self._knowledge.is_identified(real_id):
                continue
            desc = self.world.get_component(item_id, "Description")
            name = desc.name if desc else "???"
            items.append((item_id, name))

        if not items:
            self.renderer.add_message(t("item.identify_nothing"))
            return

        selected = self.renderer.show_selection_menu(
            t("ui.identify_which"), items,
        )
        if selected is None:
            return

        real_id = self.world.get_component(selected, "_potion_id")
        if real_id:
            self._identify_potion(real_id=real_id)

    def _on_game_won(self, event: GameWon) -> None:
        """Handle game won event."""
        self.won = True

    async def shutdown(self) -> None:
        """Clean up resources."""
        self.renderer.shutdown()
