"""Game loop and session management."""

from __future__ import annotations

import logging
import random
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from nhc.ai.behavior import decide_action
from nhc.core import game_input, game_ticks
from nhc.core.actions import (
    AscendStairsAction,
    BumpAction,
    DescendStairsAction,
    LookAction,
    PickupItemAction,
    SearchAction,
    UseItemAction,
    WaitAction,
    _count_slots_used,
    _entity_name,
    _item_slot_cost,
)
from nhc.core.autosave import (
    auto_restore,
    autosave as _autosave,
    delete_autosave,
    has_autosave,
)
from nhc.core.ecs import World
from nhc.core.events import (
    CreatureAttacked,
    CreatureDied,
    CustomActionEvent,
    DoorOpened,
    EventBus,
    GameWon,
    ItemPickedUp,
    ItemSold,
    ItemUsed,
    LevelEntered,
    MessageEvent,
    PlayerDied,
    HenchmanMenuEvent,
    ShopMenuEvent,
    TempleMenuEvent,
    TrapTriggered,
    VisualEffect,
)
from nhc.dungeon.generator import GenerationParams, pick_map_size
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.themes import theme_for_depth
from nhc.dungeon.loader import get_player_start, load_level
from nhc.dungeon.model import Level, Terrain
from nhc.entities.components import (
    BlocksMovement,
    Cursed,
    Description,
    Equipment,
    Health,
    Hunger,
    Inventory,
    Player,
    Position,
    Regeneration,
    Renderable,
    ShopInventory,
    Stats,
    StatusEffect,
)
from nhc.core.actions._hex_movement import MoveHexAction
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.generator import generate_test_world
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import HexFeatureType, HexWorld
from nhc.hexcrawl.pack import load_pack
from nhc.i18n import t
from nhc.narrative.context import ContextBuilder
from nhc.narrative.fallback_parser import parse_intent_keywords
from nhc.narrative.gm import GameMaster
from nhc.narrative.parser import action_plan_to_actions
from nhc.rendering.client import GameClient
from nhc.rendering.terminal.input import map_key_to_intent
from nhc.rules.advancement import award_xp_direct, check_level_up
from nhc.rules.chargen import generate_character
from nhc.rules.identification import ALL_IDS, ItemKnowledge
from nhc.utils.fov import compute_fov
from nhc.utils.rng import get_rng, get_seed, set_seed

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from concurrent.futures import Executor
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
        save_dir: Path | None = None,
        world_mode: GameMode = GameMode.DUNGEON,
    ) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.backend = backend
        self.seed = seed
        self.mode = game_mode
        self.world_mode = world_mode
        self.god_mode = god_mode
        self.reset = reset
        self.shape_variety = shape_variety
        self.save_dir = save_dir
        self.running = False
        self.game_over = False
        self.won = False
        self.turn = 0
        self.player_id: int = -1
        self.level: Level | None = None
        self.renderer = client
        self._seen_creatures: set[int] = set()
        self._knowledge = None  # ItemKnowledge, set in initialize()
        # depth (dungeon mode) or (q, r, depth) tuple (hex mode)
        # -> (level, entity_data). See _cache_key().
        self._floor_cache: dict[
            "int | tuple[int, int, int]", tuple
        ] = {}
        self._svg_cache: dict[int, tuple[str, str]] = {}  # depth → (uuid, svg)
        self._prefetch_depth: int | None = None   # depth being/been prefetched
        self._prefetch_result: Level | None = None  # pre-generated level
        self._prefetch_params: GenerationParams | None = None
        self._prefetch_thread: threading.Thread | None = None
        self.generation_params: GenerationParams | None = None
        self.killed_by: str = ""
        self._gm = None  # GameMaster, set in initialize() for typed mode
        # Character sheet used by typed-mode narration. Populated in
        # the dungeon-init path; hex mode leaves it as None so the
        # autosave/restore path doesn't AttributeError.
        self._character = None
        # Hex mode state — populated by _init_hex_world() when
        # world_mode is HEX_EASY or HEX_SURVIVAL. None in pure
        # dungeon mode.
        self.hex_world: "HexWorld | None" = None
        self.hex_player_position: "HexCoord | None" = None

    def set_god_mode(self, enabled: bool) -> None:
        """Toggle god mode live.  Identifies all items when enabled."""
        self.god_mode = enabled
        if enabled and self._knowledge:
            for item_id in ALL_IDS:
                self._knowledge.identify(item_id)

    def _cache_key(self, depth: int) -> "int | tuple[int, int, int]":
        """Floor-cache key for a given ``depth``.

        In pure dungeon mode the key is the depth integer, matching
        the historical behaviour byte-for-byte. In hex mode the key
        bundles the hex coordinate of the feature whose dungeon the
        player is currently exploring, so two different hexes' caves
        at the same depth are cached independently.

        Degrades to the integer-depth key when ``hex_player_position``
        is not yet set (pre-initialize or test setup).
        """
        if self.world_mode.is_hex and self.hex_player_position is not None:
            return (
                self.hex_player_position.q,
                self.hex_player_position.r,
                depth,
            )
        return depth

    async def enter_hex_feature(self) -> bool:
        """Enter the dungeon attached to the player's current hex.

        Returns ``True`` when a dungeon was loaded (freshly
        generated, or restored from the floor cache); ``False`` when
        the player is not on a feature hex with a :class:`DungeonRef`.

        Day clock stays frozen for the duration of the visit
        (intentionally — dungeon time is "out of band"). Floor cache
        is keyed by ``(q, r, depth)`` so re-entering the same hex
        after exiting hands back the same Level instance.
        """
        if not self.world_mode.is_hex or self.hex_world is None:
            return False
        coord = self.hex_player_position
        if coord is None:
            return False
        cell = self.hex_world.get_cell(coord)
        if cell is None or cell.dungeon is None:
            return False

        depth = 1
        cache_key = self._cache_key(depth)
        if cache_key in self._floor_cache:
            level, _ = self._floor_cache[cache_key]
            self.level = level
            return True

        from nhc.hexcrawl.seed import dungeon_seed
        template = cell.dungeon.template
        seed = dungeon_seed(self.seed or 0, coord, template)
        sv = _shape_variety_for_depth(self.shape_variety, depth)
        theme = (
            "cave" if template.startswith("procedural:cave")
            else theme_for_depth(depth)
        )
        map_w, map_h = pick_map_size(get_rng(), depth=depth)
        params = GenerationParams(
            width=map_w, height=map_h, depth=depth,
            shape_variety=sv, theme=theme, seed=seed,
        )
        self.generation_params = params
        self.level = generate_level(params)
        # Cache the freshly generated floor under the (q, r, depth)
        # key so re-entry skips regeneration.
        self._floor_cache[cache_key] = (self.level, {})
        return True

    async def exit_dungeon_to_hex(self) -> bool:
        """Pop back to the overland after a dungeon visit.

        Returns ``True`` when there was an active dungeon to leave;
        ``False`` (no-op) otherwise. The current Level is dropped
        from ``game.level`` but stays in the floor cache so re-entry
        is instantaneous.
        """
        if self.level is None or not self.world_mode.is_hex:
            return False
        self.level = None
        return True

    async def apply_hex_step(self, target: HexCoord) -> bool:
        """Execute a single overland step.

        Validates adjacency, runs :class:`MoveHexAction`, updates
        ``hex_player_position``, and writes an autosave. Returns
        True on success, False when the target is non-adjacent /
        out-of-bounds.

        Raises :class:`RuntimeError` when called outside hex mode so
        a miswired input handler fails loudly rather than silently
        corrupting the floor cache.
        """
        if not self.world_mode.is_hex or self.hex_world is None:
            raise RuntimeError(
                "apply_hex_step only valid in hex mode"
            )
        origin = self.hex_player_position
        if origin is None:
            raise RuntimeError(
                "apply_hex_step requires hex_player_position to be set"
            )
        action = MoveHexAction(
            actor=self.player_id,
            origin=origin,
            target=target,
            hex_world=self.hex_world,
        )
        if not await action.validate(self.world, None):
            return False
        await action.execute(self.world, None)
        self.hex_player_position = target
        _autosave(self, self.save_dir, blocking=True)
        return True

    def _init_hex_world(self) -> None:
        """Build the overland HexWorld for the configured hex mode.

        Difficulty rules (see ``design/overland_hexcrawl.md`` §2):

        * ``HEX_EASY`` -- player starts on the hub hex; the hub is
          revealed.
        * ``HEX_SURVIVAL`` -- player starts on a random non-feature
          hex; the hub is *not* revealed.

        Neighbour reveal on first step is the responsibility of
        ``MoveHexAction`` (M-1.5 / M-1.6); the initial reveal here
        is exactly one hex.
        """
        # Path-relative load of the bundled testland pack. A future
        # milestone will let the caller pick a pack via the CLI.
        pack_path = (
            Path(__file__).resolve().parents[2]
            / "content" / "testland" / "pack.yaml"
        )
        pack = load_pack(pack_path)
        self.hex_world = generate_test_world(seed=self.seed, pack=pack)

        if self.world_mode is GameMode.HEX_EASY:
            hub = self.hex_world.last_hub
            assert hub is not None, "generator must set last_hub"
            self.hex_player_position = hub
            self.hex_world.reveal(hub)
            return

        # HEX_SURVIVAL: random non-feature hex, hub stays hidden.
        # Use a derived RNG so the start-hex roll does not perturb
        # the seed stream consumed by the generator.
        rng = random.Random((self.seed or 0) ^ 0xABCD1234)
        candidates = [
            c for c, cell in self.hex_world.cells.items()
            if cell.feature is HexFeatureType.NONE
            and c != self.hex_world.last_hub
        ]
        if not candidates:
            raise RuntimeError(
                "no non-feature hex available for survival start"
            )
        start = rng.choice(candidates)
        self.hex_player_position = start
        self.hex_world.revealed.clear()
        self.hex_world.reveal(start)

    def initialize(
        self,
        level_path: str | Path | None = None,
        generate: bool = False,
        depth: int = 1,
        executor: "Executor | None" = None,
    ) -> None:
        """Set up initial game state from a level file or generator.

        Synchronous by design: under a gunicorn gevent worker, wrapping
        this call in ``asyncio.run`` caused a race where a second
        greenlet entering the same handler saw the first greenlet's
        still-running loop in the thread-local registry and raised
        ``RuntimeError: asyncio.run() cannot be called from a running
        event loop``. The LLM intro narration used in typed mode lives
        in :meth:`generate_intro_narration` and must be awaited by the
        caller after ``initialize``.
        """
        # Check for autosave recovery
        logger.info("Game.initialize: reset=%s, generate=%s", self.reset,
                     generate)
        if self.reset and has_autosave(self.save_dir):
            delete_autosave(self.save_dir)
            logger.info("Autosave deleted (--reset)")
        elif has_autosave(self.save_dir):
            logger.info("Autosave found, attempting recovery")
            requested_god = self.god_mode
            if auto_restore(self, self.save_dir):
                # Re-apply the requested god_mode — the autosave may
                # have been created before god mode was toggled.
                if requested_god and not self.god_mode:
                    self.set_god_mode(True)
                elif not requested_god and self.god_mode:
                    self.god_mode = False
                logger.info("Game RESTORED from autosave (turn=%d)",
                            self.turn)
                return
            logger.warning("Autosave recovery failed, starting fresh")
        else:
            logger.info("No autosave found, starting fresh game")

        if self.seed is not None:
            set_seed(self.seed)
        self.seed = get_seed()
        logger.info("RNG seed: %d (use --seed %d to reproduce)",
                     self.seed, self.seed)

        # Discover all entity types
        EntityRegistry.discover_all()

        # Initialize potion randomization
        self._knowledge = ItemKnowledge(rng=get_rng())
        if self.god_mode:
            for item_id in ALL_IDS:
                self._knowledge.identify(item_id)

        # Hex modes wrap the dungeon crawler. They build the
        # overland HexWorld and skip the dungeon-only init below;
        # a dungeon level will be loaded later when the player
        # enters a hex feature (M-1.12).
        if self.world_mode.is_hex:
            self._init_hex_world()
            return

        if generate:
            sv = _shape_variety_for_depth(self.shape_variety, depth)
            theme = theme_for_depth(depth)
            map_w, map_h = pick_map_size(get_rng(), depth=depth)
            params = GenerationParams(
                width=map_w, height=map_h,
                depth=depth, shape_variety=sv, theme=theme,
                seed=self.seed,
            )
            self.generation_params = params
            # Delegate to the pure pipeline. When an executor is
            # provided (web server path), offload generation to a
            # worker process so the main event loop stays responsive
            # and multiple cores can serve concurrent players. When
            # executor is None (CLI, tests), run inline.
            if executor is not None:
                # Block synchronously on the pool future. Under gevent
                # monkey-patching, concurrent.futures.Future.result()
                # cooperatively yields via threading primitives, so
                # other greenlets continue to make progress.
                self.level = executor.submit(
                    generate_level, params
                ).result()
            else:
                self.level = generate_level(params)
            logger.info(
                "Generated level depth=%d theme=%s "
                "(%dx%d, %d rooms)",
                depth, theme, self.level.width, self.level.height,
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
            "Hunger": Hunger(),
        })
        self._character = char

        # Give starting equipment (respecting slot costs)
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
        self.event_bus.subscribe(ItemSold, self._on_item_sold)
        self.event_bus.subscribe(VisualEffect, self._on_visual_effect)

        # Compute initial FOV
        self._update_fov()

        # Initialize renderer
        self.renderer.initialize()

        # Initialize GM for typed mode
        if self.mode == "typed" and self.backend:
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

    async def generate_intro_narration(self) -> None:
        """Generate the LLM intro narration for typed mode.

        Must be called after :meth:`initialize` when the game runs in
        typed mode with an LLM backend. Split from ``initialize`` so
        the latter can stay synchronous and be called safely from a
        gevent greenlet without wrapping it in ``asyncio.run``.
        """
        if not self._gm or not self._character or not self.level:
            return
        char = self._character
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
                    # Adventurers use level-scaled factory
                    if (placement.entity_id == "adventurer"
                            and placement.extra.get(
                                "adventurer_level")):
                        from nhc.entities.creatures.adventurer import (
                            create_adventurer_at_level,
                        )
                        components = create_adventurer_at_level(
                            placement.extra["adventurer_level"],
                        )
                    else:
                        components = EntityRegistry.get_creature(
                            placement.entity_id,
                        )
                    components["BlocksMovement"] = BlocksMovement()
                    if placement.extra.get("shop_stock"):
                        components["ShopInventory"] = ShopInventory(
                            stock=list(placement.extra["shop_stock"]),
                        )
                    if placement.extra.get("temple_services"):
                        from nhc.entities.components import (
                            TempleServices,
                        )
                        components["TempleServices"] = TempleServices(
                            services=list(
                                placement.extra["temple_services"],
                            ),
                        )
                elif placement.entity_type == "item":
                    components = EntityRegistry.get_item(placement.entity_id)
                    # Roll gold dice if present
                    if placement.extra.get("gold_dice"):
                        from nhc.utils.rng import roll_dice
                        amount = roll_dice(placement.extra["gold_dice"])
                        desc = components.get("Description")
                        if desc:
                            desc.name = f"{amount} {desc.name}"
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
                        if "reactivatable" in placement.extra:
                            trap.reactivatable = placement.extra[
                                "reactivatable"]
                else:
                    continue

                # Extract henchman starting items before entity creation
                starting_items = components.pop("_starting_items", None)

                components["Position"] = Position(
                    x=placement.x,
                    y=placement.y,
                    level_id=self.level.id,
                )
                eid = self.world.create_entity(components)

                # Give henchmen their starting equipment
                if starting_items:
                    self._give_starting_items(eid, starting_items)

            except KeyError:
                logger.warning(
                    "Unknown entity %s/%s at (%d,%d), skipping",
                    placement.entity_type, placement.entity_id,
                    placement.x, placement.y,
                )

    def _give_starting_items(
        self, entity_id: int, item_ids: list[str],
    ) -> None:
        """Create starting items for an NPC and auto-equip the best."""
        from nhc.ai.henchman_ai import auto_equip_best

        inv = self.world.get_component(entity_id, "Inventory")
        if not inv:
            return

        for item_id in item_ids:
            try:
                item_comps = EntityRegistry.get_item(item_id)
                eid = self.world.create_entity(item_comps)
                cost = _item_slot_cost(self.world, eid)
                used = _count_slots_used(self.world, inv)
                if used + cost > inv.max_slots:
                    self.world.destroy_entity(eid)
                    continue
                inv.slots.append(eid)
            except KeyError:
                logger.warning(
                    "Unknown starting item: %s", item_id,
                )

        auto_equip_best(self.world, entity_id)

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

        # Announce newly spotted creatures (skip hired henchmen)
        for eid, _, cpos in self.world.query("AI", "Position"):
            if cpos is None:
                continue
            hench = self.world.get_component(eid, "Henchman")
            if hench and hench.hired:
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
            # Render: hex mode routes to render_hex; dungeon mode keeps
            # the existing render() path unchanged.
            if self.world_mode.is_hex and self.hex_world is not None \
                    and self.level is None:
                self.renderer.render_hex(
                    self.hex_world,
                    self.hex_player_position,
                    self.turn,
                )
            else:
                self.renderer.render(
                    self.world, self.level, self.player_id, self.turn,
                )

            if self.mode == "typed":
                actions = await self._get_typed_actions()
            else:
                actions = await self._get_classic_actions()
            if actions and actions[0] == "disconnect":
                logger.info("Player disconnected, suspending game")
                _autosave(self, self.save_dir, blocking=True)
                self.running = False
                break
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

            # Haste: auto-repeat movement in the same direction
            if (player_status and player_status.hasted > 0
                    and isinstance(action, BumpAction)):
                haste_move = BumpAction(
                    actor=self.player_id,
                    dx=action.dx, dy=action.dy,
                )
                events += await self._resolve(haste_move)

            # Track when doors were opened (for auto-close)
            for ev in events:
                if isinstance(ev, DoorOpened):
                    tile = self.level.tile_at(ev.x, ev.y)
                    if tile:
                        tile.opened_at_turn = self.turn

            # Handle shop interaction (free action, no turn cost)
            for ev in events:
                if isinstance(ev, ShopMenuEvent):
                    await self._shop_interaction(ev.merchant)
                    break
                if isinstance(ev, TempleMenuEvent):
                    await self._temple_interaction(ev.priest)
                    break
                if isinstance(ev, HenchmanMenuEvent):
                    await self._henchman_interaction(ev.henchman)
                    break

            # Check win
            if self.won:
                delete_autosave(self.save_dir)
                self.renderer.show_end_screen(won=True, turn=self.turn)
                break

            # Advance turn
            self.turn += 1
            self.world.turn = self.turn

            # Process creature turns (visible creatures + henchmen)
            creature_actions = []
            for eid, ai, cpos in self.world.query("AI", "Position"):
                if cpos is None:
                    continue
                # Hired henchmen always act; others only if visible
                hench = self.world.get_component(eid, "Henchman")
                is_active_henchman = (
                    hench and hench.hired
                    and hench.owner == self.player_id
                )
                if is_active_henchman:
                    # Call for help when HP < 1/3
                    h_health = self.world.get_component(
                        eid, "Health",
                    )
                    if (h_health
                            and h_health.current
                            < h_health.maximum // 3
                            and not hench.called_for_help):
                        hench.called_for_help = True
                        h_desc = self.world.get_component(
                            eid, "Description",
                        )
                        h_name = h_desc.name if h_desc else "Henchman"
                        self.renderer.add_message(
                            t("henchman.call_for_help",
                              name=h_name),
                        )
                    elif (h_health
                          and h_health.current
                          >= h_health.maximum // 3):
                        hench.called_for_help = False
                else:
                    tile = self.level.tile_at(cpos.x, cpos.y)
                    if not tile or not tile.visible:
                        continue
                ai_action = decide_action(
                    eid, self.world, self.level, self.player_id,
                )
                if ai_action:
                    creature_actions.append((ai_action, eid if is_active_henchman else None))

            creature_events = []
            for ca, bonus_eid in creature_actions:
                creature_events += await self._resolve(ca)
                # Henchmen in a different room get a bonus move
                # to catch up to the player at double speed.
                if bonus_eid is not None:
                    from nhc.ai.henchman_ai import _find_room
                    hpos = self.world.get_component(
                        bonus_eid, "Position",
                    )
                    ppos = self.world.get_component(
                        self.player_id, "Position",
                    )
                    if hpos and ppos:
                        hr = _find_room(
                            self.level, hpos.x, hpos.y,
                        )
                        pr = _find_room(
                            self.level, ppos.x, ppos.y,
                        )
                        if hr != pr:
                            extra = decide_action(
                                bonus_eid, self.world,
                                self.level, self.player_id,
                            )
                            if extra:
                                creature_events += await (
                                    self._resolve(extra)
                                )
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
            self._tick_doors()
            self._tick_traps()
            self._tick_wand_recharge()
            self._tick_hunger()
            self._tick_stairs_proximity()
            self._tick_buried_markers()

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
                logger.info("Deleting autosave after death...")
                delete_autosave(self.save_dir)
                logger.info("Showing end screen...")
                self.renderer.show_end_screen(
                    won=False, turn=self.turn,
                    killed_by=self.killed_by,
                )
                logger.info("End screen dismissed, breaking game loop")
                break

            # Recompute FOV
            self._update_fov()

            # Autosave periodically (every 10 turns, non-blocking)
            if self.turn % 10 == 0:
                _autosave(self, self.save_dir, blocking=False)

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

    async def _shop_interaction(self, merchant_id: int) -> None:
        """Run the buy/sell/leave menu loop for a merchant."""
        from nhc.core.actions._shop import BuyAction, SellAction
        from nhc.rules.prices import buy_price, sell_price

        si = self.world.get_component(merchant_id, "ShopInventory")
        if not si:
            return

        _BUY = -1
        _SELL = -2

        while True:
            options: list[tuple[int, str]] = [
                (_BUY, t("shop.buy")),
                (_SELL, t("shop.sell")),
            ]
            choice = self.renderer.show_selection_menu(
                t("shop.welcome"), options,
            )
            if choice is None:
                break

            if choice == _BUY:
                if not si.stock:
                    self.renderer.add_message(t("shop.empty_stock"))
                    continue
                items: list[tuple[int, str]] = []
                for idx, item_id in enumerate(si.stock):
                    # Show appearance name for unidentified items
                    if (self._knowledge
                            and self._knowledge.is_identifiable(item_id)
                            and not self._knowledge.is_identified(item_id)):
                        name = self._knowledge.display_name(item_id)
                    else:
                        comps = EntityRegistry.get_item(item_id)
                        desc = comps.get("Description")
                        name = desc.name if desc else item_id
                    price = buy_price(item_id)
                    items.append((idx, f"{name} ({price}g)"))
                selected = self.renderer.show_selection_menu(
                    t("shop.buy"), items,
                )
                if selected is None:
                    continue
                # selected is the index into si.stock
                if selected < 0 or selected >= len(si.stock):
                    continue
                item_id = si.stock[selected]
                action = BuyAction(
                    actor=self.player_id,
                    merchant=merchant_id,
                    item_id=item_id,
                )
                if await action.validate(self.world, self.level):
                    events = await action.execute(self.world, self.level)
                    for ev in events:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                    # Disguise unidentified potions/scrolls
                    inv = self.world.get_component(
                        self.player_id, "Inventory",
                    )
                    if inv and inv.slots:
                        new_eid = inv.slots[-1]
                        new_comps = {
                            "Description": self.world.get_component(
                                new_eid, "Description"),
                            "Renderable": self.world.get_component(
                                new_eid, "Renderable"),
                        }
                        self._disguise_potion(new_comps, item_id)
                        if "_potion_id" in new_comps:
                            self.world.add_component(
                                new_eid, "_potion_id",
                                new_comps["_potion_id"],
                            )
                else:
                    reason = action.fail_reason
                    if reason == "cannot_afford":
                        self.renderer.add_message(
                            t("shop.cannot_afford",
                              price=buy_price(item_id)),
                        )
                    elif reason == "inventory_full":
                        self.renderer.add_message(
                            t("shop.inventory_full"),
                        )

            elif choice == _SELL:
                inv = self.world.get_component(
                    self.player_id, "Inventory",
                )
                if not inv or not inv.slots:
                    self.renderer.add_message(t("shop.nothing_to_sell"))
                    continue
                items = []
                for item_eid in inv.slots:
                    desc = self.world.get_component(item_eid, "Description")
                    reg = self.world.get_component(item_eid, "RegistryId")
                    name = desc.name if desc else "???"
                    item_id = reg.item_id if reg else "gold"
                    price = sell_price(item_id)
                    items.append((item_eid, f"{name} ({price}g)"))
                selected = self.renderer.show_selection_menu(
                    t("shop.sell"), items,
                )
                if selected is None:
                    continue
                action = SellAction(
                    actor=self.player_id,
                    merchant=merchant_id,
                    item_entity=selected,
                )
                if await action.validate(self.world, self.level):
                    events = await action.execute(self.world, self.level)
                    for ev in events:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                else:
                    reason = action.fail_reason
                    if reason == "equipped":
                        self.renderer.add_message(
                            t("shop.unequip_first"),
                        )

    async def _temple_interaction(self, priest_id: int) -> None:
        """Run the services + items menu loop for a priest."""
        from nhc.core.actions._shop import BuyAction
        from nhc.core.actions._temple import TempleServiceAction
        from nhc.rules.prices import buy_price, temple_service_price

        ts = self.world.get_component(priest_id, "TempleServices")
        if not ts:
            return

        _SERVICES = -1
        _GOODS = -2

        depth = self.level.depth

        while True:
            top: list[tuple[int, str]] = [
                (_SERVICES, t("temple.services")),
                (_GOODS, t("temple.goods")),
            ]
            choice = self.renderer.show_selection_menu(
                t("temple.welcome"), top,
            )
            if choice is None:
                break

            if choice == _SERVICES:
                svc_options: list[tuple[int, str]] = []
                for idx, sid in enumerate(ts.services):
                    price = temple_service_price(sid, depth)
                    label = t(f"temple.service.{sid}", price=price)
                    svc_options.append((idx, label))
                selected = self.renderer.show_selection_menu(
                    t("temple.services"), svc_options,
                )
                if selected is None or selected < 0 \
                        or selected >= len(ts.services):
                    continue
                sid = ts.services[selected]
                action = TempleServiceAction(
                    actor=self.player_id, priest=priest_id,
                    service_id=sid,
                )
                if await action.validate(self.world, self.level):
                    evs = await action.execute(self.world, self.level)
                    for ev in evs:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                else:
                    reason = action.fail_reason
                    msg_key = {
                        "cannot_afford": "temple.cannot_afford",
                        "no_curse": "temple.no_curse",
                        "already_full_hp": "temple.already_full_hp",
                        "already_blessed": "temple.already_blessed",
                    }.get(reason)
                    if msg_key:
                        if reason == "cannot_afford":
                            self.renderer.add_message(t(
                                msg_key,
                                price=temple_service_price(sid, depth),
                            ))
                        else:
                            self.renderer.add_message(t(msg_key))

            elif choice == _GOODS:
                si = self.world.get_component(priest_id, "ShopInventory")
                if not si or not si.stock:
                    self.renderer.add_message(t("temple.empty_stock"))
                    continue
                items: list[tuple[int, str]] = []
                for idx, item_id in enumerate(si.stock):
                    if (self._knowledge
                            and self._knowledge.is_identifiable(item_id)
                            and not self._knowledge.is_identified(item_id)):
                        name = self._knowledge.display_name(item_id)
                    else:
                        comps = EntityRegistry.get_item(item_id)
                        desc = comps.get("Description")
                        name = desc.name if desc else item_id
                    price = buy_price(item_id)
                    items.append((idx, f"{name} ({price}g)"))
                selected = self.renderer.show_selection_menu(
                    t("temple.goods"), items,
                )
                if selected is None or selected < 0 \
                        or selected >= len(si.stock):
                    continue
                item_id = si.stock[selected]
                action = BuyAction(
                    actor=self.player_id,
                    merchant=priest_id,
                    item_id=item_id,
                )
                if await action.validate(self.world, self.level):
                    evs = await action.execute(self.world, self.level)
                    for ev in evs:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                    inv = self.world.get_component(
                        self.player_id, "Inventory",
                    )
                    if inv and inv.slots:
                        new_eid = inv.slots[-1]
                        new_comps = {
                            "Description": self.world.get_component(
                                new_eid, "Description"),
                            "Renderable": self.world.get_component(
                                new_eid, "Renderable"),
                        }
                        self._disguise_potion(new_comps, item_id)
                        if "_potion_id" in new_comps:
                            self.world.add_component(
                                new_eid, "_potion_id",
                                new_comps["_potion_id"],
                            )
                else:
                    reason = action.fail_reason
                    if reason == "cannot_afford":
                        self.renderer.add_message(t(
                            "temple.cannot_afford",
                            price=buy_price(item_id),
                        ))
                    elif reason == "inventory_full":
                        self.renderer.add_message(t("shop.inventory_full"))

    async def _henchman_interaction(self, henchman_id: int) -> None:
        """Run the buy/sell/hire menu loop for an unhired henchman."""
        from nhc.core.actions._henchman import (
            HIRE_COST_PER_LEVEL,
            MAX_HENCHMEN,
            DismissAction,
            RecruitAction,
            _count_hired,
            get_hired_henchmen,
        )
        from nhc.rules.prices import buy_price, sell_price

        hench = self.world.get_component(henchman_id, "Henchman")
        if not hench or hench.hired:
            return

        hench_name = _entity_name(self.world, henchman_id)
        hire_cost = HIRE_COST_PER_LEVEL * hench.level

        _BUY = -1
        _SELL = -2
        _HIRE = -3

        while True:
            options: list[tuple[int, str]] = [
                (_BUY, t("henchman.buy")),
                (_SELL, t("henchman.sell")),
                (_HIRE, t("henchman.hire", cost=hire_cost)),
            ]
            choice = self.renderer.show_selection_menu(
                t("henchman.welcome"), options,
            )
            if choice is None:
                break

            if choice == _BUY:
                # Buy from henchman's inventory
                h_inv = self.world.get_component(
                    henchman_id, "Inventory",
                )
                if not h_inv or not h_inv.slots:
                    self.renderer.add_message(
                        t("henchman.nothing_to_buy", name=hench_name),
                    )
                    continue

                # Build item list with prices
                items: list[tuple[int, str]] = []
                for item_eid in h_inv.slots:
                    desc = self.world.get_component(
                        item_eid, "Description",
                    )
                    reg = self.world.get_component(
                        item_eid, "RegistryId",
                    )
                    name = desc.name if desc else "???"
                    item_id = reg.item_id if reg else "gold"
                    price = buy_price(item_id)
                    items.append((item_eid, f"{name} ({price}g)"))

                selected = self.renderer.show_selection_menu(
                    t("henchman.buy"), items,
                )
                if selected is None:
                    continue

                # Validate and execute buy
                reg = self.world.get_component(selected, "RegistryId")
                item_id = reg.item_id if reg else "gold"
                price = buy_price(item_id)
                player = self.world.get_component(
                    self.player_id, "Player",
                )

                if player.gold < price:
                    self.renderer.add_message(
                        t("henchman.cannot_afford_buy", price=price),
                    )
                    continue

                # Check player inventory space
                p_inv = self.world.get_component(
                    self.player_id, "Inventory",
                )
                if p_inv:
                    used = _count_slots_used(self.world, p_inv)
                    cost = _item_slot_cost(self.world, selected)
                    if used + cost > p_inv.max_slots:
                        self.renderer.add_message(
                            t("shop.inventory_full"),
                        )
                        continue

                # Transfer item
                h_inv.slots.remove(selected)
                p_inv.slots.append(selected)
                player.gold -= price
                hench.gold += price

                # Unequip from henchman if equipped
                h_equip = self.world.get_component(
                    henchman_id, "Equipment",
                )
                if h_equip:
                    for slot in ("weapon", "armor", "shield",
                                 "helmet", "ring_left", "ring_right"):
                        if getattr(h_equip, slot) == selected:
                            setattr(h_equip, slot, None)

                # Henchman re-evaluates equipment
                from nhc.ai.henchman_ai import auto_equip_best
                auto_equip_best(self.world, henchman_id)

                desc = self.world.get_component(selected, "Description")
                item_name = desc.name if desc else "item"
                self.renderer.add_message(
                    t("henchman.bought",
                      item=item_name, name=hench_name, price=price),
                )

            elif choice == _SELL:
                # Sell from player's inventory to henchman
                p_inv = self.world.get_component(
                    self.player_id, "Inventory",
                )
                if not p_inv or not p_inv.slots:
                    self.renderer.add_message(
                        t("shop.nothing_to_sell"),
                    )
                    continue

                items = []
                for item_eid in p_inv.slots:
                    desc = self.world.get_component(
                        item_eid, "Description",
                    )
                    reg = self.world.get_component(
                        item_eid, "RegistryId",
                    )
                    name = desc.name if desc else "???"
                    item_id = reg.item_id if reg else "gold"
                    price = sell_price(item_id)
                    items.append((item_eid, f"{name} ({price}g)"))

                selected = self.renderer.show_selection_menu(
                    t("henchman.sell"), items,
                )
                if selected is None:
                    continue

                # Cannot sell equipped items
                p_equip = self.world.get_component(
                    self.player_id, "Equipment",
                )
                if p_equip:
                    is_equipped = False
                    for slot in ("weapon", "armor", "shield",
                                 "helmet", "ring_left", "ring_right"):
                        if getattr(p_equip, slot) == selected:
                            is_equipped = True
                            break
                    if is_equipped:
                        self.renderer.add_message(
                            t("shop.unequip_first"),
                        )
                        continue

                reg = self.world.get_component(selected, "RegistryId")
                item_id = reg.item_id if reg else "gold"
                price = sell_price(item_id)

                # Check henchman can afford it
                if hench.gold < price:
                    self.renderer.add_message(
                        t("henchman.hench_cannot_afford",
                          name=hench_name),
                    )
                    continue

                # Check henchman inventory space
                h_inv = self.world.get_component(
                    henchman_id, "Inventory",
                )
                if h_inv:
                    used = _count_slots_used(self.world, h_inv)
                    cost = _item_slot_cost(self.world, selected)
                    if used + cost > h_inv.max_slots:
                        self.renderer.add_message(
                            t("henchman.give_full", name=hench_name),
                        )
                        continue

                # Transfer item
                p_inv.slots.remove(selected)
                h_inv.slots.append(selected)
                player = self.world.get_component(
                    self.player_id, "Player",
                )
                player.gold += price
                hench.gold -= price

                # Henchman auto-equips best gear
                from nhc.ai.henchman_ai import auto_equip_best
                auto_equip_best(self.world, henchman_id)

                desc = self.world.get_component(selected, "Description")
                item_name = desc.name if desc else "item"
                self.renderer.add_message(
                    t("henchman.sold",
                      item=item_name, name=hench_name, price=price),
                )

            elif choice == _HIRE:
                player = self.world.get_component(
                    self.player_id, "Player",
                )
                if player.gold < hire_cost:
                    self.renderer.add_message(
                        t("henchman.no_gold",
                          name=hench_name, cost=hire_cost),
                    )
                    continue

                # If party is full, offer to dismiss one
                hired_count = _count_hired(
                    self.world, self.player_id,
                )
                if hired_count >= MAX_HENCHMEN:
                    hired_ids = get_hired_henchmen(
                        self.world, self.player_id,
                    )
                    dismiss_opts: list[tuple[int, str]] = []
                    for hid in hired_ids:
                        name = _entity_name(self.world, hid)
                        dismiss_opts.append((hid, name))

                    to_dismiss = self.renderer.show_selection_menu(
                        t("henchman.dismiss_to_hire"),
                        dismiss_opts,
                    )
                    if to_dismiss is None:
                        continue

                    # Dismiss the selected henchman
                    dismiss = DismissAction(
                        actor=self.player_id,
                        henchman_id=to_dismiss,
                    )
                    if await dismiss.validate(
                        self.world, self.level,
                    ):
                        events = await dismiss.execute(
                            self.world, self.level,
                        )
                        for ev in events:
                            if isinstance(ev, MessageEvent):
                                self.renderer.add_message(ev.text)

                # Now recruit
                recruit = RecruitAction(
                    actor=self.player_id,
                    target=henchman_id,
                )
                if await recruit.validate(
                    self.world, self.level,
                ):
                    events = await recruit.execute(
                        self.world, self.level,
                    )
                    for ev in events:
                        if isinstance(ev, MessageEvent):
                            self.renderer.add_message(ev.text)
                    break  # Exit menu after hiring

    async def _get_classic_actions(self) -> list:
        """Classic mode: single keypress → single action."""
        intent, data = await self.renderer.get_input()
        if intent == "disconnect":
            return ["disconnect"]
        logger.debug("Input: intent=%s data=%s", intent, data)
        action = self._intent_to_action(intent, data)
        return [action] if action else []

    async def _get_typed_actions(self) -> list:
        """Typed mode: text input → GM interpret → action list."""
        result = await self.renderer.get_typed_input(
            self.world, self.level, self.player_id, self.turn,
        )

        # Movement keys bypass the GM pipeline
        if isinstance(result, tuple):
            intent, data = result
            if intent == "disconnect":
                return ["disconnect"]
            action = self._intent_to_action(intent, data)
            return [action] if action else []

        # Text input → GM pipeline
        typed_text = result
        if not typed_text:
            return []

        # Single-letter shortcuts: interpret as classic key commands
        # (e.g. "q" → quit, "g" → pickup, "s" → search, "i" → inventory)
        if len(typed_text) == 1:
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
            plan = parse_intent_keywords(
                typed_text, self.world, self.level, self.player_id,
            )
            return action_plan_to_actions(
                plan, self.player_id, self.world, self.level,
            )

    def _events_to_outcomes(self, events: list) -> list[dict]:
        """Convert ECS events to outcome dicts for the narrator."""
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

        if intent == "close_door":
            return game_input.find_close_door_action(self)

        if intent == "search":
            return SearchAction(actor=self.player_id)

        if intent == "dig":
            return game_input.find_dig_action(self, data)

        if intent == "descend":
            return DescendStairsAction(actor=self.player_id)

        if intent == "ascend":
            return AscendStairsAction(actor=self.player_id)

        if intent == "scroll_up":
            self.renderer.scroll_messages(1)
            return None

        if intent == "scroll_down":
            self.renderer.scroll_messages(-1)
            return None

        if intent == "give_item":
            return game_input.find_give_action(self)

        if intent == "dismiss_henchman":
            return game_input.find_dismiss_action(self)

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
            _autosave(self, self.save_dir, blocking=True)
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
            pos.x, pos.y, god_mode=self.god_mode,
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

    def _tick_doors(self) -> None:
        game_ticks.tick_doors(self)

    def _tick_traps(self) -> None:
        game_ticks.tick_traps(self)

    def _tick_wand_recharge(self) -> None:
        game_ticks.tick_wand_recharge(self)

    def _tick_hunger(self) -> None:
        game_ticks.tick_hunger(self)

    def _tick_stairs_proximity(self) -> None:
        game_ticks.tick_stairs_proximity(self)

    def _tick_buried_markers(self) -> None:
        """Remove expired BuriedMarker entities."""
        to_remove = []
        for eid, marker, _ in self.world.query(
            "BuriedMarker", "Position",
        ):
            if self.turn >= marker.expires_at_turn:
                to_remove.append(eid)
        for eid in to_remove:
            self.world.destroy_entity(eid)

    def _start_prefetch(self, depth: int) -> None:
        """Spawn a background thread to pre-generate a floor."""
        seed = (self.seed or 0) + depth * 997
        sv = _shape_variety_for_depth(self.shape_variety, depth)
        theme = theme_for_depth(depth)

        def _generate() -> None:
            try:
                rng = random.Random(seed)
                pf_w, pf_h = pick_map_size(rng, depth=depth)
                params = GenerationParams(
                    width=pf_w, height=pf_h,
                    depth=depth, shape_variety=sv, theme=theme,
                    seed=seed,
                )
                level = generate_level(params)
                self._prefetch_result = level
                self._prefetch_params = params
                logger.info("Prefetch complete for depth %d", depth)
            except Exception:
                logger.exception(
                    "Prefetch thread failed for depth %d", depth)
            finally:
                self._prefetch_thread = None

        self._prefetch_depth = depth
        self._prefetch_thread = threading.Thread(
            target=_generate, daemon=True,
        )
        self._prefetch_thread.start()
        logger.info("Prefetch started for depth %d", depth)

    def _on_level_entered(self, event: LevelEntered) -> None:
        """Transition to a dungeon level (ascending or descending)."""
        new_depth = event.depth
        old_depth = self.level.depth
        ascending = new_depth < old_depth
        logger.info("%s to depth %d",
                     "Ascending" if ascending else "Descending", new_depth)

        # Save current floor state (level + non-player entities)
        self._save_floor()

        # Remove all non-party entities from the world
        keep_ids = self._party_keep_ids()
        for eid in list(self.world._entities):
            if eid not in keep_ids:
                self.world.destroy_entity(eid)

        # Restore cached floor, use prefetch, or generate new one
        if self._cache_key(new_depth) in self._floor_cache:
            self._restore_floor(new_depth)
            logger.info("Restored cached floor at depth %d", new_depth)
        elif (self._prefetch_depth == new_depth
              and self._prefetch_result is not None):
            # Wait for prefetch thread if still running
            if self._prefetch_thread is not None:
                self._prefetch_thread.join()
                self._prefetch_thread = None
            self.level = self._prefetch_result
            self.generation_params = self._prefetch_params
            self._prefetch_result = None
            self._prefetch_params = None
            self._prefetch_depth = None
            self._spawn_level_entities()
            logger.info("Used prefetched floor at depth %d", new_depth)
        else:
            # Cancel any in-flight prefetch for a different depth
            if self._prefetch_thread is not None:
                self._prefetch_thread.join()
                self._prefetch_thread = None
            self._prefetch_result = None
            self._prefetch_params = None
            self._prefetch_depth = None
            seed = (self.seed or 0) + new_depth * 997
            sv = _shape_variety_for_depth(self.shape_variety, new_depth)
            theme = theme_for_depth(new_depth)
            ft_rng = random.Random(seed)
            ft_w, ft_h = pick_map_size(ft_rng, depth=new_depth)
            params = GenerationParams(
                width=ft_w, height=ft_h,
                depth=new_depth, shape_variety=sv, theme=theme,
                seed=seed,
            )
            self.generation_params = params
            self.level = generate_level(params)
            self._spawn_level_entities()

        # Place player at the appropriate stairs (or random if fell)
        fell = getattr(event, "fell", False)
        if fell:
            # Fell through trapdoor — land on a random floor tile
            placed = self._place_player_random_floor()
        else:
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

        # Spawn items that fell with the player (dig-floor hole)
        fallen_items = getattr(event, "fallen_items", [])
        if fallen_items:
            pos = self.world.get_component(self.player_id, "Position")
            if pos:
                from nhc.entities.registry import EntityRegistry
                for item_id in fallen_items:
                    try:
                        comps = EntityRegistry.get_item(item_id)
                        comps["Position"] = Position(
                            x=pos.x, y=pos.y,
                            level_id=self.level.id,
                        )
                        self.world.create_entity(comps)
                    except KeyError:
                        pass

        # Place hired henchmen near the player on the new floor
        self._place_henchmen_near_player()

        self._seen_creatures.clear()
        self._update_fov()

        # Atmospheric flavour message for the new level
        theme = self.level.metadata.theme if self.level.metadata else "dungeon"
        roll = __import__("nhc.utils.rng", fromlist=["roll_dice"]).roll_dice("1d12")
        atmo_key = f"atmosphere.{theme}.{roll}"
        atmo = t(atmo_key)
        if atmo != atmo_key:
            self.renderer.add_message(atmo)

        # Notify the web client to load the new floor
        if hasattr(self.renderer, 'send_floor_change'):
            cached = self._svg_cache.get(new_depth)
            self.renderer.send_floor_change(
                self.level, self.world, self.player_id,
                self.turn, seed=self.seed or 0,
                floor_svg=cached[1] if cached else None,
                floor_svg_id=cached[0] if cached else None,
            )
            # Store the rendered SVG for future revisits
            if not cached:
                self._svg_cache[new_depth] = (
                    self.renderer.floor_svg_id,
                    self.renderer.floor_svg,
                )

    def _place_player_random_floor(self) -> bool:
        """Place player on a random walkable floor tile.

        Used when the player falls through a trapdoor and lands
        at an unpredictable spot.  Returns True if placed.
        """
        from nhc.utils.rng import get_rng
        rng = get_rng()
        floors: list[tuple[int, int]] = []
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if (tile and tile.terrain == Terrain.FLOOR
                        and not tile.feature
                        and not tile.is_corridor):
                    floors.append((x, y))
        if not floors:
            return False
        fx, fy = rng.choice(floors)
        pos = self.world.get_component(self.player_id, "Position")
        if pos:
            pos.x = fx
            pos.y = fy
            pos.level_id = self.level.id
        return True

    def _place_henchmen_near_player(self) -> None:
        """Place hired henchmen on walkable tiles near the player."""
        ppos = self.world.get_component(self.player_id, "Position")
        if not ppos:
            return
        # Collect adjacent walkable tiles
        candidates: list[tuple[int, int]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = ppos.x + dx, ppos.y + dy
                tile = self.level.tile_at(nx, ny)
                if tile and tile.walkable:
                    candidates.append((nx, ny))

        idx = 0
        for eid, hench in self.world.query("Henchman"):
            if not hench.hired or hench.owner != self.player_id:
                continue
            hpos = self.world.get_component(eid, "Position")
            if not hpos:
                continue
            if idx < len(candidates):
                hpos.x, hpos.y = candidates[idx]
            else:
                # Fallback: same tile as player
                hpos.x, hpos.y = ppos.x, ppos.y
            hpos.level_id = self.level.id
            idx += 1

    def _party_keep_ids(self) -> set[int]:
        """Entity IDs that travel with the player across floors."""
        keep = {self.player_id}
        player_inv = self.world.get_component(
            self.player_id, "Inventory",
        )
        if player_inv:
            keep.update(player_inv.slots)
        # Hired henchmen and their inventory
        for eid, hench in self.world.query("Henchman"):
            if hench.hired and hench.owner == self.player_id:
                keep.add(eid)
                h_inv = self.world.get_component(eid, "Inventory")
                if h_inv:
                    keep.update(h_inv.slots)
        return keep

    def _save_floor(self) -> None:
        """Save the current floor's level and entities to cache."""
        depth = self.level.depth
        keep_ids = self._party_keep_ids()

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

        self._floor_cache[self._cache_key(depth)] = (self.level, entity_data)
        logger.info("Saved floor depth %d (%d entities cached)",
                     depth, len(entity_data))

    def _restore_floor(self, depth: int) -> None:
        """Restore a cached floor's level and entities.

        Preserves original entity IDs so cross-references (inventory
        slots, equipment pointers) remain valid.
        """
        level, entity_data = self._floor_cache[self._cache_key(depth)]
        self.level = level

        for eid, comps in entity_data.items():
            self.world._entities.add(eid)
            for comp_type, comp in comps.items():
                self.world.add_component(eid, comp_type, comp)
            # Keep _next_id above all restored IDs
            if eid >= self.world._next_id:
                self.world._next_id = eid + 1

    def _on_creature_died(self, event: CreatureDied) -> None:
        """Award XP when the player or a henchman kills a creature."""
        from nhc.core.actions._henchman import get_hired_henchmen
        from nhc.rules.advancement import XP_PER_HP

        # Award XP if killer is player or a hired henchman
        is_player_kill = event.killer == self.player_id
        is_henchman_kill = False
        if not is_player_kill:
            killer_hench = self.world.get_component(
                event.killer, "Henchman",
            )
            is_henchman_kill = (
                killer_hench is not None
                and killer_hench.hired
                and killer_hench.owner == self.player_id
            )

        if not is_player_kill and not is_henchman_kill:
            return

        # Full XP to player
        xp = award_xp_direct(
            self.world, self.player_id, event.max_hp,
        )
        if xp > 0:
            self.renderer.add_message(t("game.xp_gained", xp=xp))

        level_msgs = check_level_up(self.world, self.player_id)
        for msg in level_msgs:
            self.renderer.add_message(msg)

        # Half XP to each hired henchman
        half_xp = (event.max_hp * XP_PER_HP) // 2
        if half_xp > 0:
            for hid in get_hired_henchmen(self.world, self.player_id):
                # Don't award XP to the creature that just died
                if hid == event.entity:
                    continue
                hench = self.world.get_component(hid, "Henchman")
                if not hench:
                    continue
                hench.xp += half_xp
                self._check_henchman_level_up(hid, hench)

    def _check_henchman_level_up(self, hid: int, hench) -> None:
        """Check if a henchman should level up and handle payment."""
        from nhc.core.actions._henchman import HIRE_COST_PER_LEVEL
        from nhc.rules.advancement import (
            ABILITIES_PER_LEVEL, MAX_ABILITY_BONUS, MAX_LEVEL,
            XP_PER_LEVEL, _pick_lowest_abilities,
        )
        from nhc.utils.rng import roll_dice

        while (hench.xp >= hench.xp_to_next
               and hench.level < MAX_LEVEL):
            hench.level += 1
            hench.xp_to_next = hench.level * XP_PER_LEVEL

            # HP: Knave reroll
            health = self.world.get_component(hid, "Health")
            hp_gain = 0
            if health:
                rolled = roll_dice(f"{hench.level}d8")
                if rolled > health.maximum:
                    hp_gain = rolled - health.maximum
                else:
                    hp_gain = 1
                health.maximum += hp_gain
                health.current += hp_gain

            # Raise 3 lowest abilities
            stats = self.world.get_component(hid, "Stats")
            if stats:
                abilities = _pick_lowest_abilities(
                    stats, ABILITIES_PER_LEVEL,
                )
                for ability in abilities:
                    old_val = getattr(stats, ability)
                    if old_val < MAX_ABILITY_BONUS:
                        setattr(stats, ability, old_val + 1)
                # Update inventory capacity
                inv = self.world.get_component(hid, "Inventory")
                if inv:
                    inv.max_slots = stats.constitution + 10

            desc = self.world.get_component(hid, "Description")
            name = desc.name if desc else "Henchman"
            cost = HIRE_COST_PER_LEVEL * hench.level
            player = self.world.get_component(
                self.player_id, "Player",
            )

            if player and player.gold >= cost:
                player.gold -= cost
                self.renderer.add_message(
                    t("henchman.levelup", name=name,
                      level=hench.level, cost=cost),
                )
                self.renderer.add_message(
                    t("henchman.levelup_paid", name=name,
                      level=hench.level),
                )
            else:
                # Can't pay — henchman leaves
                self.renderer.add_message(
                    t("henchman.levelup_left", name=name,
                      cost=cost),
                )
                hench.hired = False
                hench.owner = None
                if not self.world.has_component(
                    hid, "BlocksMovement",
                ):
                    self.world.add_component(
                        hid, "BlocksMovement", BlocksMovement(),
                    )

    def _on_visual_effect(self, event: VisualEffect) -> None:
        """Forward visual effects to the renderer (web client)."""
        if hasattr(self.renderer, "send_effect"):
            self.renderer.send_effect(event.effect, event.x, event.y)

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

    def _on_item_sold(self, event: ItemSold) -> None:
        """Identify items when sold at a shop."""
        self._identify_potion(real_id=event.item_id)

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
