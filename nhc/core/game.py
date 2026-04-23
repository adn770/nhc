"""Game loop and session management."""

from __future__ import annotations

import logging
import random
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from nhc.ai.behavior import decide_action
from nhc.core import game_input, game_ticks
from nhc.core.death import DeathHandler
from nhc.core.hex_session import HexSession
from nhc.core.npc_interactions import NpcInteractions
from nhc.core.actions import (
    AscendStairsAction,
    BumpAction,
    DescendStairsAction,
    LeaveSiteAction,
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
    LeaveSiteRequested,
    LevelEntered,
    MessageEvent,
    PlayerDied,
    HenchmanMenuEvent,
    ShopMenuEvent,
    TempleMenuEvent,
    TerrainChanged,
    TrapTriggered,
    VisualEffect,
)
from nhc.dungeon.generator import GenerationParams, pick_map_size
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.themes import theme_for_depth
from nhc.dungeon.loader import get_player_start, load_level
from nhc.dungeon.model import Level, SurfaceType, Terrain
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
from nhc.hexcrawl.generator import (
    generate_continental_world,
)
from nhc.hexcrawl.mode import Difficulty, GameMode, WorldType
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
from nhc.rules.chargen import generate_character, trait_text
from nhc.rules.identification import ALL_IDS, ItemKnowledge
from nhc.utils.fov import compute_fov
from nhc.utils.rng import get_rng, get_seed, set_seed

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from concurrent.futures import Executor
    from nhc.core.actions import Action
    from nhc.utils.llm import LLMBackend

FOV_RADIUS = 5
# Outdoor site surfaces (town, keep, ruin, cottage, temple courtyards
# and sub-hex family sites) use a substantially larger sight radius so
# wandering villagers don't pop in and out of the dungeon-scale FOV
# disc. Flagged by ``LevelMetadata.prerevealed``.
FOV_RADIUS_SURFACE = 12


def _fov_radius_for_level(level) -> int:
    """Return the sight radius appropriate for *level*.

    Prerevealed surfaces see farther; every other level (dungeon,
    building interior) uses the default dungeon radius.
    """
    meta = getattr(level, "metadata", None)
    if meta is not None and getattr(meta, "prerevealed", False):
        return FOV_RADIUS_SURFACE
    return FOV_RADIUS

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


# Move-direction that represents stepping *through* a door, keyed
# by ``Tile.door_side``. Used by :meth:`Game._maybe_traverse_building_door`
# to reject lateral steps that end on an open door tile but walk
# along the wall instead of crossing the edge.
_DOOR_SIDE_CROSS_DIR: dict[str, tuple[int, int]] = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}


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
        style: str = "classic",
        god_mode: bool = False,
        reset: bool = False,
        shape_variety: float = DEFAULT_SHAPE_VARIETY,
        save_dir: Path | None = None,
        world_type: WorldType = WorldType.DUNGEON,
        difficulty: Difficulty = Difficulty.MEDIUM,
    ) -> None:
        self.world = World()
        self.event_bus = EventBus()
        self.backend = backend
        self.seed = seed
        self.style = style
        self.world_type: WorldType = world_type
        self.difficulty: Difficulty = difficulty
        self.god_mode = god_mode
        self.tester_mode = False
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
        # level.id → (uuid, svg). Keyed by Level.id rather than
        # depth because site-surface Levels share depth=0 with
        # overland dungeon floors, and a building's ground floor
        # shares depth=1 with its host site's interior, so a
        # depth-keyed cache would serve the wrong SVG to a
        # building interior after the surface got rendered.
        self._svg_cache: dict[str, tuple[str, str]] = {}
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
        # Encounter pipeline scratch: set by apply_hex_step when a
        # roll surfaces a Fight/Flee/Talk prompt, consumed by
        # resolve_encounter. See nhc.hexcrawl.encounter_pipeline.
        self.pending_encounter = None
        self._encounter_rng = None
        # Set when the player is inside a cave dungeon so
        # _cache_key can route Floor 2 to the cluster's shared
        # cache slot. Cleared on exit to hex overland.
        self._active_cave_cluster: "HexCoord | None" = None
        # Set by building-generator site assemblers (mansion, keep,
        # town) when the player enters a multi-building site so
        # future door-transition code can reach the sibling
        # buildings without re-running the assembler. None for
        # single-building sites (tower) and dungeon features.
        self._active_site = None
        # Set when the player enters a sub-hex-keyed site (farm
        # minor, shrine, well, etc.) so ``_cache_key`` routes the
        # floor under the ("sub", ...) namespace and the leave-site
        # mechanic can restore ``exploring_sub_hex`` to where the
        # player entered from. Cleared on exit to the flower.
        self._active_sub_hex: "HexCoord | None" = None
        # Sub-hex floor cache with bounded LRU eviction + mutation
        # persistence. Lazy — built on first sub-hex entry once we
        # know the player id / save dir. See nhc.core.sub_hex_cache.
        self._sub_hex_cache = None
        # Set when the player has descended from a building ground
        # floor into that building's descent ``DungeonRef``. Holds
        # the Building the descent originates from and the tile on
        # its ground floor to land back on when the player ascends.
        # Cleared on ascent or overland exit.
        self._active_descent_building: "object | None" = None
        self._active_descent_return_tile: (
            "tuple[int, int] | None"
        ) = None
        # Per-level ECS component stash, keyed by Level.id, used by
        # site door crossings to preserve creatures / items across
        # level swaps. An entry is populated when the player leaves
        # a level, consumed when they swap back in. Cleared on
        # overland exit.
        self._site_level_entities: dict[int, dict] = {}
        # Maps "q_r" → (x, y) for each cluster member's stairs_up
        # on the shared Floor 2. Populated by _generate_cave_floor2,
        # consumed by the player-placement branch in
        # _on_level_entered when descending to Floor 2.
        self._cave_floor2_stairs: dict[str, tuple[int, int]] = {}
        # Voronoi-style sector partition of a shared underworld
        # floor: floor tile (x, y) → the cluster member whose
        # stairs_up is nearest. Lets _on_level_entered update
        # hex_player_position when the player ascends through a
        # sector other than the one they descended from.
        self._underworld_sector_map: (
            "dict[tuple[int, int], HexCoord]"
        ) = {}
        # Probability of a per-step encounter roll firing in hex
        # mode. Matches DEFAULT_ENCOUNTER_RATE at startup; the
        # _maybe_stage_encounter path swaps to per-biome rates
        # when the attribute has not been nudged by a caller.
        # _default_encounter_rate is the sentinel we test against
        # to detect that "unchanged" state.
        from nhc.hexcrawl.encounter_pipeline import (
            DEFAULT_ENCOUNTER_RATE,
        )
        self._default_encounter_rate: float = DEFAULT_ENCOUNTER_RATE
        self.encounter_rate: float = DEFAULT_ENCOUNTER_RATE

        self._npc = NpcInteractions(self)
        self._death = DeathHandler(self)
        self._hex = HexSession(self)

    def set_god_mode(self, enabled: bool) -> None:
        """Toggle god mode live.

        Identifies all items. The ``encounters_disabled`` flag
        follows the god-mode state so any future encounter
        roll site can short-circuit when the flag is set.
        Hex fog of war is not touched — use the debug panel's
        fog layer toggle to reveal the full map visually.
        """
        self.god_mode = enabled
        if enabled and self._knowledge:
            for item_id in ALL_IDS:
                self._knowledge.identify(item_id)

    @property
    def encounters_disabled(self) -> bool:
        """``True`` when hex-step encounter rolls should be
        skipped. Currently tied to god mode; a later milestone
        can broaden it (e.g. a safe-travel buff) without touching
        the callers."""
        return bool(self.god_mode)

    def _cache_key(self, depth: int) -> "int | tuple":
        """Floor-cache key for a given ``depth``.

        In pure dungeon mode the key is the depth integer, matching
        the historical behaviour byte-for-byte. In hex mode the key
        bundles the hex coordinate of the feature whose dungeon the
        player is currently exploring, so two different hexes' caves
        at the same depth are cached independently.

        Cave clusters share Floor 2: when ``_active_cave_cluster``
        is set and ``depth >= 2``, the key uses the cluster's
        canonical coord instead of the player's current hex, so
        every cave entrance in the cluster resolves to the same
        cached Floor 2.

        Building descents (ruin, keep cellar, tower basement) use
        a site-kind-keyed tuple so ruin descent floors don't
        collide with hex-wide floors at the same depth: when
        ``_active_descent_building`` is set and ``depth >= 2`` the
        key becomes ``("descent", site_kind, q, r, bi,
        floor_index)``. The format matches the one stamped by
        :meth:`_enter_building_descent` for the first descent
        floor so all descent floors share one cache namespace.

        Degrades to the integer-depth key when ``hex_player_position``
        is not yet set (pre-initialize or test setup).
        """
        if self.world_type is WorldType.HEXCRAWL and self.hex_player_position is not None:
            if self._active_sub_hex is not None:
                coord = self.hex_player_position
                sub = self._active_sub_hex
                return (
                    "sub", coord.q, coord.r, sub.q, sub.r, depth,
                )
            if (
                depth >= 2
                and self._active_descent_building is not None
                and self._active_site is not None
            ):
                coord = self.hex_player_position
                bi = next(
                    i for i, b in enumerate(self._active_site.buildings)
                    if b.id == self._active_descent_building.id
                )
                return (
                    "descent", self._active_site.kind,
                    coord.q, coord.r, bi, depth - 1,
                )
            if depth >= 2 and self._active_cave_cluster is not None:
                cc = self._active_cave_cluster
                return (cc.q, cc.r, depth)
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
        if not self.world_type is WorldType.HEXCRAWL or self.hex_world is None:
            return False
        coord = self.hex_player_position
        if coord is None:
            return False
        cell = self.hex_world.get_cell(coord)
        if cell is None or cell.dungeon is None:
            return False

        from nhc.hexcrawl.seed import dungeon_seed

        # Settlement routing: every procedural:settlement hex --
        # hamlet, village, town, city -- flows through the town
        # site assembler. size_class is forwarded so the assembler
        # picks the right footprint / palisade / building count
        # preset.
        if (cell.dungeon.site_kind is None
                and cell.dungeon.template.startswith(
                    "procedural:settlement",
                )):
            cell.dungeon.site_kind = "town"

        # Building-generator sites take precedence over template
        # routing. "tower" and "mansion" are live in this step;
        # other site_kinds still fall through to the template
        # pipeline below until their engine wiring lands.
        if cell.dungeon.site_kind == "tower":
            self._active_cave_cluster = None
            if await self._enter_tower_site(coord):
                return True
        if cell.dungeon.site_kind == "mansion":
            self._active_cave_cluster = None
            if await self._enter_mansion_site(coord):
                return True
        if cell.dungeon.site_kind == "farm":
            self._active_cave_cluster = None
            if await self._enter_farm_site(coord):
                return True
        if cell.dungeon.site_kind in (
            "keep", "town", "temple", "cottage", "ruin",
        ):
            self._active_cave_cluster = None
            if await self._enter_walled_site(
                coord, cell.dungeon.site_kind,
            ):
                return True

        template = cell.dungeon.template
        is_settlement = template.startswith("procedural:settlement")
        is_cave = template.startswith("procedural:cave")

        # Track the cave cluster so _cache_key routes Floor 2
        # to the shared slot for the whole cluster.
        if is_cave and cell.dungeon.cluster_id is not None:
            self._active_cave_cluster = cell.dungeon.cluster_id
        else:
            self._active_cave_cluster = None

        depth = 1
        cache_key = self._cache_key(depth)
        if cache_key in self._floor_cache:
            level, _ = self._floor_cache[cache_key]
            self.level = level
            self._place_player_at_stairs_up()
            self._place_expedition_henchmen(is_settlement=is_settlement)
            self._update_fov()
            self._notify_floor_change(depth)
            return True

        seed = dungeon_seed(self.seed or 0, coord, template)
        if is_cave:
            # Cave Floor 1: smaller cellular cave with stairs_down
            # linking to Floor 2.
            params = GenerationParams(
                width=40, height=25, depth=depth,
                shape_variety=0.3, theme="cave", seed=seed,
            )
            self.generation_params = params
            self.level = generate_level(params)
            self._add_stairs_down_to_level()
        else:
            sv = _shape_variety_for_depth(self.shape_variety, depth)
            if template.startswith("procedural:crypt"):
                theme = "crypt"
            else:
                theme = theme_for_depth(depth)
            map_w, map_h = pick_map_size(get_rng(), depth=depth)
            params = GenerationParams(
                width=map_w, height=map_h, depth=depth,
                shape_variety=sv, theme=theme, seed=seed,
                template=template,
            )
            self.generation_params = params
            self.level = generate_level(params)
        # Set faction on level metadata from DungeonRef (used by
        # populator for faction-specific creature pools).
        if (self.level and self.level.metadata
                and cell.dungeon.faction):
            self.level.metadata.faction = cell.dungeon.faction
        # Spawn NPCs / items declared by the generator (merchant,
        # priest and recruitable adventurer for a town; future
        # populators for cave/ruin dungeons hook in the same way).
        self._spawn_level_entities()
        # Cache the freshly generated floor under the (q, r, depth)
        # key so re-entry skips regeneration. The empty dict is a
        # placeholder -- hex-side exits don't yet serialize entity
        # components, but cache re-entry reuses whoever survived in
        # the ECS world (merchants stay dead, hired henchmen follow).
        self._floor_cache[cache_key] = (self.level, {})
        self._place_player_at_stairs_up()
        self._place_expedition_henchmen(is_settlement=is_settlement)
        # Compute FOV before sending the floor so the client
        # receives visible tiles on entry (not a black map).
        self._update_fov()
        self._notify_floor_change(depth)
        return True

    async def enter_sub_hex_family_site(
        self,
        macro: "HexCoord",
        sub: "HexCoord",
        family: str,
        feature,
        tier,
        biome,
    ) -> bool:
        """Enter a family-generated sub-hex site at ``sub`` of ``macro``.

        Routes the six new family generators (wayside, sacred,
        inhabited_settlement, animal_den, natural_curiosity,
        undead) through the sub-hex floor cache. The level is
        generated from a per-sub-hex seed and cached under a
        ("sub", mq, mr, sq, sr, depth) key so re-entry is O(1).

        Sets ``_active_sub_hex`` so ``_cache_key`` routes
        subsequent lookups to the sub-hex namespace; the overland
        day clock stays frozen for the duration of the visit.
        """
        from nhc.hexcrawl.seed import dungeon_seed
        from nhc.hexcrawl.sub_hex_sites import (
            SiteTier,
            generate_animal_den_site,
            generate_inhabited_settlement_site,
            generate_natural_curiosity_site,
            generate_sacred_site,
            generate_undead_site,
            generate_wayside_site,
        )

        family_dispatch = {
            "wayside": generate_wayside_site,
            "sacred": generate_sacred_site,
            "inhabited_settlement": (
                generate_inhabited_settlement_site
            ),
            "animal_den": generate_animal_den_site,
            "natural_curiosity": generate_natural_curiosity_site,
            "undead": generate_undead_site,
        }
        generator = family_dispatch.get(family)
        if generator is None:
            return False

        self._active_sub_hex = sub
        self._active_cave_cluster = None
        self._active_site = None
        self._active_descent_building = None
        depth = 1
        cache_key = self._cache_key(depth)

        # Lazy-init the sub-hex LRU / mutation cache on first family
        # entry so pure-dungeon runs never pay for the scaffolding.
        self._ensure_sub_hex_cache()

        cached = (
            self._sub_hex_cache.get(cache_key)
            if self._sub_hex_cache is not None else None
        )
        if cached is not None:
            self.level = cached
            self._place_player_on_sub_hex_entry()
            self._update_fov()
            self._notify_floor_change(depth)
            return True

        base_template = f"family:{family}"
        seed = dungeon_seed(
            self.seed or 0, macro, base_template, sub=sub,
        )
        site = generator(
            feature=feature, biome=biome, seed=seed, tier=tier,
        )
        self.level = site.level
        if (self.level and self.level.metadata and site.faction):
            self.level.metadata.faction = site.faction
        # Load persisted mutations from a previous eviction and
        # replay them onto the regenerated level before the populator
        # runs (so looted items / killed creatures are filtered out
        # of the population walk).
        persisted_mutations: dict = {}
        if self._sub_hex_cache is not None:
            persisted_mutations = self._sub_hex_cache.load_mutations(
                cache_key,
            )
            self._apply_sub_hex_mutations_to_level(
                self.level, persisted_mutations,
            )
            self._sub_hex_cache.store(
                cache_key, self.level, mutations=persisted_mutations,
            )
        else:
            # Test paths without a save_dir still need the Level
            # addressable for the re-entry cache-hit path.
            self._floor_cache[cache_key] = (self.level, {})
        self._sub_hex_entry_tile = site.entry_tile
        # Purge stale ECS entities tied to this level_id before the
        # populator runs. Regeneration reuses the same deterministic
        # level.id, so entities from an earlier visit (items, NPCs,
        # creatures) would otherwise double up with the fresh
        # population walk. The player and hired henchmen live on
        # their own level_id ("overland") after the exit so they
        # aren't touched here.
        self._purge_entities_on_level(self.level.id)
        from nhc.core.sub_hex_populator import populate_sub_hex_site
        populate_sub_hex_site(
            self.world, site, mutations=persisted_mutations,
        )
        self._place_player_on_sub_hex_entry()
        self._update_fov()
        self._notify_floor_change(depth)
        return True

    def _purge_entities_on_level(self, level_id: str) -> None:
        """Destroy every ECS entity whose Position sits on ``level_id``.

        Skips the player and hired henchmen (they carry their own
        level id after the exit). Called before the sub-hex populator
        runs so regenerated levels don't stack duplicates on top of
        stale entities from a prior visit.
        """
        to_destroy: list[int] = []
        for eid, pos in self.world.query("Position"):
            if pos.level_id != level_id:
                continue
            if eid == self.player_id:
                continue
            hench = self.world.get_component(eid, "Henchman")
            if hench and hench.hired:
                continue
            to_destroy.append(eid)
        for eid in to_destroy:
            self.world.destroy_entity(eid)

    def _apply_sub_hex_mutations_to_level(
        self, level, mutations: dict,
    ) -> None:
        """Replay persisted door / terrain mutations onto a freshly
        regenerated sub-hex level. Looted items and killed creatures
        are filtered inside the populator; this method only touches
        map tiles."""
        doors = mutations.get("doors") or {}
        for coord_str, state in doors.items():
            try:
                x_str, y_str = coord_str.split(",", 1)
                x, y = int(x_str), int(y_str)
            except ValueError:
                continue
            tile = level.tile_at(x, y)
            if tile is None:
                continue
            # All recorded states (open/forced/picked) collapse to
            # an open door tile on replay — the state distinction
            # is for audit only (U4).
            tile.feature = "door_open"

        terrain = mutations.get("terrain") or {}
        for coord_str, kind in terrain.items():
            if kind != "dug":
                continue
            try:
                x_str, y_str = coord_str.split(",", 1)
                x, y = int(x_str), int(y_str)
            except ValueError:
                continue
            tile = level.tile_at(x, y)
            if tile is None:
                continue
            tile.terrain = Terrain.FLOOR
            tile.feature = None
            tile.surface_type = SurfaceType.CORRIDOR
            tile.dug_wall = True

    def _ensure_sub_hex_cache(self) -> None:
        """Construct :attr:`_sub_hex_cache` on first family-site entry.

        Only a game with a ``save_dir`` gets a manager — without one
        there is no place to persist evicted mutation records. Pure
        dungeon runs and transient tests stay on the in-memory
        ``_floor_cache`` fallback in ``enter_sub_hex_family_site``.
        """
        if self._sub_hex_cache is not None or self.save_dir is None:
            return
        from nhc.core.sub_hex_cache import SubHexCacheManager

        self._sub_hex_cache = SubHexCacheManager(
            storage_dir=self.save_dir,
            player_id="game",
        )

    def _place_player_on_sub_hex_entry(self) -> None:
        """Drop the player onto the family site's canonical front door."""
        if self.level is None:
            return
        entry = getattr(self, "_sub_hex_entry_tile", None)
        if entry is None:
            entry = (1, 1)
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x, pos.y = entry
            pos.level_id = self.level.id

    # Days between rumor refreshes on a revisit. Fresh leads
    # don't appear every single day (that would trivialize
    # exploration), but after three days the innkeepers have had
    # time to hear new stories.
    _RUMOR_REFRESH_COOLDOWN_DAYS: int = 3

    def _maybe_seed_rumors(self, seed: int) -> None:
        """Top up :attr:`HexWorld.active_rumors` on town entry.

        Rules:

        * Empty pool -> seed three fresh rumors.
        * Non-empty pool + cooldown not yet elapsed -> no-op
          (player hasn't revisited often enough to hear new news).
        * Non-empty pool + cooldown elapsed -> append three new
          rumors onto whatever the player hasn't consumed yet.

        God mode uses the truthful generator so the debug player
        never gets a false lead.
        """
        if self.hex_world is None:
            return
        from nhc.hexcrawl.rumor_pool import seed_rumor_pool, top_up_rumor_pool
        from nhc.i18n import current_lang

        lang = current_lang()
        world = self.hex_world
        if not world.active_rumors:
            seed_rumor_pool(
                world, seed=seed, lang=lang, count=3,
                god_mode=self.god_mode,
            )
            world.last_rumor_day = world.day
            return
        # Non-empty: honour the cooldown.
        days_since = world.day - world.last_rumor_day
        if days_since < self._RUMOR_REFRESH_COOLDOWN_DAYS:
            return
        # Append fresh rumors on top of unconsumed ones. Mix the
        # seed with the day so the new rumors don't duplicate
        # earlier generations.
        top_up_rumor_pool(
            world, seed=seed + world.day, lang=lang, count=3,
            god_mode=self.god_mode,
        )
        world.last_rumor_day = world.day

    def _place_expedition_henchmen(self, *, is_settlement: bool) -> None:
        """Move hired henchmen from the overland into the current level.

        Settlements bring the whole expedition inside so services
        are reachable to everyone. A cave / ruin can only fit
        :data:`MAX_HENCHMEN` of them in the crawl; when the player
        has more than that hired, an interactive dialog lets them
        pick which :data:`MAX_HENCHMEN` come along. Unpicked
        henchmen keep :attr:`Position.level_id` ``"overland"`` as
        left-behinds. If the dialog isn't available (no renderer
        hook, player cancels), falls back to sorted-by-entity-id
        first-N so entry never blocks.
        """
        if self.level is None:
            return
        from nhc.core.actions._henchman import MAX_HENCHMEN
        hired = [
            (eid, h) for eid, h in self.world.query("Henchman")
            if h.hired and h.owner == self.player_id
        ]
        hired.sort(key=lambda t: t[0])
        if is_settlement or len(hired) <= MAX_HENCHMEN:
            selected = hired
        else:
            picked_ids = self._select_dungeon_party(
                hired, MAX_HENCHMEN,
            )
            selected_by_id = dict(hired)
            selected = [
                (eid, selected_by_id[eid]) for eid in picked_ids
            ]
        # Only touch the selected henchmen; left-behinds keep their
        # existing "overland" position verbatim.
        for eid, _ in selected:
            pos = self.world.get_component(eid, "Position")
            if pos is not None:
                pos.level_id = self.level.id
        # Lay them out on walkable tiles around the player.
        self._place_henchmen_near_player()

    def _select_dungeon_party(
        self, hired: list, max_size: int,
    ) -> list[int]:
        """Prompt the player to pick ``max_size`` henchmen.

        Falls back to the first ``max_size`` hired-by-entity-id
        when the renderer has no ``show_selection_menu`` hook or
        the player cancels a prompt. Returns a list of entity
        ids in the order picked.
        """
        prompt = getattr(
            self.renderer, "show_selection_menu", None,
        )
        default = [eid for eid, _ in hired[:max_size]]
        if prompt is None:
            return default
        picked: list[int] = []
        remaining = list(hired)
        for _ in range(max_size):
            if not remaining:
                break
            options = [
                (eid, _entity_name(self.world, eid))
                for eid, _ in remaining
            ]
            choice = prompt(t("hex.pick_party"), options)
            if choice is None:
                # Player bailed out; fall back to the first-N
                # pick from the original hired order.
                return default
            picked.append(int(choice))
            remaining = [
                (eid, h) for eid, h in remaining
                if eid != int(choice)
            ]
        return picked

    def _notify_floor_change(self, depth: int) -> None:
        """Tell the web client a new dungeon floor is in play so it
        can fetch / render the SVG and redraw the canvas stack."""
        if self.level is None:
            return
        if not hasattr(self.renderer, "send_floor_change"):
            return
        cache_key = self.level.id
        cached = self._svg_cache.get(cache_key)
        site = self._active_site
        logger.debug(
            "floor-change: level=%s depth=%s svg_cache_hit=%s "
            "cached_levels=%s active_site=%s building_id=%s "
            "level_dim=%sx%s theme=%s prerevealed=%s",
            cache_key, depth, cached is not None,
            sorted(self._svg_cache.keys()),
            site.kind if site else None,
            getattr(self.level, "building_id", None),
            self.level.width, self.level.height,
            self.level.metadata.theme if self.level.metadata else None,
            (self.level.metadata.prerevealed
             if self.level.metadata else None),
        )
        self.renderer.send_floor_change(
            self.level, self.world, self.player_id,
            self.turn, seed=self.seed or 0,
            floor_svg=cached[1] if cached else None,
            floor_svg_id=cached[0] if cached else None,
            site=site,
        )
        if not cached and getattr(self.renderer, "floor_svg", None):
            fresh_svg = self.renderer.floor_svg
            fresh_id = self.renderer.floor_svg_id
            if isinstance(fresh_svg, str):
                self._svg_cache[cache_key] = (fresh_id, fresh_svg)
                logger.debug(
                    "floor-change: cached new SVG for level=%s "
                    "id=%s size=%d bytes",
                    cache_key, fresh_id, len(fresh_svg),
                )

    async def _enter_tower_site(self, coord) -> bool:
        """Route a tower-site hex through assemble_site().

        Places the player on the assembled tower's ground floor at
        the entry-door tile (or a perimeter floor tile if the door
        is missing). Reuses the same (q, r, depth) floor cache as
        the template pipeline so re-entry restores the same Level
        instance.
        """
        from nhc.dungeon.site import assemble_site
        from nhc.hexcrawl.seed import dungeon_seed

        cell = self.hex_world.get_cell(coord)
        if cell is None or cell.dungeon is None:
            return False

        depth = 1
        cache_key = self._cache_key(depth)
        if cache_key in self._floor_cache:
            level, _ = self._floor_cache[cache_key]
            self.level = level
            self._place_player_on_tower_entry()
            self._update_fov()
            self._notify_floor_change(depth)
            return True

        seed = dungeon_seed(
            self.seed or 0, coord, cell.dungeon.template,
        )
        site = assemble_site(
            "tower",
            f"site_{coord.q}_{coord.r}",
            random.Random(seed),
            mage_variant=cell.dungeon.mage_variant,
        )
        building = site.buildings[0]
        self.level = building.ground
        if (self.level and self.level.metadata
                and cell.dungeon.faction):
            self.level.metadata.faction = cell.dungeon.faction
        self._spawn_level_entities()
        # Pre-cache every floor of the tower under (q, r, depth) so
        # the engine's existing descend/ascend transition finds the
        # adjacent floor without having to regenerate the building.
        for i, floor in enumerate(building.floors):
            self._floor_cache[self._cache_key(i + 1)] = (floor, {})
        self._place_player_on_tower_entry()
        self._update_fov()
        self._notify_floor_change(depth)
        return True

    async def _enter_mansion_site(self, coord) -> bool:
        """Route a mansion-site hex through assemble_site()."""
        return await self._enter_multi_building_site(coord, "mansion")

    async def _enter_farm_site(self, coord) -> bool:
        """Route a farm-site hex through assemble_site()."""
        return await self._enter_multi_building_site(coord, "farm")

    async def _enter_multi_building_site(
        self, coord, kind: str,
    ) -> bool:
        """Land the player on ``site.buildings[0].ground``.

        Caches the first building's floors under the engine's
        depth-keyed slots so the existing stair-based floor
        transition works exactly like a tower; every sibling
        building's every floor is cached under a site-kind-keyed
        tuple so future cross-building door transitions can find
        them without re-running the assembler. The assembled Site
        is parked on :attr:`_active_site` as an O(1) handle.
        """
        from nhc.dungeon.site import assemble_site
        from nhc.hexcrawl.seed import dungeon_seed

        cell = self.hex_world.get_cell(coord)
        if cell is None or cell.dungeon is None:
            return False

        depth = 1
        cache_key = self._cache_key(depth)
        if cache_key in self._floor_cache:
            level, _ = self._floor_cache[cache_key]
            self.level = level
            self._place_player_on_building_entry()
            self._update_fov()
            self._notify_floor_change(depth)
            return True

        seed = dungeon_seed(
            self.seed or 0, coord, cell.dungeon.template,
        )
        site = assemble_site(
            kind,
            f"site_{coord.q}_{coord.r}",
            random.Random(seed),
            mage_variant=cell.dungeon.mage_variant,
        )
        first = site.buildings[0]
        self.level = first.ground
        if (self.level and self.level.metadata
                and cell.dungeon.faction):
            self.level.metadata.faction = cell.dungeon.faction
        self._spawn_level_entities()
        for i, floor in enumerate(first.floors):
            self._floor_cache[self._cache_key(i + 1)] = (floor, {})
        for bi in range(1, len(site.buildings)):
            b = site.buildings[bi]
            for fi, floor in enumerate(b.floors):
                key = (kind, coord.q, coord.r, bi, fi)
                self._floor_cache[key] = (floor, {})
        self._active_site = site
        self._place_player_on_building_entry()
        self._update_fov()
        self._notify_floor_change(depth)
        return True

    async def _enter_walled_site(self, coord, kind: str) -> bool:
        """Route a keep / town hex through assemble_site().

        Lands the player on the Site's ``surface`` Level (the
        courtyard for a keep, the street grid for a town) at the
        walkable tile nearest to the first gate of the enclosure,
        not on any individual building floor. Every building's
        every floor is cached under a site-kind-specific key so a
        future door-based transition can find the interior
        without re-running the assembler.
        """
        from nhc.dungeon.site import assemble_site
        from nhc.hexcrawl.seed import dungeon_seed

        cell = self.hex_world.get_cell(coord)
        if cell is None or cell.dungeon is None:
            return False

        depth = 1
        cache_key = self._cache_key(depth)
        if cache_key in self._floor_cache:
            level, _ = self._floor_cache[cache_key]
            self.level = level
            self._mark_surface_explored_if_prerevealed()
            self._place_player_on_surface()
            self._place_expedition_henchmen(
                is_settlement=kind == "town",
            )
            self._update_fov()
            self._notify_floor_change(depth)
            return True

        seed = dungeon_seed(
            self.seed or 0, coord, cell.dungeon.template,
        )
        site = assemble_site(
            kind,
            f"site_{coord.q}_{coord.r}",
            random.Random(seed),
            size_class=cell.dungeon.size_class,
            biome=cell.biome,
        )
        # Settlements top up the overland rumor pool on entry;
        # keep / town assemblers cover every settlement now, so
        # the hook belongs here rather than in the legacy
        # procedural:settlement branch. Inhabited keeps (v2 M12)
        # also refresh rumors so the garrison feels like a live
        # source of leads, not an empty parade ground.
        is_settlement = kind == "town"
        if is_settlement or kind == "keep":
            self._maybe_seed_rumors(seed)
        self.level = site.surface
        if (self.level and self.level.metadata
                and cell.dungeon.faction):
            self.level.metadata.faction = cell.dungeon.faction
        self._mark_surface_explored_if_prerevealed()
        self._spawn_level_entities()
        # Ground-depth cache slot holds the surface so re-entry is
        # O(1). Buildings go under site-kind-keyed tuples for
        # future cross-building entry.
        self._floor_cache[self._cache_key(depth)] = (self.level, {})
        for bi, b in enumerate(site.buildings):
            for fi, floor in enumerate(b.floors):
                key = (kind, coord.q, coord.r, bi, fi)
                self._floor_cache[key] = (floor, {})
        self._active_site = site
        self._place_player_on_surface()
        self._place_expedition_henchmen(is_settlement=is_settlement)
        self._update_fov()
        self._notify_floor_change(depth)
        return True

    def _mark_surface_explored_if_prerevealed(self) -> None:
        """Flip ``tile.explored`` on every non-VOID tile of a
        prerevealed level so the web client skips fog of war on the
        layout. ``tile.visible`` stays untouched -- entities and
        secrets continue to gate on the player's FOV.
        """
        level = self.level
        if not (level and level.metadata and level.metadata.prerevealed):
            return
        for row in level.tiles:
            for tile in row:
                if tile.terrain != Terrain.VOID:
                    tile.explored = True

    def _place_player_on_surface(self) -> None:
        """Land the player on the site surface near a gate.

        Prefers a FLOOR tile within the enclosure's first gate
        window; otherwise falls back to any FLOOR tile on the
        surface, and finally to ``(1, 1)``.
        """
        if self.level is None:
            return
        gate_xy: tuple[int, int] | None = None
        site = getattr(self, "_active_site", None)
        if (
            site is not None
            and site.enclosure is not None
            and site.enclosure.gates
        ):
            gx, gy, _ = site.enclosure.gates[0]
            gate_xy = (gx, gy)
        px, py = 1, 1
        best_d2 = None
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile is None or tile.terrain != Terrain.FLOOR:
                    continue
                if gate_xy is None:
                    px, py = x, y
                    best_d2 = 0
                    break
                d2 = (x - gate_xy[0]) ** 2 + (y - gate_xy[1]) ** 2
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    px, py = x, y
            if best_d2 == 0:
                break
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x = px
            pos.y = py
            pos.level_id = self.level.id

    def _place_player_on_building_entry(self) -> None:
        """Land the player on the active Level's entry-door tile.

        Falls back to a perimeter FLOOR tile when the door feature
        is missing, and to ``(1, 1)`` as a last resort.  Reuses the
        tower-entry algorithm; factored out so new site assemblers
        can land the player uniformly.
        """
        self._place_player_on_tower_entry()

    def _place_player_on_tower_entry(self) -> None:
        """Land the player on the tower's entry-door tile.

        Falls back to any perimeter FLOOR tile if the door feature
        is missing, and finally to ``(1, 1)`` as a last resort.
        """
        if self.level is None:
            return
        px, py = 1, 1
        door_found = False
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile and tile.feature == "door_closed":
                    px, py = x, y
                    door_found = True
                    break
            if door_found:
                break
        if not door_found:
            for y in range(self.level.height):
                for x in range(self.level.width):
                    tile = self.level.tile_at(x, y)
                    if tile and tile.terrain == Terrain.FLOOR:
                        px, py = x, y
                        door_found = True
                        break
                if door_found:
                    break
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x = px
            pos.y = py
            pos.level_id = self.level.id

    def _maybe_traverse_building_door(
        self,
        dx: int = 0,
        dy: int = 0,
        pre_x: int | None = None,
        pre_y: int | None = None,
    ) -> None:
        """Swap the active level when the player bumps *through*
        an open site door.

        Called after each player-originated action with the move
        direction and the player's pre-action position. Traverses
        only when both of the following hold:

        1. The player is *still* on the door tile after the action
           (``(pre_x, pre_y) == current position``). I.e., they
           were already standing on the door and their bump either
           got blocked by the wall on the other side of the edge
           or opened a closed door in place -- the classic
           "second step" that actually crosses. Merely *stepping
           onto* the door tile from an adjacent neighbour does
           not count; the player has to land on the door and then
           bump the edge to cross.
        2. The move direction matches the door's ``door_side`` --
           i.e., the bump was perpendicular to the wall carrying
           the door, not a lateral step along it. Mapping
           (:data:`_DOOR_SIDE_CROSS_DIR`):
           ``north`` → ``(0, -1)``, ``south`` → ``(0, 1)``,
           ``east`` → ``(1, 0)``, ``west`` → ``(-1, 0)``.
           ``(0, 0)`` (non-movement actions such as ``WaitAction``)
           never traverses.

        If ``pre_x`` / ``pre_y`` are ``None``, the pre-pos gate is
        skipped -- callers that place the player directly on a
        door tile (tests, scripted scenarios) can invoke the hook
        without fabricating a pre-position.

        Swaps land on the paired coordinate registered in
        ``site.building_doors`` (surface <-> building) or
        ``site.interior_doors`` (mansion cross-building walls).
        No-op when there is no active site, no player position,
        the tile under the player is not an open door, or the
        door has no valid ``door_side``.
        """
        site = self._active_site
        if site is None or self.level is None:
            return
        pos = self.world.get_component(self.player_id, "Position")
        if pos is None:
            return
        x, y = pos.x, pos.y
        if pre_x is not None and pre_y is not None:
            if (pre_x, pre_y) != (x, y):
                return
        tile = self.level.tile_at(x, y)
        if tile is None or tile.feature != "door_open":
            return
        expected = _DOOR_SIDE_CROSS_DIR.get(tile.door_side)
        if expected is None or (dx, dy) != expected:
            return
        # Surface -> building entry.
        if self.level is site.surface:
            target = site.building_doors.get((x, y))
            if target is None:
                return
            bid, bx, by = target
            building = next(
                (b for b in site.buildings if b.id == bid), None,
            )
            if building is None:
                return
            self._swap_to_building(building, bx, by)
            return
        # Building -> building (mansion shared door) or building ->
        # surface (perimeter exterior door).
        current_bid = self.level.building_id
        if current_bid is None:
            return
        interior = site.interior_doors.get((current_bid, x, y))
        if interior is not None:
            tbid, tx, ty = interior
            target_b = next(
                (b for b in site.buildings if b.id == tbid), None,
            )
            if target_b is not None:
                self._swap_to_building(target_b, tx, ty)
                return
        for (sx, sy), (bid, bx, by) in site.building_doors.items():
            if bid == current_bid and (bx, by) == (x, y):
                self._swap_to_site_surface(sx, sy)
                return

    def _swap_to_building(self, building, bx: int, by: int) -> None:
        """Switch ``self.level`` to ``building.ground`` and place
        the player on the ``(bx, by)`` tile.

        Marks the landing door tile as open so the player is never
        stuck on a closed-door square after a level swap.
        Re-keys the depth-indexed floor cache to point at the
        target building's floors so cross-floor stair navigation
        works for whichever building the player just entered.
        Saves entities of the outgoing level to a per-level stash
        and restores (or spawns) the target level's entities.
        Emits a floor-change notification for the web renderer.
        """
        from_level = self.level.id if self.level else None
        logger.debug(
            "swap-to-building: from=%s to=%s building=%s "
            "ground_depth=%s tile=(%s,%s)",
            from_level, building.ground.id, building.id,
            building.ground.depth, bx, by,
        )
        self._stash_current_level_entities()
        self.level = building.ground
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x = bx
            pos.y = by
            pos.level_id = self.level.id
        tile = self.level.tile_at(bx, by)
        if tile is not None and tile.feature == "door_closed":
            tile.feature = "door_open"
        self._activate_building_floor_cache(building)
        self._restore_or_spawn_level_entities()
        self._update_fov()
        self._notify_floor_change(self.level.depth)

    def _activate_building_floor_cache(self, building) -> None:
        """Point the depth-keyed floor cache at ``building.floors``.

        In multi-building sites (mansion, keep, town, farm) only
        the first building's floors land in the depth-keyed cache
        slots at site entry. When the player swaps into a sibling
        via a door, the depth cache must move to that sibling so
        DescendStairsAction / AscendStairsAction resolve to the
        right Level. Entity state is cleared on swap; a later
        pass can thread per-building entity stashes through if
        sibling populations turn out to matter.
        """
        if self._active_site is None:
            return
        for fi, floor in enumerate(building.floors):
            self._floor_cache[self._cache_key(fi + 1)] = (floor, {})

    def _is_building_descent_entry(self) -> bool:
        """Return True when the player is standing on the active
        site building's descent stair tile.

        The caller must have already decided the action is a
        descent; this method only checks tile eligibility.
        """
        from nhc.hexcrawl.model import DungeonRef

        if self._active_site is None or self.level is None:
            return False
        if self.level.building_id is None:
            return False
        if self.level.floor_index != 0:
            return False
        building = next(
            (b for b in self._active_site.buildings
             if b.id == self.level.building_id),
            None,
        )
        if building is None or building.descent is None:
            return False
        pos = self.world.get_component(self.player_id, "Position")
        if pos is None:
            return False
        for link in building.stair_links:
            if not isinstance(link.to_floor, DungeonRef):
                continue
            if link.from_tile == (pos.x, pos.y):
                return True
        return False

    def _collect_non_party_entities(
        self,
    ) -> dict[int, dict[str, object]]:
        """Snapshot components of every non-party entity."""
        keep_ids = self._party_keep_ids()
        data: dict[int, dict[str, object]] = {}
        for eid in list(self.world._entities):
            if eid in keep_ids:
                continue
            comps: dict[str, object] = {}
            for comp_type, store in self.world._components.items():
                if eid in store:
                    comps[comp_type] = store[eid]
            if comps:
                data[eid] = comps
        return data

    def _destroy_non_party_entities(self) -> None:
        keep_ids = self._party_keep_ids()
        for eid in list(self.world._entities):
            if eid not in keep_ids:
                self.world.destroy_entity(eid)

    def _restore_entities(
        self, data: dict[int, dict[str, object]],
    ) -> None:
        for eid, comps in data.items():
            self.world._entities.add(eid)
            for comp_type, comp in comps.items():
                self.world.add_component(eid, comp_type, comp)
            if eid >= self.world._next_id:
                self.world._next_id = eid + 1

    def _enter_building_descent(self) -> None:
        """Generate / restore the first floor of the active
        building's descent ``DungeonRef`` and swap ``self.level``."""
        from nhc.hexcrawl.model import DungeonRef
        from nhc.hexcrawl.seed import dungeon_seed

        assert self._active_site is not None
        assert self.level is not None and self.level.building_id
        building = next(
            b for b in self._active_site.buildings
            if b.id == self.level.building_id
        )
        assert building.descent is not None
        descent_link = next(
            l for l in building.stair_links
            if isinstance(l.to_floor, DungeonRef)
        )
        coord = self.hex_player_position
        bi = next(
            i for i, b in enumerate(self._active_site.buildings)
            if b.id == building.id
        )
        descent_key = (
            "descent", self._active_site.kind,
            coord.q, coord.r, bi, 1,
        )
        ground_key = (
            "descent_ground", self._active_site.kind,
            coord.q, coord.r, bi,
        )
        # Stash ground-level entities so the player finds the same
        # creatures / items when they climb back up.
        ground_entities = self._collect_non_party_entities()
        self._floor_cache[ground_key] = (self.level, ground_entities)
        self._destroy_non_party_entities()

        if descent_key in self._floor_cache:
            level, entity_data = self._floor_cache[descent_key]
            self.level = level
            self._restore_entities(entity_data)
        else:
            template = descent_link.to_floor.template
            seed = dungeon_seed(
                self.seed or 0, coord, template + "_descent",
            )
            sv = _shape_variety_for_depth(self.shape_variety, 2)
            theme = (
                "crypt" if template.startswith("procedural:crypt")
                else theme_for_depth(2)
            )
            rng = random.Random(seed)
            w, h = pick_map_size(rng, depth=2)
            params = GenerationParams(
                width=w, height=h, depth=2,
                shape_variety=sv, theme=theme, seed=seed,
                template=template,
            )
            self.generation_params = params
            self.level = generate_level(params)
            # Inherit the surface's faction so a biome-rolled
            # ruin pool (design/biome_features.md §8) drives the
            # descent populator on Floor 1 just like it did on
            # the surface -- no grab-bag crypt creatures in a
            # cultist-flavoured ruin.
            site_surface = self._active_site.surface
            inherited_faction = (
                site_surface.metadata.faction
                if (site_surface and site_surface.metadata)
                else None
            )
            if (inherited_faction and self.level
                    and self.level.metadata):
                self.level.metadata.faction = inherited_faction
            self._floor_cache[descent_key] = (self.level, {})
            self._spawn_level_entities()

        self._active_descent_building = building
        self._active_descent_return_tile = descent_link.from_tile
        self._place_player_at_stairs_up()
        self._update_fov()
        self._notify_floor_change(self.level.depth)

    def _exit_building_descent(self) -> None:
        """Return from an active descent to the building ground
        floor, placing the player on the descent source tile."""
        assert self._active_descent_building is not None
        assert self._active_descent_return_tile is not None
        assert self._active_site is not None
        coord = self.hex_player_position
        bi = next(
            i for i, b in enumerate(self._active_site.buildings)
            if b.id == self._active_descent_building.id
        )
        descent_key = (
            "descent", self._active_site.kind,
            coord.q, coord.r, bi, 1,
        )
        ground_key = (
            "descent_ground", self._active_site.kind,
            coord.q, coord.r, bi,
        )
        # Stash descent entities so a second descent finds the
        # same state; then destroy and rehydrate ground entities.
        self._floor_cache[descent_key] = (
            self.level, self._collect_non_party_entities(),
        )
        self._destroy_non_party_entities()
        building = self._active_descent_building
        return_tile = self._active_descent_return_tile
        ground_cache = self._floor_cache.pop(ground_key, None)
        if ground_cache is not None:
            cached_level, ground_entities = ground_cache
            self.level = cached_level
            self._restore_entities(ground_entities)
        else:
            self.level = building.ground
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x, pos.y = return_tile
            pos.level_id = self.level.id
        self._active_descent_building = None
        self._active_descent_return_tile = None
        self._update_fov()
        self._notify_floor_change(self.level.depth)

    def _swap_to_site_surface(self, sx: int, sy: int) -> None:
        """Switch ``self.level`` back to the active site's surface
        Level and place the player on ``(sx, sy)``.

        Saves entities of the outgoing building level and restores
        (or spawns) surface entities.
        """
        if self._active_site is None:
            return
        from_level = self.level.id if self.level else None
        logger.debug(
            "swap-to-site-surface: from=%s to=%s tile=(%s,%s)",
            from_level, self._active_site.surface.id, sx, sy,
        )
        self._stash_current_level_entities()
        self.level = self._active_site.surface
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x = sx
            pos.y = sy
            pos.level_id = self.level.id
        tile = self.level.tile_at(sx, sy)
        if tile is not None and tile.feature == "door_closed":
            tile.feature = "door_open"
        self._restore_or_spawn_level_entities()
        self._update_fov()
        self._notify_floor_change(self.level.depth)

    def _stash_current_level_entities(self) -> None:
        """Save non-party entity components for the current level.

        Stores under ``self._site_level_entities[level.id]`` so
        ``_restore_or_spawn_level_entities`` can rehydrate them
        when the player swaps back to the same level.
        """
        if self.level is None:
            return
        self._site_level_entities[self.level.id] = (
            self._collect_non_party_entities()
        )
        self._destroy_non_party_entities()

    def _restore_or_spawn_level_entities(self) -> None:
        """Rehydrate stashed entities for the current level, or
        spawn fresh placements when the level has never been
        activated this session."""
        if self.level is None:
            return
        stash = self._site_level_entities.pop(self.level.id, None)
        if stash is not None:
            self._restore_entities(stash)
        else:
            self._spawn_level_entities()

    def _place_player_at_stairs_up(self) -> None:
        """Move the player's Position onto the current level's
        stairs_up tile (or (1, 1) as a fallback)."""
        if self.level is None:
            return
        px, py = 1, 1
        for y in range(self.level.height):
            row_found = False
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile and tile.feature == "stairs_up":
                    px, py = x, y
                    row_found = True
                    break
            if row_found:
                break
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x = px
            pos.y = py
            pos.level_id = self.level.id

    async def exit_dungeon_to_hex(self) -> bool:
        """Pop back to the overland after a dungeon visit.

        Returns ``True`` when there was an active dungeon to leave;
        ``False`` (no-op) otherwise. The current Level is dropped
        from ``game.level`` but stays in the floor cache so re-entry
        is instantaneous. The player's Position is moved back to the
        overland sentinel so any stray dungeon system that consults
        it sees "out of bounds".
        """
        if self.level is None or not self.world_type is WorldType.HEXCRAWL:
            return False
        # Heavy lifting lives in _exit_to_overland_sync so
        # _maybe_exit_cleared_arena can call it synchronously
        # from the dungeon tick loop.
        self._exit_to_overland_sync()
        return True

    def _maybe_exit_cleared_arena(self) -> bool:
        """Auto-pop back to the overland when an arena is cleared.

        The Fight branch of an encounter pushes an arena
        :class:`Level` (tagged :data:`ARENA_TAG`). Once every
        creature on it is dead the arena serves no further
        purpose, so the game exits to the overland and emits a
        victory message. Returns ``True`` when an exit actually
        fired, ``False`` otherwise.

        Only hex mode triggers the hook -- classic dungeon runs
        handle their own level transitions. The method is
        synchronous so the dungeon run loop can call it between
        actions without awaiting.
        """
        from nhc.hexcrawl.encounter import ARENA_TAG
        if self.level is None or not self.world_type is WorldType.HEXCRAWL:
            return False
        if not any(ARENA_TAG in r.tags for r in self.level.rooms):
            return False
        # Any AI-bearing entity still on this level counts.
        for eid, _ai in self.world.query("AI"):
            pos = self.world.get_component(eid, "Position")
            if pos is None:
                continue
            if pos.level_id != self.level.id:
                continue
            health = self.world.get_component(eid, "Health")
            if health is None or health.current > 0:
                return False
        self.renderer.add_message(t("encounter.arena_cleared"))
        self._exit_to_overland_sync()
        return True

    def _generate_underworld_floor(self, depth: int) -> None:
        """Generate a shared underground floor for a cave cluster.

        Generalizes the old Floor 2 generator to handle depths
        2-5 with biome progression. Size scales with cluster
        membership and depth. Each cluster member gets a
        stairs_up tile at well-separated positions.
        """
        cc = self._active_cave_cluster
        if cc is None or self.hex_world is None:
            return
        members = self.hex_world.cave_clusters.get(cc, [cc])
        n = len(members)

        from nhc.hexcrawl.seed import dungeon_seed
        from nhc.hexcrawl.underworld import (
            floor_dimensions,
            theme_for_underworld_depth,
        )

        w, h = floor_dimensions(n, depth)
        theme = theme_for_underworld_depth(depth)
        seed = dungeon_seed(
            self.seed or 0, cc, f"cave_floor{depth}",
        )
        params = GenerationParams(
            width=w, height=h, depth=depth,
            shape_variety=0.3, theme=theme, seed=seed,
        )
        self.generation_params = params
        self.level = generate_level(params)

        # Remove the default stairs_up placed by the generator;
        # we'll place N of our own.
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile and tile.feature == "stairs_up":
                    tile.feature = ""

        # Place N stairs_up, one per cluster member, spread across
        # the map. Collect floor tiles and partition into N sectors.
        floors: list[tuple[int, int]] = []
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if (tile and tile.terrain is Terrain.FLOOR
                        and not tile.feature):
                    floors.append((x, y))
        if not floors:
            return
        rng = random.Random(seed + 1)
        rng.shuffle(floors)

        # Spread stairs across the map by dividing floor tiles
        # into N equal sectors (sorted by x then y for spatial
        # spread) and picking one from each sector.
        floors.sort(key=lambda p: (p[0], p[1]))
        sector_size = max(1, len(floors) // n)
        self._cave_floor2_stairs = {}
        stairs_by_member: "dict[HexCoord, tuple[int, int]]" = {}
        for i, member in enumerate(members):
            sector = floors[i * sector_size:(i + 1) * sector_size]
            if not sector:
                sector = [rng.choice(floors)]
            sx, sy = sector[len(sector) // 2]
            self.level.tiles[sy][sx].feature = "stairs_up"
            key = f"{member.q}_{member.r}"
            self._cave_floor2_stairs[key] = (sx, sy)
            stairs_by_member[member] = (sx, sy)
            logger.info(
                "Underworld floor %d stairs_up for %s at (%d, %d)",
                depth, key, sx, sy,
            )

        # Build the sector partition so ascend knows which member
        # hex the player is currently under.
        from nhc.hexcrawl.underworld import assign_sector_map
        self._underworld_sector_map = assign_sector_map(
            self.level, stairs_by_member,
        )

        # Add stairs_down if deeper floors exist
        region = self.hex_world.underworld_regions.get(cc)
        max_depth = region.max_depth if region else 2
        if depth < max_depth:
            self._add_stairs_down_to_level()

    def _refresh_underworld_sector_map(self, depth: int) -> None:
        """Rebuild sector map for a cached underworld floor.

        Called after _restore_floor so the map is available even
        when the floor was not freshly generated this session.
        """
        if (depth < 2
                or self._active_cave_cluster is None
                or self.hex_world is None
                or self.level is None):
            self._underworld_sector_map = {}
            return
        cc = self._active_cave_cluster
        members = self.hex_world.cave_clusters.get(cc, [cc])
        # Find stairs_up tiles on the level and pair with members
        # using the cached _cave_floor2_stairs dict when available,
        # otherwise round-robin against the stairs_up positions.
        stairs_by_member: dict[HexCoord, tuple[int, int]] = {}
        for member in members:
            key = f"{member.q}_{member.r}"
            xy = self._cave_floor2_stairs.get(key)
            if xy is not None:
                stairs_by_member[member] = xy
        if not stairs_by_member:
            self._underworld_sector_map = {}
            return
        from nhc.hexcrawl.underworld import assign_sector_map
        self._underworld_sector_map = assign_sector_map(
            self.level, stairs_by_member,
        )

    def _add_stairs_down_to_level(self) -> None:
        """Place a stairs_down tile on the current level.

        Picks a random FLOOR tile far from stairs_up so the
        player has to explore the cave floor before descending.
        """
        if self.level is None:
            return
        # Find stairs_up position.
        up_x = up_y = 0
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if tile and tile.feature == "stairs_up":
                    up_x, up_y = x, y
        # Collect floor candidates far from stairs_up.
        candidates: list[tuple[int, int, int]] = []
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if (tile and tile.terrain is Terrain.FLOOR
                        and not tile.feature):
                    dist = abs(x - up_x) + abs(y - up_y)
                    candidates.append((dist, x, y))
        if not candidates:
            return
        # Pick among the farthest 20%.
        candidates.sort(reverse=True)
        top = candidates[:max(1, len(candidates) // 5)]
        rng = random.Random(
            (self.seed or 0) + hash(("stairs_down",
             self.hex_player_position)),
        )
        _, sx, sy = rng.choice(top)
        self.level.tiles[sy][sx].feature = "stairs_down"

    def _is_site_edge_exit(self, dx: int, dy: int) -> bool:
        """Return True when a move of ``(dx, dy)`` from the
        player's current tile steps off the edge of an active
        Site surface, whether walled (keep / town / farm) or a
        sub-hex family site.

        Used by :meth:`_intent_to_action` to route an off-map
        move into :class:`LeaveSiteAction` rather than a regular
        bump. Surface identification:

        * Walled sites expose ``_active_site`` with a ``surface``
          Level; the player is on the surface when
          ``level.id == _active_site.surface.id``.
        * Sub-hex family sites assign ``self.level`` directly and
          mark ``_active_sub_hex``; they run at ``depth == 1``
          without ``building_id``.

        Building interiors (``level.building_id`` is set) are
        rejected so the player still has to leave through a door
        when inside a building.
        """
        if self.world_type is not WorldType.HEXCRAWL:
            return False
        if self.level is None:
            return False
        if self._active_site is None and self._active_sub_hex is None:
            return False
        on_walled_surface = (
            self._active_site is not None
            and self.level.id == self._active_site.surface.id
        )
        on_sub_hex_surface = (
            self._active_sub_hex is not None
            and self.level.depth == 1
            and self.level.building_id is None
            and (
                self._active_site is None
                or self.level.id == self._active_site.surface.id
            )
        )
        if not (on_walled_surface or on_sub_hex_surface):
            return False
        pos = self.world.get_component(self.player_id, "Position")
        if pos is None:
            return False
        nx, ny = pos.x + dx, pos.y + dy
        return self.level.tile_at(nx, ny) is None

    def _leave_site_narration_key(self) -> str:
        """Pick the most specific ``leave_site.exit_<kind>`` key for
        the currently active site.

        Sub-hex family visits key off the minor/major feature of the
        sub-hex cell; walled sites key off ``_active_site.kind``
        with a macro-cell feature fallback. Returns ``leave_site.exit``
        as the generic catch-all; :class:`LeaveSiteAction` already
        falls back to the same key when the specific entry is
        missing from the current locale, so callers don't need to
        probe themselves.
        """
        from nhc.hexcrawl.model import MinorFeatureType

        if (self._active_sub_hex is not None
                and self.hex_world is not None):
            macro = self.hex_world.exploring_hex
            if macro is not None:
                cell = self.hex_world.get_cell(macro)
                if cell is not None and cell.flower is not None:
                    sub_cell = cell.flower.cells.get(
                        self._active_sub_hex,
                    )
                    if sub_cell is not None:
                        minor = sub_cell.minor_feature
                        if minor is not MinorFeatureType.NONE:
                            return f"leave_site.exit_{minor.value}"
                        major = sub_cell.major_feature
                        if major is not HexFeatureType.NONE:
                            return f"leave_site.exit_{major.value}"
        if self._active_site is not None:
            kind = getattr(self._active_site, "kind", None)
            if kind:
                return f"leave_site.exit_{kind}"
            if (self.hex_world is not None
                    and self.hex_player_position is not None):
                cell = self.hex_world.get_cell(
                    self.hex_player_position,
                )
                if cell is not None:
                    feat = cell.feature
                    if feat is not HexFeatureType.NONE:
                        return f"leave_site.exit_{feat.value}"
        return "leave_site.exit"

    def _on_leave_site_requested(self, event: LeaveSiteRequested) -> None:
        """Handle the :class:`LeaveSiteRequested` bus event.

        Drops the level, moves the player to the overland
        sentinel, and restores the flower view. Subscribed in
        :meth:`_subscribe_event_handlers`.
        """
        self._exit_to_overland_sync()

    # -- C2: sub-hex mutation tracking ---------------------------------

    def _active_sub_hex_cache_key(self) -> "tuple | None":
        """Return the ``("sub", ...)`` cache-manager key for the
        currently-active sub-hex family visit, or ``None`` when no
        visit is in progress. Used by the mutation handlers below."""
        if self._active_sub_hex is None or self.hex_world is None:
            return None
        macro = self.hex_world.exploring_hex
        if macro is None:
            return None
        sub = self._active_sub_hex
        return ("sub", macro.q, macro.r, sub.q, sub.r, 1)

    def _append_sub_hex_mutation(
        self, kind: str, value,
    ) -> None:
        """Append ``value`` onto the named mutation list for the
        current sub-hex cache entry. No-op when no visit is active."""
        if self._sub_hex_cache is None:
            return
        key = self._active_sub_hex_cache_key()
        if key is None:
            return
        entry = self._sub_hex_cache._entries.get(key)
        if entry is None:
            return
        muts = entry["mutations"]
        bucket = muts.setdefault(kind, [])
        bucket.append(value)
        self._sub_hex_cache.update_mutations(key, muts)

    def _set_sub_hex_mutation(
        self, kind: str, subkey: str, value,
    ) -> None:
        """Set ``mutations[kind][subkey] = value`` for the current
        sub-hex cache entry. No-op outside a visit."""
        if self._sub_hex_cache is None:
            return
        key = self._active_sub_hex_cache_key()
        if key is None:
            return
        entry = self._sub_hex_cache._entries.get(key)
        if entry is None:
            return
        muts = entry["mutations"]
        bucket = muts.setdefault(kind, {})
        bucket[subkey] = value
        self._sub_hex_cache.update_mutations(key, muts)

    def _on_sub_hex_item_picked(self, event: ItemPickedUp) -> None:
        """Record the tile an item was picked up from so replay on
        re-entry can remove the matching placement."""
        if self._active_sub_hex is None:
            return
        pos = self.world.get_component(event.entity, "Position")
        if pos is None:
            return
        self._append_sub_hex_mutation(
            "looted", [pos.x, pos.y],
        )

    def _on_sub_hex_creature_died(self, event: CreatureDied) -> None:
        """Record the id of a creature that died inside a sub-hex
        site so the populator skips it on re-entry.

        Populator-spawned entities carry a ``SubHexStableId``
        component; record that stable id so the mutation survives
        the ECS destroy that follows the event. Non-populated
        casualties (e.g. adventurers wandered in) fall back to the
        ECS int so the mutation is still unique, though they won't
        match on re-entry (non-populated creatures don't respawn)."""
        if self._active_sub_hex is None:
            return
        sid_comp = self.world.get_component(
            event.entity, "SubHexStableId",
        )
        marker = (
            sid_comp.stable_id if sid_comp is not None
            else event.entity
        )
        self._append_sub_hex_mutation("killed", marker)

    def _on_sub_hex_door_opened(self, event: DoorOpened) -> None:
        """Record an opened door so re-entry keeps it open rather
        than resetting to closed."""
        if self._active_sub_hex is None:
            return
        self._set_sub_hex_mutation(
            "doors", f"{event.x},{event.y}", "open",
        )

    def _on_sub_hex_terrain_changed(self, event: TerrainChanged) -> None:
        """Record a dug-through wall (U4: skip door tiles, handled by
        the emitter — DigAction only fires for walls/voids)."""
        if self._active_sub_hex is None:
            return
        self._set_sub_hex_mutation(
            "terrain", f"{event.x},{event.y}", event.kind,
        )

    def _exit_to_overland_sync(self) -> None:
        """Synchronous form of :meth:`exit_dungeon_to_hex` body.

        Nothing here awaits -- it just drops the level and moves
        the player + hired henchmen to the overland sentinel.
        If ``exploring_hex`` is set, the player returns to the
        flower view at the feature_cell rather than the macro map.
        """
        if self.level is None or not self.world_type is WorldType.HEXCRAWL:
            return
        departing_level_id = self.level.id
        entry_sub_hex = self._active_sub_hex
        self.level = None
        self._active_cave_cluster = None
        self._active_site = None
        self._active_sub_hex = None
        self._active_descent_building = None
        self._active_descent_return_tile = None
        self._site_level_entities = {}
        self._underworld_sector_map = {}
        pos = self.world.get_component(self.player_id, "Position")
        if pos is not None:
            pos.x = -1
            pos.y = -1
            pos.level_id = "overland"
        for eid, hench in self.world.query("Henchman"):
            if not hench.hired or hench.owner != self.player_id:
                continue
            hpos = self.world.get_component(eid, "Position")
            if hpos is None:
                continue
            if hpos.level_id == departing_level_id:
                hpos.x = -1
                hpos.y = -1
                hpos.level_id = "overland"
        # If we were exploring a flower when we entered the
        # feature, return to the flower. Sub-hex family sites
        # restore the entry sub-hex (so the flower view keeps the
        # player at the door they walked through); walled sites
        # and dungeon exits fall back to the feature_cell.
        if (self.hex_world
                and self.hex_world.exploring_hex is not None):
            if entry_sub_hex is not None:
                self.hex_world.exploring_sub_hex = entry_sub_hex
            else:
                macro = self.hex_world.exploring_hex
                cell = self.hex_world.get_cell(macro)
                if cell and cell.flower and cell.flower.feature_cell:
                    self.hex_world.exploring_sub_hex = (
                        cell.flower.feature_cell
                    )

    async def panic_flee(self) -> bool:
        """Escape the current dungeon from anywhere at a cost.

        Normal exit (:meth:`exit_dungeon_to_hex`) expects the
        player on the entry tile. Panic-flee skips that
        requirement in exchange for a 1d6 damage roll against the
        player and a single half-day advance on the overland
        clock. Floors damage so the player keeps at least 1 HP --
        a bail-out shouldn't be the thing that kills the
        character.

        Returns ``True`` when the flee actually triggered, ``False``
        when there's no active dungeon to flee from (no-op on the
        overland).
        """
        import random as _random

        if self.level is None or not self.world_type is WorldType.HEXCRAWL:
            return False
        # Damage roll first so the HP state is observable before
        # the dungeon is popped (rendering hooks may read it).
        rng = self._encounter_rng or _random.Random()
        hp = self.world.get_component(self.player_id, "Health")
        if hp is not None and hp.current > 1:
            damage = rng.randint(1, 6)
            hp.current = max(1, hp.current - damage)
        # Day-clock penalty: half a day lost to the scramble out.
        if self.hex_world is not None:
            self.hex_world.advance_clock(1)
        # Reuse the normal exit path for the cache / level reset
        # + henchman shepherding.
        await self.exit_dungeon_to_hex()
        return True

    async def resolve_encounter(self, choice) -> bool:
        """Dispatch the player's Fight / Flee / Talk pick.

        Returns ``True`` when a pending encounter was consumed,
        ``False`` when there was nothing to resolve.

        * ``FIGHT`` — generate an arena with the encounter's
          creatures, load it as :attr:`level`, spawn the foes,
          and pull the dungeon-party into it (left-behinds stay
          on the overland via :meth:`_place_expedition_henchmen`).
        * ``FLEE`` — stay on the overland; roll 1d4 damage against
          the player using :attr:`_encounter_rng` (tests seed it
          for determinism).
        * ``TALK`` — peacefully resolve. The LLM-driven dialog is
          a later UI-polish piece; today the pipeline just clears
          the pending state and emits a flavour message.
        """
        import random as _random

        from nhc.hexcrawl.encounter import generate_encounter_arena
        from nhc.hexcrawl.encounter_pipeline import EncounterChoice
        from nhc.hexcrawl.seed import dungeon_seed

        if self.pending_encounter is None:
            return False
        enc = self.pending_encounter
        self.pending_encounter = None

        if choice is EncounterChoice.FIGHT:
            # Seed the arena off the hex coord so identical rolls
            # on the same tile reproduce byte-for-byte.
            coord = self.hex_player_position or HexCoord(0, 0)
            seed = dungeon_seed(
                self.seed or 0, coord, "encounter",
            )
            self.level = generate_encounter_arena(
                seed=seed,
                biome=enc.biome,
                creatures=enc.creatures,
                arena_id=(
                    f"arena_{coord.q}_{coord.r}_{self.turn}"
                ),
            )
            self._spawn_level_entities()
            self._place_player_at_stairs_up()
            # Encounters honour the dungeon party cap -- a pack
            # of goblins can't fit the whole expedition.
            self._place_expedition_henchmen(is_settlement=False)
            self._notify_floor_change(depth=1)
            return True

        if choice is EncounterChoice.FLEE:
            rng = self._encounter_rng or _random.Random()
            hp = self.world.get_component(self.player_id, "Health")
            if hp is not None:
                # 1d4: a bruise, not a killing blow.
                damage = rng.randint(1, 4)
                hp.current = max(0, hp.current - damage)
            return True

        if choice is EncounterChoice.TALK:
            # No ECS side-effect in v1. Just a peaceful pop-off.
            return True

        raise ValueError(f"unknown encounter choice: {choice!r}")

    async def apply_hex_step(self, target: HexCoord) -> bool:
        """Delegate to HexSession."""
        return await self._hex.apply_hex_step(target)

    def _maybe_stage_encounter(self, target: "HexCoord") -> None:
        """Delegate to HexSession."""
        self._hex._maybe_stage_encounter(target)

    def _create_hex_player(self) -> None:
        """Delegate to HexSession."""
        self._hex._create_hex_player()

    def _give_starting_gear(self, char) -> None:
        """Equip the player with the character's rolled starting
        items. Shared across dungeon and hex init paths so every
        mode starts with the same gear."""
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
                        self.world.destroy_entity(eid)
                        logger.info(
                            "Starting item %s skipped (slots full)",
                            item_id,
                        )
                        continue
                    inv.slots.append(eid)
                    if equip:
                        if (equip.weapon is None
                                and self.world.has_component(
                                    eid, "Weapon")):
                            equip.weapon = eid
                        armor_comp = self.world.get_component(
                            eid, "Armor",
                        )
                        if armor_comp:
                            slot_map = {
                                "body": "armor",
                                "shield": "shield",
                                "helmet": "helmet",
                            }
                            attr = slot_map.get(
                                armor_comp.slot, "armor",
                            )
                            if getattr(equip, attr) is None:
                                setattr(equip, attr, eid)
            except KeyError:
                logger.warning(
                    "Unknown starting item: %s", item_id,
                )

    def handle_player_death(self) -> bool:
        """Delegate to DeathHandler."""
        return self._death.handle_player_death()

    def allows_cheat_death_now(self) -> bool:
        """Delegate to DeathHandler."""
        return self._death.allows_cheat_death_now()

    def cheat_death(self) -> None:
        """Delegate to DeathHandler."""
        self._death.cheat_death()

    def cheat_death_dungeon(self) -> None:
        """Delegate to DeathHandler."""
        self._death.cheat_death_dungeon()

    def _init_hex_world(self) -> None:
        """Delegate to HexSession."""
        self._hex._init_hex_world()

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
        else:
            # No explicit seed → force a fresh random one so
            # consecutive "New Game" clicks on the same thread
            # don't reuse the stale thread-local seed from the
            # previous session.
            set_seed(random.Random().randint(0, 2**31 - 1))
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
        # overland HexWorld and skip the dungeon-only level
        # generation below; a dungeon level will be loaded later
        # when the player enters a hex feature (M-1.12). Event
        # handlers still need to be wired so within-dungeon
        # actions (descend stairs, pick up items, kill creatures)
        # reach the Game-side dispatch.
        if self.world_type is WorldType.HEXCRAWL:
            self._init_hex_world()
            self._subscribe_event_handlers()
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
                short=trait_text("background", char.background),
            ),
            "Equipment": Equipment(),
            "Hunger": Hunger(),
        })
        self._character = char

        self._give_starting_gear(char)

        # Spawn level entities
        self._spawn_level_entities()

        # Subscribe event handlers (shared with hex mode — see
        # _subscribe_event_handlers).
        self._subscribe_event_handlers()

        # Compute initial FOV
        self._update_fov()

        # Initialize renderer
        self.renderer.initialize()

        # Initialize GM for typed mode
        if self.style == "typed" and self.backend:
            self._ctx_builder = ContextBuilder()
            self._gm = GameMaster(self.backend, self._ctx_builder)

        # Welcome message with character intro
        self.renderer.add_message(t("game.welcome", name=self.level.name))
        self.renderer.add_message(t(
            "game.char_intro",
            name=char.name,
            background=trait_text("background", char.background),
            virtue=trait_text("virtue", char.virtue),
            vice=trait_text("vice", char.vice),
            # Alignment sits at a sentence boundary in the template.
            alignment=trait_text(
                "alignment", char.alignment,
            ).capitalize(),
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
            char_background=trait_text("background", char.background),
            char_virtue=trait_text("virtue", char.virtue),
            char_vice=trait_text("vice", char.vice),
            char_alignment=trait_text("alignment", char.alignment),
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
                    anchor = placement.extra.get("errand_anchor")
                    if anchor is not None and "Errand" in components:
                        errand = components["Errand"]
                        errand.anchor_x, errand.anchor_y = anchor
                        errand.anchor_weight = placement.extra.get(
                            "errand_weight", 0.5,
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

        # Interior edge walls aren't tile-level blockers — they
        # sit on the edge between two tiles. The FOV raycast is
        # tile-based, so we precompute the BFS-reachable set with
        # edges as barriers and treat unreachable tiles as blocked
        # for the purposes of this cast. Subtract the shadow set
        # after so rooms behind a wall stay invisible instead of
        # partially revealed.
        radius = _fov_radius_for_level(self.level)
        edge_shadow: set[tuple[int, int]] = set()
        if self.level.interior_edges:
            from nhc.dungeon.edges import edge_shadow_tiles
            edge_shadow = edge_shadow_tiles(
                self.level, (pos.x, pos.y), radius,
            )

        def is_blocking(x: int, y: int) -> bool:
            if (x, y) in blocked_tiles:
                return True
            if (x, y) in edge_shadow:
                return True
            tile = self.level.tile_at(x, y)
            if not tile:
                return True
            return tile.blocks_sight

        visible = compute_fov(pos.x, pos.y, radius, is_blocking)
        # Virtual wall tiles are room floor behind the door —
        # exclude them so the room isn't partially revealed.
        visible -= blocked_tiles
        visible -= edge_shadow

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
        logger.info("Game loop started (mode=%s)", self.style)

        while self.running:
            # Render: hex mode routes to render_hex; dungeon mode keeps
            # the existing render() path unchanged.
            if self.world_type is WorldType.HEXCRAWL and self.hex_world is not None \
                    and self.level is None \
                    and self.hex_world.exploring_hex is not None:
                # Sub-hex flower exploration mode
                self.renderer._hex_game = self
                self.renderer.render_flower(
                    self.hex_world,
                    self.hex_world.exploring_sub_hex,
                    self.turn,
                )
                outcome = await self._process_flower_turn()
                if outcome == "disconnect":
                    logger.info("Player disconnected, suspending game")
                    _autosave(self, self.save_dir, blocking=True)
                    self.running = False
                    break
                if outcome in ("moved", "rest"):
                    self.turn += 1
                continue

            if self.world_type is WorldType.HEXCRAWL and self.hex_world is not None \
                    and self.level is None:
                # Give the renderer a back-reference so it can
                # gather player stats for the unified status bar.
                self.renderer._hex_game = self
                self.renderer.render_hex(
                    self.hex_world,
                    self.hex_player_position,
                    self.turn,
                )
                outcome = await self._process_hex_turn()
                if outcome == "disconnect":
                    logger.info("Player disconnected, suspending game")
                    _autosave(self, self.save_dir, blocking=True)
                    self.running = False
                    break
                if outcome in ("moved", "entered", "rest"):
                    self.turn += 1
                continue

            self.renderer.render(
                self.world, self.level, self.player_id, self.turn,
            )

            if self.style == "typed":
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
                # Snapshot pre-action position so the door-
                # crossing hook can tell "player bumped through
                # the door edge while on the door tile" from
                # "player just stepped onto an open door tile".
                pre_pos = self.world.get_component(
                    self.player_id, "Position",
                )
                pre_x = pre_pos.x if pre_pos else 0
                pre_y = pre_pos.y if pre_pos else 0
                events += await self._resolve(act)
                self._maybe_traverse_building_door(
                    getattr(act, "dx", 0), getattr(act, "dy", 0),
                    pre_x, pre_y,
                )

            # Haste: auto-repeat movement in the same direction
            if (player_status and player_status.hasted > 0
                    and isinstance(action, BumpAction)):
                haste_move = BumpAction(
                    actor=self.player_id,
                    dx=action.dx, dy=action.dy,
                )
                pre_pos = self.world.get_component(
                    self.player_id, "Position",
                )
                pre_x = pre_pos.x if pre_pos else 0
                pre_y = pre_pos.y if pre_pos else 0
                events += await self._resolve(haste_move)
                self._maybe_traverse_building_door(
                    haste_move.dx, haste_move.dy, pre_x, pre_y,
                )

            # Track when doors were opened (for auto-close) and
            # propagate open/close to any linked door pair so both
            # sides of a cross-building InteriorDoorLink stay in
            # sync with their ``opened_at_turn``.
            from nhc.core.events import DoorClosed as _DoorClosed
            from nhc.core.game_ticks import _sync_linked_door
            for ev in events:
                if isinstance(ev, DoorOpened):
                    tile = self.level.tile_at(ev.x, ev.y)
                    if tile:
                        tile.opened_at_turn = self.turn
                    _sync_linked_door(self, ev.x, ev.y)
                elif isinstance(ev, _DoorClosed):
                    _sync_linked_door(self, ev.x, ev.y)

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
            if self.style == "typed" and self._gm and creature_events:
                c_outcomes = self._events_to_outcomes(creature_events)
                if c_outcomes:
                    c_narr = await self._gm.narrate_creatures(c_outcomes)
                    if c_narr.strip():
                        self.renderer.add_message(c_narr)

            # Tick poison on all affected entities
            self._apply_turn_ticks()

            # Hex-mode: auto-pop a cleared encounter arena.
            self._maybe_exit_cleared_arena()

            # God mode: restore HP to max each turn
            health = self.world.get_component(self.player_id, "Health")
            if self.god_mode and health:
                health.current = health.maximum

            # Check player death (None means entity was destroyed)
            if not health or health.current <= 0:
                self._detect_death_cause(events)
                logger.info("Player died: killed_by=%s turn=%d",
                            self.killed_by, self.turn)
                death_msg = t("game.died")
                if self.killed_by:
                    death_msg = t("game.slain_by", killer=self.killed_by)
                self.renderer.add_message(death_msg)
                # Hex-easy offers a cheat-death dialog before the
                # classic end-screen path; every other mode falls
                # through to permadeath.
                if self.handle_player_death():
                    logger.info("Player cheated death, resuming loop")
                    continue
                self.game_over = True
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
        from nhc.core.actions._confirm import confirm_peaceful_attack

        prompt = getattr(
            self.renderer, "show_selection_menu", None,
        )
        action = confirm_peaceful_attack(
            self.world, self.level, action, prompt,
        )
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
        # Teleporter pads: step onto a pad on the current level and
        # get whisked to the paired tile (one hop, no chaining).
        from nhc.core.actions._teleport import maybe_teleport_player
        if self.level is not None:
            if maybe_teleport_player(
                self.world, self.level, self.player_id,
            ):
                from nhc.core.actions._teleport import teleport_message
                msg = MessageEvent(text=teleport_message())
                await self.event_bus.emit(msg)
                events.append(msg)
        return events

    async def _shop_interaction(self, merchant_id: int) -> None:
        """Delegate to NpcInteractions."""
        await self._npc.shop_interaction(merchant_id)

    async def _temple_interaction(self, priest_id: int) -> None:
        """Delegate to NpcInteractions."""
        await self._npc.temple_interaction(priest_id)

    async def _henchman_interaction(self, henchman_id: int) -> None:
        """Delegate to NpcInteractions."""
        await self._npc.henchman_interaction(henchman_id)

    async def _process_hex_turn(self) -> str:
        """Delegate to HexSession."""
        return await self._hex._process_hex_turn()

    async def _process_flower_turn(self) -> str:
        """Delegate to HexSession."""
        return await self._hex._process_flower_turn()

    def _maybe_stage_sub_hex_encounter(
        self, target_sub: HexCoord,
    ) -> None:
        """Delegate to HexSession."""
        self._hex._maybe_stage_sub_hex_encounter(target_sub)

    async def _prompt_encounter(self) -> None:
        """Delegate to HexSession."""
        await self._hex._prompt_encounter()

    async def _get_classic_actions(self) -> list:
        """Classic mode: single keypress → single action."""
        intent, data = await self.renderer.get_input()
        if intent == "disconnect":
            return ["disconnect"]
        # Ascend at depth 1 in hex mode = exit to overland/flower.
        # Skip when the player is inside a building interior --
        # there `stairs_up` means "physically up a floor" and must
        # fall through to AscendStairsAction.
        if (intent == "ascend" and self.world_type is WorldType.HEXCRAWL
                and self.level is not None and self.level.depth <= 1
                and self.level.building_id is None):
            pos = self.world.get_component(self.player_id, "Position")
            tile = self.level.tile_at(pos.x, pos.y) if pos else None
            if tile and tile.feature == "stairs_up":
                ok = await self.exit_dungeon_to_hex()
                if ok:
                    self.renderer.add_message(
                        "You return to the overland.",
                    )
                return []
        # Hex-mode exit from inside a dungeon: pop back to the
        # overland. Returns an empty action list so the dungeon
        # turn does not also tick.
        if intent == "hex_exit" and self.world_type is WorldType.HEXCRAWL:
            ok = await self.exit_dungeon_to_hex()
            if ok:
                self.renderer.add_message(
                    "You return to the overland.",
                )
            return []
        # Panic-flee: works from anywhere in the crawl, costs 1d6
        # HP + one day-clock segment. The game-over dialog fires
        # naturally if the HP roll floors the player at 1.
        if intent == "panic_flee" and self.world_type is WorldType.HEXCRAWL:
            ok = await self.panic_flee()
            if ok:
                self.renderer.add_message(
                    "You bail out in a panic.",
                )
            return []
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
                pre_pos = self.world.get_component(
                    self.player_id, "Position",
                )
                pre_x = pre_pos.x if pre_pos else 0
                pre_y = pre_pos.y if pre_pos else 0
                evts = await self._resolve(act)
                all_events += evts
                self._maybe_traverse_building_door(
                    getattr(act, "dx", 0), getattr(act, "dy", 0),
                    pre_x, pre_y,
                )

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
                    pre_pos = self.world.get_component(
                        self.player_id, "Position",
                    )
                    pre_x = pre_pos.x if pre_pos else 0
                    pre_y = pre_pos.y if pre_pos else 0
                    evts = await self._resolve(act)
                    all_events += evts
                    self._maybe_traverse_building_door(
                        getattr(act, "dx", 0),
                        getattr(act, "dy", 0),
                        pre_x, pre_y,
                    )

            # Phase 3: Narrate all outcomes together
            outcomes = self._events_to_outcomes(all_events)
            char = self._character
            narrative = await self._gm.narrate(
                intent=typed_text,
                outcomes=outcomes,
                char_name=char.name,
                char_background=trait_text("background", char.background),
                char_virtue=trait_text("virtue", char.virtue),
                char_vice=trait_text("vice", char.vice),
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
            if self._is_site_edge_exit(dx, dy):
                return LeaveSiteAction(
                    actor=self.player_id, dx=dx, dy=dy,
                    narration_key=self._leave_site_narration_key(),
                )
            return BumpAction(
                actor=self.player_id, dx=dx, dy=dy,
                edge_doors=self.renderer.edge_doors,
                hex_world=self.hex_world,
            )

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
        if self.style == "classic":
            self.style = "typed"
            self.renderer.style = "typed"
            # Initialize GM if backend available and not already set up
            if self.backend and not self._gm:
                self._ctx_builder = ContextBuilder()
                self._gm = GameMaster(self.backend, self._ctx_builder)
        else:
            self.style = "classic"
            self.renderer.style = "classic"
        logger.info("Switched to %s mode", self.style)

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

    # ── Per-turn tick sequence ─────────────────────────────────
    # Individual methods kept for direct use (hex movement ticks
    # hunger alone, tests call individual ticks).

    _TURN_TICKS = (
        game_ticks.tick_poison,
        game_ticks.tick_regeneration,
        game_ticks.tick_mummy_rot,
        game_ticks.tick_rings,
        game_ticks.tick_doors,
        game_ticks.tick_traps,
        game_ticks.tick_wand_recharge,
        game_ticks.tick_hunger,
        game_ticks.tick_stairs_proximity,
    )

    def _apply_turn_ticks(self) -> None:
        """Run all per-turn status/world ticks in sequence."""
        for tick in self._TURN_TICKS:
            tick(self)
        self._tick_buried_markers()

    def _tick_poison(self) -> None:
        game_ticks.tick_poison(self)

    def _tick_regeneration(self) -> None:
        game_ticks.tick_regeneration(self)

    def _tick_mummy_rot(self) -> None:
        game_ticks.tick_mummy_rot(self)

    def _tick_hunger(self) -> None:
        game_ticks.tick_hunger(self)

    def _detect_death_cause(self, events: list) -> None:
        """Determine what killed the player from turn events."""
        for ev in events:
            if (isinstance(ev, CreatureAttacked)
                    and ev.target == self.player_id and ev.hit):
                desc = self.world.get_component(ev.attacker, "Description")
                if desc:
                    self.killed_by = desc.name
        if self.killed_by:
            return
        for ev in events:
            if (isinstance(ev, TrapTriggered)
                    and ev.entity == self.player_id and ev.damage > 0):
                self.killed_by = ev.trap_name
                return

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

    def _subscribe_event_handlers(self) -> None:
        """Wire Game-side handlers onto the event bus.

        Shared by dungeon and hex modes so that actions firing
        LevelEntered, CreatureDied, and friends reach the game
        loop in both paths. Idempotent-ish: re-registering the
        same (type, handler) pair would duplicate subscriptions,
        so this method is expected to run once per Game.
        """
        self.event_bus.subscribe(MessageEvent, self._on_message)
        self.event_bus.subscribe(GameWon, self._on_game_won)
        self.event_bus.subscribe(CreatureDied, self._on_creature_died)
        self.event_bus.subscribe(LevelEntered, self._on_level_entered)
        self.event_bus.subscribe(ItemUsed, self._on_item_used)
        self.event_bus.subscribe(ItemSold, self._on_item_sold)
        self.event_bus.subscribe(VisualEffect, self._on_visual_effect)
        self.event_bus.subscribe(
            LeaveSiteRequested, self._on_leave_site_requested,
        )
        # Sub-hex mutation tracking (C2): the handlers below short-
        # circuit when _active_sub_hex is None, so dungeon runs and
        # macro-site visits are untouched.
        self.event_bus.subscribe(
            ItemPickedUp, self._on_sub_hex_item_picked,
        )
        self.event_bus.subscribe(
            CreatureDied, self._on_sub_hex_creature_died,
        )
        self.event_bus.subscribe(
            DoorOpened, self._on_sub_hex_door_opened,
        )
        self.event_bus.subscribe(
            TerrainChanged, self._on_sub_hex_terrain_changed,
        )

    def _on_level_entered(self, event: LevelEntered) -> None:
        """Transition to a dungeon level (ascending or descending)."""
        new_depth = event.depth
        old_depth = self.level.depth
        ascending = new_depth < old_depth
        logger.info("%s to depth %d",
                     "Ascending" if ascending else "Descending", new_depth)

        # Capture source-floor building context so we can place the
        # player on the matching StairLink tile after the swap (the
        # ascending/stair-feature heuristic below is inverted for
        # building floors because the actions flip depth).
        old_building_id = self.level.building_id
        old_floor_index = self.level.floor_index
        _pre_pos = self.world.get_component(self.player_id, "Position")
        old_player_tile: tuple[int, int] | None = (
            (_pre_pos.x, _pre_pos.y) if _pre_pos else None
        )

        # Building descent: descending from a building ground
        # floor onto the descent stair tile routes through the
        # dungeon template pipeline (cave / crypt / ...), not
        # the in-building floor cache.
        if not ascending and self._is_building_descent_entry():
            self._enter_building_descent()
            return
        # Exiting the descent: ascending from descent depth 1
        # (old_depth == 2) to depth 1 returns to the source
        # building's ground floor. Deeper-floor ascents inside the
        # descent use the normal dungeon cache.
        if (ascending
                and self._active_descent_building is not None
                and new_depth == 1 and old_depth == 2):
            self._exit_building_descent()
            return

        # When ascending from an underworld floor, the player may
        # have walked into a sector belonging to a different cluster
        # member than the one they originally descended from. Update
        # hex_player_position before _cache_key is consulted so the
        # shallower floor resolves to the correct surface hex.
        if (ascending and old_depth >= 2
                and self._active_cave_cluster is not None
                and self._underworld_sector_map
                and self.hex_player_position is not None):
            p = self.world.get_component(self.player_id, "Position")
            if p is not None:
                target = self._underworld_sector_map.get((p.x, p.y))
                if target is not None and target != self.hex_player_position:
                    logger.info(
                        "Underworld crossing: %s → %s via sector",
                        self.hex_player_position, target,
                    )
                    self.hex_player_position = target

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

            # Hex-mode underworld: shared floors across the cluster,
            # scaling with depth and cluster size.
            if (self._active_cave_cluster is not None
                    and new_depth >= 2
                    and self.hex_world is not None):
                self._generate_underworld_floor(new_depth)
            elif (
                self._active_descent_building is not None
                and new_depth >= 2
            ):
                # Within an N-floor building descent (ruin, keep
                # cellar, etc.): reuse the descent's template for
                # every floor so the ruin stays a ruin all the way
                # down rather than falling back to the depth-themed
                # dungeon pipeline.
                from nhc.hexcrawl.model import DungeonRef
                from nhc.hexcrawl.seed import dungeon_seed

                descent_link = next(
                    link for link in
                    self._active_descent_building.stair_links
                    if isinstance(link.to_floor, DungeonRef)
                )
                template = descent_link.to_floor.template
                coord = self.hex_player_position
                floor_idx = new_depth - 1
                seed = dungeon_seed(
                    self.seed or 0, coord,
                    f"{template}_descent_{floor_idx}",
                )
                sv = _shape_variety_for_depth(
                    self.shape_variety, new_depth,
                )
                theme = (
                    "crypt"
                    if template.startswith("procedural:crypt")
                    else theme_for_depth(new_depth)
                )
                ft_rng = random.Random(seed)
                ft_w, ft_h = pick_map_size(ft_rng, depth=new_depth)
                params = GenerationParams(
                    width=ft_w, height=ft_h,
                    depth=new_depth, shape_variety=sv, theme=theme,
                    seed=seed, template=template,
                )
                self.generation_params = params
                self.level = generate_level(params)
                # Propagate the active site's faction (rolled at
                # hexcrawl placement time) through every descent
                # floor so a cultist ruin stays a cultist ruin from
                # Floor 1 down to Floor 3.
                site = self._active_site
                surface_faction = (
                    site.surface.metadata.faction
                    if (site and site.surface
                        and site.surface.metadata)
                    else None
                )
                if (surface_faction and self.level
                        and self.level.metadata):
                    self.level.metadata.faction = surface_faction
                # Ruin Floor 3 (depth == RUIN_DESCENT_FLOORS + 1)
                # gets a boss room seeded from FACTION_LEADERS.
                from nhc.dungeon.populator import assign_ruin_boss_room
                from nhc.dungeon.sites.ruin import RUIN_DESCENT_FLOORS
                if (template == "procedural:ruin"
                        and surface_faction
                        and new_depth == RUIN_DESCENT_FLOORS + 1):
                    assign_ruin_boss_room(
                        self.level, surface_faction,
                        random.Random(seed ^ 0xB055),
                    )
            else:
                seed = (self.seed or 0) + new_depth * 997
                sv = _shape_variety_for_depth(
                    self.shape_variety, new_depth,
                )
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
                stair_feature = "stairs_down"
            else:
                stair_feature = "stairs_up"

            # Same-building cross-floor transition: look up the
            # matching StairLink so the player lands on the exact
            # counterpart tile rather than relying on the
            # stair-feature search (whose ascending/descending
            # polarity is inverted for building floors).
            placed = self._place_player_via_building_link(
                old_building_id=old_building_id,
                old_floor_index=old_floor_index,
                old_player_tile=old_player_tile,
            )

            # Underworld floors: when descending, place at the
            # stairs_up that corresponds to the player's entry hex
            # (looked up from _cave_floor2_stairs).
            if (not placed
                    and not ascending
                    and self._active_cave_cluster is not None
                    and new_depth >= 2
                    and self.hex_player_position is not None):
                hp = self.hex_player_position
                key = f"{hp.q}_{hp.r}"
                target_xy = self._cave_floor2_stairs.get(key)
                if target_xy:
                    pos = self.world.get_component(
                        self.player_id, "Position",
                    )
                    if pos:
                        pos.x, pos.y = target_xy
                        pos.level_id = self.level.id
                    placed = True

            if not placed:
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
            cache_key = self.level.id
            cached = self._svg_cache.get(cache_key)
            self.renderer.send_floor_change(
                self.level, self.world, self.player_id,
                self.turn, seed=self.seed or 0,
                floor_svg=cached[1] if cached else None,
                floor_svg_id=cached[0] if cached else None,
                site=self._active_site,
            )
            # Store the rendered SVG for future revisits
            if not cached:
                fresh_svg = self.renderer.floor_svg
                fresh_id = self.renderer.floor_svg_id
                if isinstance(fresh_svg, str):
                    self._svg_cache[cache_key] = (fresh_id, fresh_svg)

    def _place_player_via_building_link(
        self,
        old_building_id: str | None,
        old_floor_index: int | None,
        old_player_tile: tuple[int, int] | None,
    ) -> bool:
        """Place the player on the counterpart stair tile of the
        :class:`StairLink` that matches the cross-floor transition.

        Only activates when both the source and destination levels
        belong to the same building. Used because building stair
        actions flip depth direction, which breaks the generic
        stair-feature search used for dungeon transitions.
        """
        if (old_building_id is None
                or old_floor_index is None
                or old_player_tile is None
                or self._active_site is None
                or self.level is None
                or self.level.building_id is None
                or self.level.building_id != old_building_id):
            return False
        building = next(
            (b for b in self._active_site.buildings
             if b.id == old_building_id),
            None,
        )
        if building is None:
            return False
        new_fi = self.level.floor_index
        target_xy: tuple[int, int] | None = None
        for link in building.stair_links:
            if not isinstance(link.to_floor, int):
                continue
            if (link.from_floor == old_floor_index
                    and link.from_tile == old_player_tile
                    and link.to_floor == new_fi):
                target_xy = link.to_tile
                break
            if (link.to_floor == old_floor_index
                    and link.to_tile == old_player_tile
                    and link.from_floor == new_fi):
                target_xy = link.from_tile
                break
        if target_xy is None:
            return False
        pos = self.world.get_component(self.player_id, "Position")
        if pos:
            pos.x, pos.y = target_xy
            pos.level_id = self.level.id
        return True

    def _place_player_random_floor(self) -> bool:
        """Place player on a random walkable floor tile.

        Used when the player falls through a trapdoor and lands
        at an unpredictable spot.  Returns True if placed.
        """
        rng = get_rng()
        floors: list[tuple[int, int]] = []
        for y in range(self.level.height):
            for x in range(self.level.width):
                tile = self.level.tile_at(x, y)
                if (tile and tile.terrain == Terrain.FLOOR
                        and not tile.feature
                        and tile.surface_type != SurfaceType.CORRIDOR):
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
        """Place hired henchmen on walkable tiles near the player.

        Only henchmen already tagged for the current level move --
        in hex mode that filters out expedition "left-behinds"
        (whose ``Position.level_id == "overland"``) from a cave
        entry so they stay on the overland tile until the player
        returns.
        """
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
            # Skip left-behinds: hex-mode henchmen whose level_id
            # still reads "overland" opted out of this crawl.
            if hpos.level_id != self.level.id:
                continue
            if idx < len(candidates):
                hpos.x, hpos.y = candidates[idx]
            else:
                # Fallback: same tile as player
                hpos.x, hpos.y = ppos.x, ppos.y
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

        # Rebuild the underworld sector map from the cached level so
        # an ascend immediately after restore still routes the player
        # to the correct surface hex. The floor cache itself is
        # pickle-friendly and doesn't persist the map.
        self._refresh_underworld_sector_map(depth)

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
