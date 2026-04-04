# NHC — Nethack-like Crawler: Design Document

## 1. Vision

NHC is a roguelike dungeon crawler built on the Knave TTRPG ruleset with an
Entity-Component-System architecture. It combines traditional roguelike
mechanics (permadeath, procedural generation, identification puzzles) with
an optional LLM-driven typed gameplay mode where the player types natural
language intents and a Game Master LLM interprets, resolves, and narrates
outcomes.

What makes it unique:

- **Dual input modes** -- classic keyboard roguelike *or* typed natural
  language with an LLM Game Master, switchable mid-game with TAB.
- **Dyson Logos style SVG rendering** -- procedural cross-hatching, room
  shadows, and stone detail produce hand-drawn-looking dungeon maps.
- **Full multilingual support** -- English, Catalan, and Spanish, including
  native-authored LLM prompt templates per language.
- **Web and terminal** -- the same game engine drives both a blessed-based
  terminal TUI and an HTML5 Canvas + WebSocket web client.

Current scope: ~26k lines Python, 1239 tests across 69 test files,
78 creatures, 193 items, 13 trap types.

---

## 2. Architecture Overview

```
nhc/
+-- nhc.py                       # Terminal CLI entry point
+-- nhc_web.py                   # Web server entry point
+-- play / server                # Bash launchers (auto-venv)
+-- Dockerfile                   # Python 3.12-slim container
+-- docker-compose.yml           # nhc + Caddy + DuckDNS
+-- nhc/
|   +-- config.py                # 3-tier config (defaults -> ~/.nhcrc -> CLI)
|   +-- core/
|   |   +-- ecs.py               # World store, entity CRUD, component queries
|   |   +-- game.py              # Async game loop, floor management
|   |   +-- events.py            # Event bus (pub/sub with async handlers)
|   |   +-- game_input.py        # Input intent processing
|   |   +-- game_ticks.py        # Per-turn system ticks (doors, prefetch)
|   |   +-- actions/             # Action modules (9 files)
|   |   |   +-- _base.py        # Base action classes, door helpers
|   |   |   +-- _movement.py    # Move, bump, stairs
|   |   |   +-- _combat.py      # Melee, ranged attacks
|   |   |   +-- _items.py       # Pickup, drop, equip, use
|   |   |   +-- _interaction.py # Search, look, doors, chests
|   |   |   +-- _ranged.py      # Throw, ranged targeting
|   |   |   +-- _spells.py      # Scroll/wand activation
|   |   |   +-- _traps.py       # Trap trigger/disarm
|   |   |   +-- _helpers.py     # Shared action utilities
|   |   +-- save.py              # JSON manual save/load
|   |   +-- autosave.py          # Binary autosave (pickle+zlib)
|   +-- entities/
|   |   +-- components.py        # ECS components (dataclasses)
|   |   +-- registry.py          # Auto-discovery entity registry
|   |   +-- creatures/           # 78 creature factories
|   |   +-- items/               # 193 item factories
|   |   +-- features/            # 13 trap factories
|   +-- dungeon/
|   |   +-- generators/
|   |   |   +-- bsp.py           # BSP dungeon generator
|   |   |   +-- classic.py       # Original random placement generator
|   |   |   +-- cellular.py      # Cellular automata cave generator
|   |   +-- generator.py         # Generator dispatch
|   |   +-- classic.py           # Legacy generator wrapper
|   |   +-- model.py             # Level, Tile, Room, Shape data structures
|   |   +-- params.py            # Generation parameter schema
|   |   +-- room_types.py        # Room specialization + painters
|   |   +-- themes.py            # Depth-to-theme mapping
|   |   +-- terrain.py           # Cellular automata water/grass
|   |   +-- populator.py         # Entity placement (encounter groups)
|   |   +-- loader.py            # YAML level loader (multilingual)
|   +-- rendering/
|   |   +-- base.py              # Abstract renderer protocol
|   |   +-- client.py            # Client abstraction
|   |   +-- svg.py               # Dyson Logos style SVG export
|   |   +-- web_client.py        # WebSocket JSON renderer
|   |   +-- graphical/           # Placeholder (not implemented)
|   |   +-- terminal/
|   |       +-- renderer.py      # 4-zone terminal TUI (blessed)
|   |       +-- panels.py        # Status bar + message log
|   |       +-- glyphs.py        # Tile/color mappings (16/256)
|   |       +-- themes.py        # Color theme definitions
|   |       +-- input.py         # Key -> intent mapping
|   |       +-- input_line.py    # Text input widget (typed mode)
|   |       +-- narrative_log.py # Narrative log (typed mode)
|   |       +-- help_overlay.py  # Scrollable help popup
|   +-- narrative/
|   |   +-- gm.py                # LLM Game Master pipeline
|   |   +-- context.py           # Game state -> LLM context
|   |   +-- parser.py            # JSON action plan parser
|   |   +-- fallback_parser.py   # Keyword parser (no LLM)
|   |   +-- narrator.py          # Outcome narration
|   |   +-- dialogue.py          # NPC dialogue system
|   |   +-- quests.py            # Quest tracking
|   |   +-- story.py             # Story compression
|   |   +-- mcp_server.py        # MCP tool server
|   |   +-- prompts.py           # Multilingual prompt loader
|   |   +-- prompts/{en,ca,es}/  # Prompt templates per language
|   +-- rules/
|   |   +-- combat.py            # Attack rolls, damage, healing
|   |   +-- chargen.py           # Knave character generation
|   |   +-- identification.py    # Potion/scroll/ring/wand ID
|   |   +-- advancement.py       # XP and leveling
|   |   +-- loot.py              # Loot table resolution
|   |   +-- conditions.py        # Status effects
|   |   +-- abilities.py         # Special abilities
|   |   +-- magic.py             # Magic system rules
|   +-- ai/
|   |   +-- behavior.py          # Creature AI (chase, attack, flee)
|   |   +-- pathfinding.py       # A* pathfinding (8-directional)
|   |   +-- tactics.py           # Combat AI and morale checks
|   +-- web/
|   |   +-- app.py               # Flask application factory
|   |   +-- ws.py                # WebSocket handler (flask-sock)
|   |   +-- auth.py              # Two-tier auth (admin + player tokens)
|   |   +-- registry.py          # Player registry (JSON-backed)
|   |   +-- sessions.py          # Multi-session manager (max 8)
|   |   +-- config.py            # Web-specific configuration
|   |   +-- static/js/           # Client JS (map, input, ui, ws, debug)
|   |   +-- templates/           # HTML (index.html, admin.html)
|   +-- debug_tools/
|   |   +-- mcp_server.py        # MCP debug server
|   |   +-- tools/               # 6 tool modules (13 tools total)
|   +-- i18n/
|   |   +-- manager.py           # Translation lookup + fallback
|   |   +-- locales/{en,ca,es}.yaml  # ~2000 lines each
|   +-- utils/
|       +-- llm.py               # LLM backends (Ollama, MLX, Anthropic)
|       +-- rng.py               # Seeded RNG + dice roller
|       +-- fov.py               # Shadowcasting FOV
|       +-- log.py               # Debug logging with topic filters
|       +-- spatial.py           # Distance/adjacency helpers
+-- levels/                      # Hand-crafted YAML dungeons
+-- design/                      # Design documents (this file)
+-- tests/unit/                  # 69 test files, 1239 tests
```

---

## 3. Core Engine

### ECS (Entity-Component-System)

The `World` class in `core/ecs.py` is the central store. Entities are
integer IDs; components are Python dataclasses keyed by type name string.
The World provides:

- `create_entity(components)` / `destroy_entity(eid)` -- lifecycle
- `add_component` / `get_component` / `remove_component` -- mutation
- `query(*component_types)` -- iterate entities matching a component set

There is no formal "system" abstraction. Game systems are functions that
query the World directly, called from the game loop or event handlers.

### Event Bus

`core/events.py` implements an async pub/sub event bus. Event types are
dataclasses inheriting from `Event`. Current event types:
`CreatureAttacked`, `CreatureDied`, `ItemPickedUp`, `ItemUsed`,
`DoorOpened`, `LevelEntered`, `SpellCast`, `TrapTriggered`,
`PlayerDied`, `GameWon`, `MessageEvent`, `CustomActionEvent`.

Handlers are registered per event type and called asynchronously when
events are emitted.

### Action Pipeline

Player and creature actions live in `core/actions/`, split across 9
modules by domain: base classes, movement, combat, items, interaction
(including chests), ranged, spells, traps, and shared helpers. Each
action class encapsulates validation (can this action happen?) and
execution (mutate the World + emit events).

### Async Game Loop

`core/game.py` owns the game loop. Each turn:

1. Collect player input (keyboard intent or typed natural language)
2. Resolve the player action
3. Tick creature AI (movement, combat, morale)
4. Process status effects and conditions
5. Run per-turn systems (game_ticks.py)
6. Emit events and update rendering

The game manages multi-floor state: a floor cache preserves entity and
tile state when the player transitions between floors via stairs.

Per-turn systems in `game_ticks.py` include door auto-close (doors
revert to closed after 20 turns if unoccupied) and stairs proximity
prefetch (background generation of the next floor when the player is
within 7 tiles of downstairs).

---

## 4. Knave Rules

NHC implements the Knave TTRPG ruleset with minor adaptations for
real-time roguelike play.

### Abilities

Six abilities (Strength, Dexterity, Constitution, Intelligence, Wisdom,
Charisma) with bonus values. The bonus is the modifier; defense is
bonus + 10. Character generation rolls 3d6-keep-lowest for each ability,
producing bonus values 1-6.

### Combat

- **Attack**: d20 + ability bonus vs target's armor defense
- **Damage**: weapon dice pool (e.g. d6 for a sword)
- **Healing**: potions restore fixed or rolled HP
- **Critical hits**: natural 20 always hits
- **Morale**: creatures check morale when HP drops below threshold;
  failure causes fleeing behavior

### Magic

Scrolls and wands are the primary magic system. Scrolls are single-use;
wands have limited charges that recharge over time. Spell effects are
defined in `rules/magic.py`. Rings provide passive buffs while equipped.
All magic items use the identification system (see section 6).

### Inventory

Inventory uses a slot system: each item has a slot cost, and the player
has a maximum number of slots (Constitution-derived). Inventory slots
double as spell slots -- carrying a scroll occupies the same resource
as carrying equipment.

### Advancement

XP is gained from defeating creatures. Level-up increases HP and allows
improving one ability bonus by +1. XP thresholds follow a standard
progression curve defined in `rules/advancement.py`.

---

## 5. Dungeon Generation

The primary generator is BSP (Binary Space Partition) in
`dungeon/generators/bsp.py`. See `design/dungeon_generator.md` for the
full pipeline design.

### BSP Pipeline Summary

1. **Layout** -- recursively subdivide the map into cells; carve a room
   in each leaf cell. Five room shapes: rect, circle, octagon, cross,
   hybrid. Shape variety is configurable (default 30% non-rectangular).
2. **Connect** -- build corridors along the BSP tree (sibling pairs),
   then add extra loop connections to prevent dead ends. Corridors use
   L-shaped or straight paths.
3. **Specialize** -- assign room types: standard, treasury, armory,
   library, crypt, shrine, garden, trap_room. Room painters populate
   each room with thematic content (items, creatures, traps, features).
4. **Terrain** -- cellular automata pass adds water and grass patches.
   Theme parameters control density per dungeon theme (crypt, cave,
   sewer, castle, forest). Theme is auto-selected by depth via
   `themes.py` (dungeon→crypt→cave→castle→abyss). Level feelings
   (flooded, overgrown, barren) can override defaults.
5. **Populate** -- place encounter groups, items, and traps based on
   depth-scaled difficulty tiers.
6. **Features** -- place stairs, doors (including locked and secret),
   and wall fixtures.

The classic generator (`dungeon/classic.py`) remains available as an
alternative. A cellular automata cave generator
(`generators/cellular.py`) produces organic cave layouts using random
fill, automata smoothing, flood-fill region detection, and L-shaped
corridor connections between caverns.

Hand-authored YAML levels can be loaded via `dungeon/loader.py` for
scripted floors or tutorials.

---

## 6. Entity System

### Registry Pattern

`entities/registry.py` provides an auto-discovery registry. Entity
factories are decorated with `@EntityRegistry.register_creature` or
`@EntityRegistry.register_item` and return a dict of component name
to component instance. The registry auto-discovers all factory modules
on first access.

### Content Stats

| Category   | Count | Details                                      |
|------------|-------|----------------------------------------------|
| Creatures  | 78    | Full BEB bestiary, AI behaviors, factions     |
| Items      | 193   | 38 scrolls, 14 potions, 14 wands, 8 rings     |
|            |       | 119 equipment (weapons, armor, tools, etc.)    |
| Traps      | 13    | Pit, fire, poison, paralysis, teleport, etc.  |

### Identification System

Unidentified items show a randomized appearance rather than their true
name. Appearances are shuffled per game seed for consistency within
a run:

- **Potions** -- colors (ruby, azure, emerald, etc.)
- **Scrolls** -- cryptic labels (ZELGO MER, etc.)
- **Rings** -- gem types (ruby ring, sapphire ring, etc.)
- **Wands** -- wood types (oak wand, willow wand, etc.)

Items are identified by use (quaffing a potion, reading a scroll,
zapping a wand) or via identification scrolls. Once identified, all
items of that type show their true name for the rest of the game.
See `design/magic_items.md` for ring and wand mechanics.

---

## 7. Rendering

### Terminal TUI

The blessed-based terminal renderer (`rendering/terminal/renderer.py`)
uses a 4-zone layout:

1. **Map** -- shadowcasting FOV, 16 or 256 color modes, box-drawing
   walls (Unicode characters: corner, tee, cross junctions)
2. **Status bar** -- HP, floor, turn count, level, gold
3. **Message log** -- scrollable combat/event messages
4. **Inventory sidebar** -- equipment and carried items

In typed mode, zones 3-4 are replaced with a narrative log and text
input widget.

### Web Client

The web client (`rendering/web_client.py` + `web/static/js/`) renders
the dungeon using a layered approach:

- **SVG base layer** -- Dyson Logos style dungeon map (cross-hatching,
  room shadows, stone floor detail, generated by `rendering/svg.py`)
- **4 Canvas layers** -- entities, FOV overlay, UI highlights, and
  animation, composited over the SVG
- **WebSocket** -- JSON protocol for game state updates, entity
  positions, FOV changes, and player input

The SVG renderer produces black-and-white maps with procedural
cross-hatching using Shapely geometry and Perlin noise. SVG output is
cached and invalidated only on floor transitions.

### Web Status Bar

The web client uses a 3-line status bar:

1. **Line 1** -- location, depth, turn, level, gold, HP bar
2. **Line 2** -- name, ability scores, equipped items (interactive:
   click for primary action, right-click context menu), AC
3. **Line 3** -- backpack inventory with slot count, interactive items

### Point-and-Click

The web client supports point-and-click interaction: clicking a tile
sends a move/interact intent. An action toolbar and inventory panel
provide mouse-driven access to all game actions.

---

## 8. Narrative & LLM

### GM Pipeline

The typed gameplay mode routes player input through an LLM Game Master.
See `design/typed_gameplay.md` for the full pipeline design.

Pipeline stages:

1. **Context build** (`narrative/context.py`) -- assembles game state
   into a structured prompt: visible entities, player stats, inventory,
   recent history, compressed story summary.
2. **Interpret** (`narrative/gm.py`) -- the LLM receives the context +
   player's typed intent and produces a JSON action plan (which game
   actions to execute, with parameters).
3. **Parse** (`narrative/parser.py`) -- validates and extracts actions
   from the LLM JSON response. Falls back to keyword parsing
   (`fallback_parser.py`) if the LLM is unavailable or returns invalid
   output.
4. **Execute** -- resolved actions are dispatched through the normal
   action pipeline.
5. **Narrate** (`narrative/narrator.py`) -- the LLM describes the
   outcome with narrative flavor, grounded in the actual mechanical
   results.

### LLM Backends

Three backends in `utils/llm.py`, sharing an abstract `LLMBackend`
interface with streaming support:

- **Ollama** -- local models via the Ollama API
- **MLX** -- Apple Silicon native inference via MLX
- **Anthropic** -- Claude API for cloud inference

Backend selection is configurable via `~/.nhcrc` or CLI args. When no
backend is available, the fallback keyword parser provides degraded
but functional typed mode.

### Story Compression

`narrative/story.py` periodically summarizes accumulated narrative
history to fit within the LLM context window, preserving key plot
points and quest state.

### Prompts

Prompt templates live in `narrative/prompts/{en,ca,es}/`. Each language
has independently authored prompts (not machine-translated) tuned for
that language's LLM performance characteristics.

---

## 9. Web Server

### Flask + WebSocket

`web/app.py` creates the Flask application with flask-sock for
WebSocket support. Each WebSocket connection is tied to a game session;
the WS handler thread owns the socket, reading input into a queue and
draining output via a sender thread.

`create_app()` performs one-time startup work: it calls
`EntityRegistry.discover_all()` exactly once (previously this ran on
every new game, putting import I/O on the concurrent-init hot path),
pre-renders the hatch SVG, and creates the dungeon generation pool
described below.

### Authentication

Two-tier token auth (`web/auth.py`):

- **Admin** -- master token + LAN-only restriction, for `/admin` routes
  and the admin panel (`admin.html`)
- **Player** -- per-player tokens validated against a persistent
  `PlayerRegistry` (`web/registry.py`), backed by a JSON file with
  thread-safe atomic writes

Tokens can be provided via cookie (`nhc_token`), `Authorization` header,
or query parameter (`?token=...`). Query params take precedence to allow
fresh link clicks to override stale cookies.

### Session Manager

`web/sessions.py` manages up to 8 concurrent game sessions. Each session
runs its own game loop in a separate thread. A reaper removes stale
disconnected sessions.

### Concurrency Model

The server runs as a single gunicorn gevent worker process. This is
intentional: keeping all session state (SessionManager, PlayerRegistry,
WebSocket connections, rate limiter) in one process avoids the need
for a shared session store. Gevent's greenlets provide per-worker
concurrency for I/O-bound request handling.

CPU parallelism comes from a separate layer. `create_app()` creates a
`ProcessPoolExecutor` sized via the `NHC_GEN_WORKERS` env var (default
`os.cpu_count()`), stored at `app.config["GEN_POOL"]`. Dungeon
generation is pure Python and CPU-bound; the `game_new` and
`game_resume` routes offload it to the pool via
`asyncio.run(game.initialize(..., executor=gen_pool))`, so the gevent
hub stays responsive while levels are generated in parallel across
cores. On a quad-core host, four players can have their dungeons
generated simultaneously on four cores.

The pool is pinned to the `spawn` multiprocessing start method.
Gunicorn's gevent worker monkey-patches `os.fork` before `create_app`
runs, and forked children inherit a gevent hub tied to the parent's
kernel resources that hangs on first use. Spawn re-execs a clean
Python interpreter per worker and re-imports the dungeon modules
once at worker startup; workers are long-lived and reused across
requests.

### Admin Panel

The admin HTML page provides session monitoring, player management
(create, revoke tokens, regenerate links), and server controls.

---

## 10. Deployment

### Docker Stack

The production deployment uses Docker Compose with three services:

- **nhc** -- Python 3.12-slim container running gunicorn with gevent
  worker, single worker process, exposed on port 8080
- **caddy** -- reverse proxy with automatic TLS via Let's Encrypt
- **duckdns** -- dynamic DNS updater for the public hostname

Data persists in a `/var/nhc` volume (autosaves, player registry).

### Environment Variables

- `NHC_AUTH_TOKEN` -- admin token (required in production)
- `NHC_MAX_SESSIONS` -- concurrent session cap (default 8)
- `NHC_GEN_WORKERS` -- size of the dungeon generation pool
  (default 4 in the Dockerfile and systemd unit, targeting a
  quad-core SBC; overridable via `docker run --env`, compose
  environment, or the systemd override file)
- `NHC_DATA_DIR` -- persistent data directory (default `/var/nhc`)
- `NHC_EXTERNAL_URL` -- public URL for link generation
- `DUCKDNS_SUBDOMAIN`, `DUCKDNS_TOKEN` -- dynamic DNS credentials

Health checks poll `/health` every 30 seconds.

---

## 11. Internationalization

### Three Languages

English, Catalan, and Spanish locale files in `i18n/locales/`, each
~2000 lines of YAML. Coverage includes creature names and descriptions,
item names, UI strings, room descriptions, status messages, and combat
narration.

### Lookup and Fallback

`i18n/manager.py` resolves dotted keys
(e.g. `t("creature.goblin.name")`) with a fallback chain: current
language -> English -> the key itself. This ensures missing translations
degrade gracefully.

### Gender Support

Catalan and Spanish locale entries include a `gender` field (`"m"` or
`"f"`) for grammatical gender agreement in generated text. The
translation manager uses this when constructing phrases with articles
or adjectives.

### Prompt Localization

LLM prompt templates are authored natively per language (not translated
from English), stored in `narrative/prompts/{en,ca,es}/`.

---

## 12. Save System

### JSON Manual Save

`core/save.py` serializes the full game state to JSON: World (all
entities and components), level metadata, floor cache (previously
visited floors), player state, identification mappings, and turn count.
Triggered by the player pressing `S`; loaded with `L`.

### Binary Autosave

`core/autosave.py` uses pickle + zlib compression for fast periodic
saves. Autosave is throttled to avoid performance impact. On startup,
the game detects existing autosaves and offers restore. Autosave files
are deleted on clean quit or explicit save.

### Multi-Floor Persistence

When the player transitions between floors via stairs, the current
floor state is serialized into the floor cache. Returning to a
previously visited floor restores its exact state (entities, items,
doors, terrain modifications).

---

## 13. Debug Tools

### MCP Debug Server

`debug_tools/mcp_server.py` exposes 13 MCP tools for game state
inspection, organized across 6 tool modules:

- **game_state** -- game snapshot, entity list, tile info
- **dungeon** -- room info, door analysis, tile map, tile search
- **rendering** -- layer state, FOV analysis
- **svg_query** -- SVG tile element inspection
- **exports** -- list and read debug export files
- **autosave** -- autosave diagnostics (seed, turn, depth, entities)

### God Mode

Activated with `--god` flag. Provides invulnerability, full item
identification, complete map reveal, and a debug panel overlay in
the terminal TUI.

---

## 14. TODO & Future Enhancements

### Dungeon Generation

- **Boss floors** -- every 5th depth with themed boss encounters.
- **Shop rooms** -- rooms with merchant NPCs for buying/selling.
  Would require NPC interaction UI and economy balancing.
- **Level feelings** -- flooded, overgrown, barren variants. Framework
  exists in `terrain.py` with `FEELINGS` list and seed probability
  overrides, but selection logic is minimal.

### Narrative & NPCs

- **NPC dialogue expansion** -- `narrative/dialogue.py` is functional
  but content is sparse. Needs more dialogue trees, merchant
  interactions, quest givers.
- **Quest system expansion** -- `narrative/quests.py` is functional
  but could be deeper integrated into the game loop and LLM pipeline.
- **GM pipeline integration tests** -- context building + action plan
  parsing + narration end-to-end tests are missing.

### Rendering & UI

- **Graphical renderer** -- pygame/tcod-based renderer. Placeholder
  directory exists at `rendering/graphical/` but no implementation.
- **Key rebinding** -- all key mappings are hardcoded in
  `rendering/terminal/input.py`. A configuration-driven binding
  system would allow customization.
- **Persistent high score table** -- death screen shows cause of death
  and stats, but scores are not persisted across runs.

### Mechanics

- **Hunger/torch mechanics** -- classic roguelike resource management
  systems. Neither is implemented.
- **More trap variety** -- web, gas, and other trap types beyond the
  current 13.
- **Ring passive effect tests** -- mending HP regeneration and
  detection auto-reveal are implemented but lack test coverage.
- **Ascend stairs action tests** -- stair transitions and floor state
  cleanup on ascent are untested.
