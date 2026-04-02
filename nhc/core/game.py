"""Game loop and session management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nhc.ai.behavior import decide_action
from nhc.core import game_input, game_ticks

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
    from nhc.utils.llm import LLMBackend

FOV_RADIUS = 5

DEFAULT_SHAPE_VARIETY = 0.3
SHAPE_VARIETY_PER_DEPTH = 0.05
MAX_SHAPE_VARIETY = 0.8


def _shape_variety_for_depth(base: float, depth: int) -> float:
    """Scale shape variety with dungeon depth, capped at MAX."""
    if base == 0.0:
        return 0.0
    return min(base + (depth - 1) * SHAPE_VARIETY_PER_DEPTH,
               MAX_SHAPE_VARIETY)


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


def edge_door_blocked_tiles(
    x: int, y: int, door_side: str,
) -> set[tuple[int, int]]:
    """Return tiles to block FOV through a closed edge-door.

    When the player stands on a closed door tile, a 3-tile-wide
    virtual wall is placed in the door_side direction so that
    diagonal shadowcasting rays cannot leak around a single
    blocked tile into the room beyond.
    """
    if door_side == "north":
        return {(x + d, y - 1) for d in (-1, 0, 1)}
    if door_side == "south":
        return {(x + d, y + 1) for d in (-1, 0, 1)}
    if door_side == "east":
        return {(x + 1, y + d) for d in (-1, 0, 1)}
    if door_side == "west":
        return {(x - 1, y + d) for d in (-1, 0, 1)}
    return set()


_CLOSED_DOOR_FEATURES = frozenset({
    "door_closed", "door_locked", "door_secret",
})


def _has_visible_floor_neighbor(
    x: int, y: int, visible: set[tuple[int, int]],
    level: "Level", exclude: tuple[int, int] | None = None,
) -> bool:
    """True if any visible cardinal neighbor is a non-WALL tile.

    The door tile that triggered the walk is excluded so it
    doesn't prevent hiding its own flanking walls.
    """
    from nhc.dungeon.model import Terrain
    _FLOOR_TERRAIN = (Terrain.FLOOR, Terrain.WATER)
    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        if (nx, ny) == exclude:
            continue
        if (nx, ny) not in visible:
            continue
        t = level.tile_at(nx, ny)
        if t and t.terrain in _FLOOR_TERRAIN:
            return True
    return False


def door_wall_run_hidden(
    level: "Level", visible: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Return wall tiles along the wall run of visible closed doors.

    When a closed/locked/secret edge-door is visible, the
    contiguous wall tiles along the wall run reveal the room's
    structure.  Walk in both directions from the door, hiding
    each wall tile only if it has no visible non-wall neighbor
    (excluding the door itself).  This ensures walls next to
    the player's corridor remain visible.
    """
    from nhc.dungeon.model import Terrain

    hidden: set[tuple[int, int]] = set()
    for vx, vy in visible:
        tile = level.tile_at(vx, vy)
        if not tile or tile.feature not in _CLOSED_DOOR_FEATURES:
            continue
        side = tile.door_side
        if not side:
            continue
        door_pos = (vx, vy)
        # Vertical door (east/west): wall runs along y
        if side in ("east", "west"):
            for direction in (-1, 1):
                ny = vy + direction
                while True:
                    adj = level.tile_at(vx, ny)
                    if not adj or adj.terrain != Terrain.WALL:
                        break
                    if not _has_visible_floor_neighbor(
                        vx, ny, visible, level, door_pos,
                    ):
                        hidden.add((vx, ny))
                    ny += direction
        # Horizontal door (north/south): wall runs along x
        else:
            for direction in (-1, 1):
                nx = vx + direction
                while True:
                    adj = level.tile_at(nx, vy)
                    if not adj or adj.terrain != Terrain.WALL:
                        break
                    if not _has_visible_floor_neighbor(
                        nx, vy, visible, level, door_pos,
                    ):
                        hidden.add((nx, vy))
                    nx += direction
    return hidden


_CORRIDOR_OFFSET = {
    "north": (0, 1),    # wall north → corridor south
    "south": (0, -1),   # wall south → corridor north
    "east": (-1, 0),    # wall east → corridor west
    "west": (1, 0),     # wall west → corridor east
}


def compute_hatch_clear(
    level: "Level",
) -> set[tuple[int, int]]:
    """Return explored tiles whose hatch should be cleared.

    Only FLOOR/WATER tiles are included — WALL and VOID tiles
    stay hatched so the expand doesn't leak SVG corridor/room
    structure into adjacent unexplored tiles.  Closed, locked,
    or secret doors are excluded when the corridor side hasn't
    been explored yet.

    Exception: WALL tiles inside non-rectangular room bounding
    rects (octagon, circle, cross, hybrid) are included because
    the SVG draws room outlines as polygons that extend into
    those corner tiles.
    """
    from nhc.dungeon.model import RectShape, Terrain

    _CLEARABLE = (Terrain.FLOOR, Terrain.WATER)

    # Pre-compute WALL tiles inside non-rect room bounding rects.
    # These tiles have room outline content in the SVG.
    smooth_room_walls: set[tuple[int, int]] = set()
    for room in level.rooms:
        if isinstance(room.shape, RectShape):
            continue
        r = room.rect
        floor = room.floor_tiles()
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                if (x, y) not in floor:
                    smooth_room_walls.add((x, y))

    result: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tile_at(x, y)
            if not tile or not tile.explored:
                continue
            if tile.terrain not in _CLEARABLE:
                if (x, y) in smooth_room_walls:
                    result.add((x, y))
                continue
            if (tile.feature in _CLOSED_DOOR_FEATURES
                    and tile.door_side):
                offset = _CORRIDOR_OFFSET.get(tile.door_side)
                if offset:
                    cx, cy = x + offset[0], y + offset[1]
                    nb = level.tile_at(cx, cy)
                    if not nb or not nb.explored:
                        continue
            result.add((x, y))
    return result


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
        shape_variety: float = DEFAULT_SHAPE_VARIETY,
    ) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.backend = backend
        self.seed = seed
        self.mode = game_mode
        self.god_mode = god_mode
        self.reset = reset
        self.shape_variety = shape_variety
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
        logger.info("Game.initialize: reset=%s, generate=%s", self.reset,
                     generate)
        if self.reset and has_autosave():
            delete_autosave()
            logger.info("Autosave deleted (--reset)")
        elif has_autosave():
            logger.info("Autosave found, attempting recovery")
            if auto_restore(self):
                logger.info("Game RESTORED from autosave (turn=%d)",
                            self.turn)
                return
            logger.warning("Autosave recovery failed, starting fresh")
        else:
            logger.info("No autosave found, starting fresh game")

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

            sv = _shape_variety_for_depth(self.shape_variety, depth)
            params = GenerationParams(depth=depth, shape_variety=sv)
            gen = BSPGenerator()
            self.level = gen.generate(params)
            rng = __import__("nhc.utils.rng", fromlist=["get_rng"]).get_rng()
            assign_room_types(self.level, rng)
            apply_terrain(self.level, rng)
            populate_level(self.level)
            logger.info(
                "Generated level depth=%d shape_variety=%.2f "
                "(%dx%d, %d rooms)",
                depth, sv, self.level.width, self.level.height,
                len(self.level.rooms),
            )

            # Player starts at stairs_up
            px, py = 1, 1
            for y in range(self.level.height):
                for x in range(self.level.width):
                    if (self.level.tile_at(x, y)
                            and self.level.tile_at(x, y).feature
                            == "stairs_up"):
                        px, py = x, y
                        break
                else:
                    continue
                break
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
                blocked_tiles = edge_door_blocked_tiles(
                    pos.x, pos.y, cur.door_side,
                )

        def is_blocking(x: int, y: int) -> bool:
            if (x, y) in blocked_tiles:
                return True
            tile = self.level.tile_at(x, y)
            if not tile:
                return True
            return tile.blocks_sight

        visible = compute_fov(pos.x, pos.y, FOV_RADIUS, is_blocking)
        # Virtual wall tiles are room floor behind the door —
        # exclude them so the room isn't partially revealed.
        visible -= blocked_tiles

        # Hide wall tiles flanking visible closed doors so the
        # room's wall structure isn't revealed before entry.
        if self.renderer.edge_doors:
            visible -= door_wall_run_hidden(self.level, visible)

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
                logger.info("Player died: killed_by=%s turn=%d",
                            self.killed_by, self.turn)
                death_msg = t("game.died")
                if self.killed_by:
                    death_msg = t("game.slain_by", killer=self.killed_by)
                self.renderer.add_message(death_msg)
                self.renderer.render(
                    self.world, self.level, self.player_id, self.turn,
                )
                from nhc.core.autosave import delete_autosave
                logger.info("Deleting autosave after death...")
                delete_autosave()
                logger.info("Showing end screen...")
                self.renderer.show_end_screen(
                    won=False, turn=self.turn,
                    killed_by=self.killed_by,
                )
                logger.info("End screen dismissed, breaking game loop")
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
            return game_input.resolve_item_action(self, data)

        if intent == "wait":
            return WaitAction(actor=self.player_id)

        if intent == "pickup":
            return game_input.find_pickup_action(self)

        if intent == "use_item":
            return game_input.find_use_action(self)

        if intent == "quaff":
            return game_input.find_quaff_action(self)

        if intent == "throw":
            return game_input.find_throw_action(self)

        if intent == "zap":
            return game_input.find_zap_action(self)

        if intent == "equip":
            return game_input.find_equip_action(self)

        if intent == "drop":
            return game_input.find_drop_action(self)

        if intent == "inventory":
            self._show_inventory()
            return None

        if intent == "look":
            return LookAction(actor=self.player_id)

        if intent == "farlook":
            self._farlook_mode()
            return None

        if intent == "pick_lock":
            return game_input.find_lock_action(self, "pick")

        if intent == "force_door":
            return game_input.find_lock_action(self, "force")

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
            self.renderer.shutdown()
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
        game_ticks.tick_poison(self)

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

    def _tick_regeneration(self) -> None:
        game_ticks.tick_regeneration(self)

    def _tick_mummy_rot(self) -> None:
        game_ticks.tick_mummy_rot(self)

    def _tick_rings(self) -> None:
        game_ticks.tick_rings(self)

    def _tick_wand_recharge(self) -> None:
        game_ticks.tick_wand_recharge(self)

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
            sv = _shape_variety_for_depth(self.shape_variety, new_depth)
            params = GenerationParams(depth=new_depth, shape_variety=sv)
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

        # Notify the web client to load the new floor
        if hasattr(self.renderer, 'send_floor_change'):
            self.renderer.send_floor_change(
                self.level, self.world, self.player_id,
                self.turn, seed=self.seed or 0,
            )

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
