# NHC — Nethack-like Crawler

## Design Document

### 1. Vision

NHC is a roguelike dungeon crawler in the tradition of Nethack, implemented in
Python with gameplay mechanics drawn from **Knave** (Ben Milton's OSR ruleset).
The game combines classic procedural dungeon exploration with LLM-driven emergent
narrative — the dungeon is not just a series of rooms but a living story shaped
by player actions and AI narration.

### 2. Design Principles

- **Modularity over monolith.** Every subsystem (rendering, rules, generation,
  entities) is behind an abstract interface so implementations can be swapped.
- **Registry/plugin pattern for content.** Creatures, items, spells, and room
  features are self-registering modules — adding a new monster means adding one
  file.
- **Data-driven dungeons.** Dungeon levels are a serializable format (YAML/JSON)
  that can be authored by hand, generated procedurally, or inspected by an LLM.
- **Renderer-agnostic core.** The game engine knows nothing about ASCII or pixels.
  Rendering is a pluggable backend; the first implementation is a terminal TUI.
- **LLM as narrative co-pilot.** Game state is exposed through a structured
  interface (and optionally MCP tools) so an LLM can weave story, dialogue,
  and world reactions around the mechanical events.

---

### 3. Architecture Overview

```
nhc/
├── nhc/                        # Main package
│   ├── __init__.py
│   ├── main.py                 # Entry point, session bootstrap
│   │
│   ├── core/                   # Engine core (renderer-agnostic)
│   │   ├── __init__.py
│   │   ├── game.py             # Game loop, turn sequencing
│   │   ├── world.py            # World state: dungeon stack, clock, factions
│   │   ├── ecs.py              # Entity-Component-System foundation
│   │   ├── events.py           # Event bus (pub/sub for decoupled systems)
│   │   ├── actions.py          # Action resolution pipeline
│   │   └── save.py             # Serialization / save-load
│   │
│   ├── rules/                  # Knave mechanics
│   │   ├── __init__.py
│   │   ├── abilities.py        # STR, DEX, CON, INT, WIS, CHA (defense-based)
│   │   ├── combat.py           # Attack rolls, damage, morale
│   │   ├── magic.py            # Spell slots = inventory slots (Knave rule)
│   │   ├── advancement.py      # XP, leveling, HP
│   │   └── conditions.py       # Status effects, death & dying
│   │
│   ├── dungeon/                # Dungeon representation & generation
│   │   ├── __init__.py
│   │   ├── model.py            # Level, Room, Corridor, Tile, Door, Stairs
│   │   ├── loader.py           # Load static levels from disk (YAML)
│   │   ├── generator.py        # Procedural generation interface
│   │   ├── generators/         # Pluggable generator implementations
│   │   │   ├── __init__.py
│   │   │   ├── bsp.py          # Binary Space Partition
│   │   │   ├── cellular.py     # Cellular automata (caves)
│   │   │   └── classic.py      # Room-and-corridor (donjon-style)
│   │   ├── params.py           # Generation parameter schema
│   │   └── populator.py        # Place creatures, items, traps, features
│   │
│   ├── entities/               # Registry-based entity catalogs
│   │   ├── __init__.py
│   │   ├── registry.py         # Auto-discovery registry
│   │   ├── base.py             # Base entity, creature, item classes
│   │   ├── creatures/          # One module per creature
│   │   │   ├── __init__.py
│   │   │   ├── goblin.py
│   │   │   ├── skeleton.py
│   │   │   ├── dragon.py
│   │   │   └── ...
│   │   ├── items/              # One module per item (or item family)
│   │   │   ├── __init__.py
│   │   │   ├── sword.py
│   │   │   ├── healing_potion.py
│   │   │   ├── spell_tome.py
│   │   │   └── ...
│   │   └── features/           # Traps, altars, fountains, etc.
│   │       ├── __init__.py
│   │       ├── trap_pit.py
│   │       ├── fountain.py
│   │       └── ...
│   │
│   ├── ai/                     # Creature AI / behavior
│   │   ├── __init__.py
│   │   ├── behavior.py         # Behavior tree / state machine interface
│   │   ├── pathfinding.py      # A* on dungeon grid
│   │   └── tactics.py          # Combat AI, morale checks
│   │
│   ├── rendering/              # Pluggable rendering backends
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract renderer protocol
│   │   ├── terminal/           # ASCII / TUI backend
│   │   │   ├── __init__.py
│   │   │   ├── renderer.py     # Curses/blessed renderer
│   │   │   ├── glyphs.py       # Entity → ASCII glyph mapping
│   │   │   ├── panels.py       # HUD, inventory, message log panels
│   │   │   └── input.py        # Keyboard input handler
│   │   └── graphical/          # Future: pygame / tcod backend
│   │       └── __init__.py
│   │
│   ├── narrative/              # LLM-driven storytelling
│   │   ├── __init__.py
│   │   ├── narrator.py         # Narrative engine: event → story text
│   │   ├── context.py          # Game state summarizer for LLM context
│   │   ├── dialogue.py         # NPC dialogue generation
│   │   ├── quests.py           # Emergent quest generation
│   │   └── mcp_server.py       # MCP tool server for external LLM access
│   │
│   └── utils/                  # Shared utilities
│       ├── __init__.py
│       ├── rng.py              # Seeded RNG, dice roller (d20, 2d6, etc.)
│       ├── fov.py              # Field of view / line of sight
│       └── spatial.py          # Grid math, coordinates, rectangles
│
├── levels/                     # Static dungeon level files (YAML)
│   ├── tutorial.yaml
│   └── tomb_of_horrors.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── samples/
│
├── debug/                      # Temporary dev artifacts
│   └── .gitkeep
│
├── docs/
│   └── knave_reference.md      # Knave rules quick-reference
│
├── pyproject.toml
└── CLAUDE.md
```

---

### 4. Core Engine

#### 4.1 Entity-Component-System (ECS)

The game uses a lightweight ECS to keep data and behavior orthogonal. This is
critical for the plugin pattern — a new creature is just a new bundle of
components, not a new class hierarchy.

```python
# Core component examples
@dataclass
class Position:
    x: int
    y: int
    level_id: str

@dataclass
class Renderable:
    glyph: str          # ASCII char: '@', 'g', 'D'
    color: str          # Terminal color name or hex for graphical
    render_order: int   # Layer priority

@dataclass
class Stats:           # Knave ability scores (defense values)
    strength: int       # Melee attack/damage bonus, carry capacity
    dexterity: int      # Initiative, ranged, armor defense
    constitution: int   # HP bonus, poison saves
    intelligence: int   # Spell slots, lore
    wisdom: int         # Perception, willpower saves
    charisma: int       # Reaction rolls, morale, followers

@dataclass
class Health:
    current: int
    maximum: int

@dataclass
class Inventory:
    slots: list[EntityId]   # Knave: inventory slots = equipment capacity
    max_slots: int          # CON-based in Knave

@dataclass
class AI:
    behavior: str           # Behavior tree ID
    morale: int             # Knave morale threshold
    faction: str
```

Entity creation is declarative — a creature module exports a factory:

```python
# nhc/entities/creatures/goblin.py
from nhc.entities.registry import register_creature

@register_creature("goblin")
def create_goblin():
    return {
        "Stats": Stats(strength=1, dexterity=2, constitution=1,
                       intelligence=0, wisdom=0, charisma=-1),
        "Health": Health(current=4, maximum=4),
        "Renderable": Renderable(glyph="g", color="green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="goblinoid"),
        "Loot": LootTable(entries=[("gold", 2, "2d6"), ("dagger", 0.3)]),
        "Description": Description(
            name="Goblin",
            short="a snarling goblin",
            long="A wiry, green-skinned creature with yellowed fangs "
                 "and a rusty blade."
        ),
    }
```

#### 4.2 Event Bus

All game events flow through a central bus. This enables decoupled systems: the
combat system emits `CreatureDied`, the narrative system listens and generates
story text, the renderer listens and shows animations.

```python
class EventBus:
    def subscribe(self, event_type: type,
                  handler: Callable[..., Awaitable[None]]) -> None: ...
    async def emit(self, event: Event) -> None:
        """Dispatch to all subscribers. Fast handlers run inline,
        slow handlers (LLM calls) are spawned as background tasks."""
    def emit_fire_and_forget(self, event: Event) -> None:
        """Queue event for background processing (narrative, logging)."""

# Event hierarchy
@dataclass
class Event:
    turn: int
    timestamp: float

class CreatureAttacked(Event):
    attacker: EntityId
    target: EntityId
    roll: int
    damage: int
    hit: bool

class CreatureDied(Event):
    entity: EntityId
    killer: EntityId | None
    cause: str

class ItemPickedUp(Event):
    entity: EntityId
    item: EntityId

class DoorOpened(Event):
    entity: EntityId
    position: Position

class LevelEntered(Event):
    entity: EntityId
    level_id: str
    depth: int

class SpellCast(Event):
    caster: EntityId
    spell: str
    targets: list[EntityId]
```

The narrative module subscribes to all events and maintains a running story
context that it feeds to the LLM.

#### 4.3 Action Pipeline

Player and creature actions go through a resolution pipeline that allows
validation, modification by equipment/status effects, and event emission:

```
Input → Action → Validate → Modifiers → Execute → Events → Render
```

```python
class Action(ABC):
    actor: EntityId
    async def validate(self, world: World) -> bool: ...
    async def execute(self, world: World) -> list[Event]: ...

class MeleeAttackAction(Action):
    target: EntityId

class MoveAction(Action):
    direction: Direction

class UseItemAction(Action):
    item: EntityId
    target: EntityId | None

class CastSpellAction(Action):
    spell_id: str
    targets: list[EntityId]
```

#### 4.4 Game Loop

Turn-based with energy/speed system for creatures that act at different rates.
The loop is `async` — player input is awaited (non-blocking), and LLM narrative
generation runs as background tasks that deliver text to the message log when
ready.

```python
class GameLoop:
    async def run(self):
        while self.running:
            # 1. Await player input (yields control to background tasks)
            action = await self.input_handler.get_action()

            # 2. Resolve player action
            events = await self.resolve(action)

            # 3. Advance world clock
            self.world.tick()

            # 4. Process creature turns (energy-based)
            for creature in self.world.active_creatures():
                if creature.energy >= TURN_COST:
                    ai_action = self.ai.decide(creature, self.world)
                    events += await self.resolve(ai_action)
                    creature.energy -= TURN_COST

            # 5. Process timed effects, hunger, torches, etc.
            events += self.world.process_effects()

            # 6. Feed events to narrative engine (background task)
            self.narrative.enqueue_events(events)

            # 7. Render (includes any narrative text that arrived)
            self.renderer.render(self.world)

    async def resolve(self, action: Action) -> list[Event]:
        if not await action.validate(self.world):
            return []
        events = await action.execute(self.world)
        for event in events:
            await self.event_bus.emit(event)
        return events
```

#### 4.5 Async Architecture

The game uses `asyncio` as its concurrency backbone. This is not about
parallelism (the game is single-threaded) — it's about **non-blocking I/O**
so that slow operations (LLM calls, file I/O, future network play) never
freeze the game.

**What runs async:**

| Component | Why async | Pattern |
|-----------|-----------|---------|
| Game loop | Orchestrator — awaits input, yields to background work | `async def run()` |
| Player input | Terminal read blocks; async lets background tasks proceed | `await input_handler.get_action()` |
| LLM API calls | Network I/O, 0.5–3s latency | `asyncio.create_task()` — fire and forget |
| Narrative engine | Batches events, calls LLM in background | Background task with `asyncio.Queue` |
| MCP server | stdio transport is inherently async | `async def handle_request()` |
| Save/load | File I/O (minor, but keeps interface uniform) | `await aiofiles.open()` |
| Event bus handlers | Some handlers are fast (pure logic), some slow (LLM) | Sync handlers called inline, async handlers spawned |

**What stays synchronous:**

| Component | Why sync |
|-----------|----------|
| Combat resolution | Pure computation, microseconds |
| FOV calculation | CPU-bound, fast |
| Dungeon generation | CPU-bound, runs once per level |
| Creature AI decisions | Pure logic on local state |
| ECS queries | In-memory data access |

**Async pattern for narrative:**

The key insight is that LLM narration is a *background enrichment*, not a
blocking requirement. The game must remain responsive while the LLM thinks.

```python
class NarrativeEngine:
    def __init__(self, llm_client: AsyncLLMClient):
        self._queue: asyncio.Queue[list[Event]] = asyncio.Queue()
        self._pending_text: list[str] = []  # Rendered next frame
        self._task: asyncio.Task | None = None

    def start(self):
        """Start the background narrative processing loop."""
        self._task = asyncio.create_task(self._process_loop())

    async def _process_loop(self):
        while True:
            events = await self._queue.get()
            priority = self._classify(events)
            if priority == Priority.SKIP:
                continue
            context = self._build_context(events)
            text = await self._llm_client.generate(context)
            # Thread-safe append; renderer picks this up next frame
            self._pending_text.append(text)

    def enqueue_events(self, events: list[Event]):
        self._queue.put_nowait(events)

    def drain_text(self) -> list[str]:
        """Called by renderer each frame to collect ready narrative."""
        texts = self._pending_text[:]
        self._pending_text.clear()
        return texts
```

**Entry point:**

```python
# nhc/main.py
import asyncio

async def main():
    game = Game(config)
    await game.initialize()
    await game.run()

if __name__ == "__main__":
    asyncio.run(main())
```

**Terminal input with asyncio:**

Raw terminal input (curses/blessed) doesn't natively support `await`. The
input handler uses `loop.add_reader()` on stdin or runs the blocking read
in a thread executor:

```python
class AsyncTerminalInput:
    async def get_action(self) -> Action:
        loop = asyncio.get_event_loop()
        key = await loop.run_in_executor(None, self._blocking_read)
        return self._key_to_action(key)
```

This ensures background tasks (narrative generation, MCP requests) continue
processing while the game waits for the player to press a key.

---

### 5. Knave Rules Implementation

Knave's elegance makes it ideal for a roguelike — the rules are minimal but
complete. Key mechanical mappings:

#### 5.1 Abilities

Knave uses **defense** values (ability + 10) for saves and **bonus** values
(ability score itself) for modifiers. Characters start with abilities 1–6
(rolled as 3d6, keep lowest).

| Ability | Bonus applies to | Defense (bonus + 10) saves against |
|---------|------------------|------------------------------------|
| STR | Melee attacks, forced doors | Grappling, crushing |
| DEX | Ranged attacks, initiative | Dodging, reflexes |
| CON | Hit points per level | Poison, disease |
| INT | Number of languages | Illusions, arcane effects |
| WIS | Detecting traps/secrets | Charm, fear |
| CHA | Reaction rolls, hirelings | Persuasion, leadership |

#### 5.2 Combat

```
Attack roll: d20 + ability bonus ≥ target's Armor Defense
Damage: weapon die + STR bonus (melee) or DEX bonus (ranged)
Critical: natural 20 → max damage
```

Armor is inventory-based: each armor piece takes 1 slot and gives +1 Armor
Defense (base 10 unarmored). Maximum armor = shield + helmet + body = 15 defense.

#### 5.3 Magic (Inventory-as-Spellbook)

Knave's signature: **spells are items**. A spell tome takes one inventory slot.
Casting a spell consumes it for the day (not permanently). This maps perfectly
to a roguelike inventory system — finding a new spell tome is like finding a
magic weapon.

#### 5.4 Inventory

Inventory slots = CON defense (typically 11–16). Items have a slot cost:

| Item type | Slots |
|-----------|-------|
| Most items | 1 |
| Heavy weapons (2H) | 2 |
| Armor (body) | 2 |
| 100 coins | 1 |
| Bundled light items (arrows ×20) | 1 |

#### 5.5 Advancement

| Level | HP | Ability improvements |
|-------|-----|---------------------|
| 1 | d8 | Starting scores |
| 2+ | +d8/level | Roll 3d6 per ability; if > current, +1 |
| Max | 10 | Level 10 cap |

---

### 6. Dungeon Format

Dungeon levels are represented as a structured format that serves three
consumers: the game engine, static file storage, and LLM reasoning.

#### 6.1 Level Model

```python
@dataclass
class Level:
    id: str                          # Unique identifier
    name: str                        # "The Goblin Warrens"
    depth: int                       # Dungeon depth (difficulty scaling)
    width: int
    height: int
    tiles: list[list[Tile]]          # 2D grid
    rooms: list[Room]                # Room metadata (for AI/narrative)
    corridors: list[Corridor]
    entities: list[EntityPlacement]  # Creatures, items, features
    metadata: LevelMetadata          # Theme, difficulty, narrative hooks

@dataclass
class Tile:
    terrain: Terrain                 # FLOOR, WALL, WATER, LAVA, etc.
    feature: str | None              # door, stairs_up, stairs_down, trap
    explored: bool
    visible: bool

@dataclass
class Room:
    id: str
    rect: Rect                       # Bounding box
    tags: list[str]                  # ["treasure", "boss", "shrine"]
    description: str                 # For narrative: "a damp chamber..."
    connections: list[str]           # Connected room/corridor IDs

@dataclass
class LevelMetadata:
    theme: str                       # "crypt", "cave", "castle"
    difficulty: int                  # 1-10
    narrative_hooks: list[str]       # Story seeds for LLM
    faction: str | None              # Dominant faction
    ambient: str                     # "dripping water echoes..."
```

#### 6.2 YAML Serialization (Static Levels)

```yaml
id: tutorial_crypt
name: "The Forgotten Crypt"
depth: 1
width: 40
height: 25
theme: crypt
difficulty: 1
ambient: "Cold air seeps from cracks in the ancient stone."

narrative_hooks:
  - "A faded inscription warns of a sealed evil below."
  - "Scratch marks on the walls suggest something clawed its way out."

rooms:
  - id: entry
    x: 2
    y: 2
    width: 8
    height: 6
    tags: [entry, safe]
    description: "A crumbling antechamber with broken urns."
    connections: [corridor_1]

  - id: tomb
    x: 20
    y: 10
    width: 10
    height: 8
    tags: [boss, treasure]
    description: "A grand burial chamber. A stone sarcophagus dominates."
    connections: [corridor_2]

corridors:
  - id: corridor_1
    points: [[10, 5], [15, 5], [15, 12]]
    connects: [entry, corridor_2]

  - id: corridor_2
    points: [[15, 12], [20, 12]]
    connects: [corridor_1, tomb]

# Tile overrides (sparse — generator fills defaults)
tile_overrides:
  - {x: 10, y: 5, feature: door_closed}
  - {x: 20, y: 12, feature: door_locked}
  - {x: 5, y: 4, feature: stairs_up}
  - {x: 25, y: 14, feature: stairs_down}

entities:
  - type: creature
    id: skeleton
    position: {x: 22, y: 13}
    patrol: [[22, 13], [27, 13], [27, 16]]

  - type: creature
    id: skeleton
    position: {x: 24, y: 15}

  - type: item
    id: healing_potion
    position: {x: 6, y: 5}

  - type: feature
    id: trap_pit
    position: {x: 15, y: 8}
    hidden: true
    dc: 12
```

The tile grid itself can be stored as an ASCII map block for hand-authored levels:

```yaml
map: |
  ########################################
  #......##                              #
  #......##                              #
  #......+.........                      #
  #......##       .                      #
  #......##       .                      #
  ########        .                      #
                  .                      #
              #####.######               #
              #..........#               #
              #..........+...............#
              #..........#               #
              #..........#               #
              #..........#               #
              ############               #
  ########################################

legend:
  '#': wall
  '.': floor
  '+': door_closed
  '<': stairs_up
  '>': stairs_down
  '~': water
  '^': trap (hidden)
  ' ': void (unused space)
```

---

### 7. Procedural Dungeon Generation

#### 7.1 Generator Interface

```python
class DungeonGenerator(ABC):
    @abstractmethod
    def generate(self, params: GenerationParams) -> Level: ...

@dataclass
class GenerationParams:
    width: int = 80
    height: int = 50
    depth: int = 1                    # Affects difficulty scaling
    room_count: Range = Range(5, 15)
    room_size: Range = Range(4, 12)
    corridor_style: str = "straight"  # straight, bent, organic
    density: float = 0.4              # Room coverage ratio
    connectivity: float = 0.8         # Extra corridors (1.0 = fully connected)
    theme: str = "dungeon"            # crypt, cave, castle, sewer
    seed: int | None = None           # Reproducibility
    # Feature toggles
    dead_ends: bool = True
    secret_doors: float = 0.1         # Probability per eligible wall
    water_features: bool = False
    multiple_stairs: bool = False
```

#### 7.2 Generator Implementations

**Classic Room-and-Corridor** (`classic.py`):
Donjon-style. Places rectangular rooms, connects them with L-shaped or
straight corridors. Room placement uses rejection sampling with overlap
checks. Produces clean, traditional dungeon layouts.

**BSP** (`bsp.py`):
Recursively partitions the map into cells via binary splits, then carves a
room inside each leaf cell. Guarantees non-overlapping rooms and produces a
natural tree-structured connectivity graph. Good for structured levels (castles,
fortresses).

**Cellular Automata** (`cellular.py`):
Starts with random noise, applies B5678/S45678-style rules to produce organic
cave systems. Post-processes to ensure connectivity (flood fill → bridge
isolated regions). Good for natural caves and caverns.

All generators feed into the **populator** which places entities based on depth,
theme, and room tags:

```python
class Populator:
    def populate(self, level: Level, params: PopulationParams) -> Level:
        """Place creatures, items, traps, and features."""
        for room in level.rooms:
            difficulty_budget = self.budget_for(room, level.depth)
            creatures = self.creature_registry.select(
                budget=difficulty_budget,
                theme=level.metadata.theme,
                tags=room.tags,
            )
            items = self.item_registry.select(
                depth=level.depth,
                room_tags=room.tags,
            )
            # Place within room bounds, respecting spacing rules
            self.place_entities(room, creatures + items, level)
        return level
```

---

### 8. Entity Registry / Plugin Pattern

The registry auto-discovers entity modules at startup by scanning the
`creatures/`, `items/`, and `features/` directories.

```python
# nhc/entities/registry.py
class EntityRegistry:
    _creatures: dict[str, Callable] = {}
    _items: dict[str, Callable] = {}
    _features: dict[str, Callable] = {}

    @classmethod
    def register_creature(cls, entity_id: str):
        def decorator(factory: Callable):
            cls._creatures[entity_id] = factory
            return factory
        return decorator

    @classmethod
    def register_item(cls, entity_id: str):
        def decorator(factory: Callable):
            cls._items[entity_id] = factory
            return factory
        return decorator

    @classmethod
    def discover(cls, package_path: str):
        """Auto-import all modules in the given package directory."""
        for module_file in Path(package_path).glob("*.py"):
            if module_file.name.startswith("_"):
                continue
            importlib.import_module(
                f"nhc.entities.{package_path.name}.{module_file.stem}"
            )

    @classmethod
    def spawn_creature(cls, entity_id: str, world: World,
                       position: Position) -> EntityId:
        factory = cls._creatures[entity_id]
        components = factory()
        components["Position"] = position
        return world.create_entity(components)
```

**Adding a new creature** is a single-file operation:

```python
# nhc/entities/creatures/mimic.py
from nhc.entities.registry import EntityRegistry

@EntityRegistry.register_creature("mimic")
def create_mimic():
    return {
        "Stats": Stats(strength=4, dexterity=1, constitution=3,
                       intelligence=1, wisdom=2, charisma=0),
        "Health": Health(current=18, maximum=18),
        "Renderable": Renderable(glyph="M", color="brown", render_order=2),
        "AI": AI(behavior="ambush", morale=12, faction="dungeon"),
        "Disguise": Disguise(appears_as="chest", reveal_on="interact"),
        "Loot": LootTable(entries=[("gold", 1.0, "4d6"),
                                   ("magic_item", 0.2)]),
        "Description": Description(
            name="Mimic",
            short="what appears to be a treasure chest",
            long="Its surface glistens with an unnatural sheen. "
                 "The hinges don't quite look right."
        ),
    }
```

No other file needs modification — the registry discovers it automatically.

---

### 9. Rendering Architecture

#### 9.1 Renderer Protocol

```python
class Renderer(Protocol):
    def initialize(self) -> None: ...
    def shutdown(self) -> None: ...
    def render_world(self, world: World, camera: Camera) -> None: ...
    def render_ui(self, ui_state: UIState) -> None: ...
    def show_message(self, text: str, style: str = "normal") -> None: ...
    def get_input(self) -> InputEvent: ...
    def show_menu(self, title: str, options: list[str]) -> int: ...
    def show_inventory(self, inventory: Inventory) -> Action | None: ...
    def animate(self, animation: Animation) -> None: ...

class InputEvent:
    key: str
    modifiers: set[str]

class Camera:
    center: Position
    viewport_width: int
    viewport_height: int
```

#### 9.2 Terminal Renderer

The first renderer uses Python's `curses` (with `blessed` as a friendlier
wrapper) to draw the dungeon as ASCII art:

```
╔══════════════════════════════════════════════════╗
║  The Forgotten Crypt (Depth 1)     HP: 12/12    ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  ########          ########                      ║
║  #......#          #......#                      ║
║  #..@...+##########+...g..#                      ║
║  #......#          #....$.#                      ║
║  #.<....#          #...D..#                      ║
║  ########          ########                      ║
║                                                  ║
╠══════════════════════════════════════════════════╣
║ STR:3 DEX:4 CON:3 INT:2 WIS:3 CHA:1  Lv:1      ║
║ Armor:12  Slots: 7/13                            ║
╠══════════════════════════════════════════════════╣
║ > You enter a damp chamber. Water drips from     ║
║   the ceiling onto cracked flagstones.           ║
║ > A goblin snarls and raises its rusty blade!    ║
╚══════════════════════════════════════════════════╝
```

Glyph assignments follow Nethack conventions:

| Glyph | Entity |
|-------|--------|
| `@` | Player |
| `a-z` | Creatures (lowercase = weak) |
| `A-Z` | Creatures (uppercase = strong) |
| `$` | Gold |
| `!` | Potion |
| `?` | Scroll |
| `/` | Wand |
| `[` | Armor |
| `)` | Weapon |
| `+` | Door (closed) |
| `.` | Floor |
| `#` | Wall / corridor |
| `<` `>` | Stairs up/down |
| `^` | Trap (visible) |
| `~` | Water |

#### 9.3 Future Graphical Renderer

The `graphical/` package will implement the same `Renderer` protocol using
pygame or tcod. The `Renderable` component carries both `glyph` (ASCII) and
can be extended with `sprite: str` (asset path) without changing the core engine.
The renderer selection is a startup configuration choice.

---

### 10. LLM Narrative Integration

#### 10.1 Architecture

The narrative system sits as an observer on the event bus. It does not affect
game mechanics — it adds flavor, dialogue, and emergent story.

```
Game Events ──→ Narrative Engine ──→ Story Text ──→ Message Log
                     │
                     ├── Context Builder (summarizes game state)
                     ├── LLM Client (Claude API / local model)
                     └── Story State (continuity tracker)
```

#### 10.2 Context Builder

The context builder produces a structured summary of game state that fits
within an LLM context window. It maintains a sliding window of recent events
and a compressed summary of older history.

```python
class NarrativeContext:
    def build(self, world: World, events: list[Event]) -> dict:
        return {
            "player": {
                "name": world.player.name,
                "level": world.player.level,
                "health_pct": world.player.health_ratio,
                "notable_items": self.notable_items(world.player),
                "conditions": world.player.active_conditions,
            },
            "location": {
                "level_name": world.current_level.name,
                "room": self.describe_room(world.player_room),
                "depth": world.current_level.depth,
                "theme": world.current_level.metadata.theme,
                "ambient": world.current_level.metadata.ambient,
            },
            "recent_events": [
                self.summarize_event(e) for e in events[-20:]
            ],
            "story_so_far": self.story_state.compressed_summary,
            "nearby_creatures": [
                self.describe_creature(c) for c in world.visible_creatures
            ],
            "narrative_hooks": world.current_level.metadata.narrative_hooks,
            "story_threads": self.story_state.active_threads,
        }
```

#### 10.3 Narrative Triggers

Not every event needs LLM narration. The engine uses a priority/filter system:

| Trigger | Priority | Example output |
|---------|----------|----------------|
| Enter new level | High | Atmospheric description |
| Enter new room | Medium | Room description with details |
| Kill notable creature | High | Dramatic combat conclusion |
| Find rare item | Medium | Item lore / history |
| Near death | High | Tension building |
| NPC encounter | High | Dialogue generation |
| Routine combat | Low | Brief flavor (or skip) |
| Pick up mundane item | Skip | No narration |

High-priority events are sent to the LLM immediately (as a background
`asyncio.Task`) and the resulting text is displayed as soon as it arrives —
typically before the player's next input. Medium-priority events are batched.
Low-priority events are narrated only if there's a lull in action.

#### 10.4 Emergent Quests

The LLM can generate quest hooks based on game state:

```python
class QuestGenerator:
    def consider_quest(self, context: NarrativeContext) -> Quest | None:
        """Periodically evaluate whether to introduce a quest hook."""
        # Feed context to LLM with quest-generation prompt
        # LLM returns structured quest data or null
        ...

@dataclass
class Quest:
    title: str
    description: str
    objective: QuestObjective      # kill, fetch, explore, escort
    target: str                    # Entity or location ID
    reward_hint: str               # Narrative reward description
    status: QuestStatus
```

#### 10.5 MCP Server for External LLM Access

An MCP server exposes game state as tools, allowing an external Claude instance
(e.g., via Claude Code or Claude Desktop) to act as a narrative director:

```python
# Tool definitions for mcp_server.py

@mcp_tool("get_game_state")
def get_game_state() -> dict:
    """Get current game state: player, level, creatures, items."""

@mcp_tool("get_event_log")
def get_event_log(last_n: int = 20) -> list[dict]:
    """Get recent game events for narrative context."""

@mcp_tool("get_level_map")
def get_level_map(explored_only: bool = True) -> str:
    """Get ASCII representation of current level."""

@mcp_tool("get_player_inventory")
def get_player_inventory() -> list[dict]:
    """Get player's inventory with item descriptions."""

@mcp_tool("get_creature_info")
def get_creature_info(entity_id: str) -> dict:
    """Get detailed info about a visible creature."""

@mcp_tool("get_room_description")
def get_room_description(room_id: str) -> dict:
    """Get room metadata including tags and narrative hooks."""

@mcp_tool("narrate")
def narrate(text: str, style: str = "normal") -> None:
    """Push narrative text to the game's message log."""

@mcp_tool("create_quest")
def create_quest(title: str, description: str,
                 objective_type: str, target: str) -> str:
    """Create an emergent quest for the player."""

@mcp_tool("set_creature_dialogue")
def set_creature_dialogue(entity_id: str,
                          dialogue: list[str]) -> None:
    """Set dialogue lines for an NPC encounter."""

@mcp_tool("get_story_summary")
def get_story_summary() -> str:
    """Get compressed narrative summary of the adventure so far."""

@mcp_tool("add_narrative_hook")
def add_narrative_hook(hook: str, level_id: str | None = None) -> None:
    """Plant a narrative hook for future story development."""
```

This enables a powerful workflow: the player plays in the terminal, while a
Claude instance connected via MCP observes and enriches the experience in
real-time.

---

### 11. Game State Serialization

The full game state must be serializable for save/load and LLM consumption:

```python
@dataclass
class GameState:
    player: EntitySnapshot
    world: WorldSnapshot
    narrative: NarrativeSnapshot
    turn: int
    rng_state: bytes           # For deterministic replay

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> "GameState": ...

    def save(self, path: Path) -> None:
        """Save to YAML file."""

    @classmethod
    def load(cls, path: Path) -> "GameState":
        """Load from YAML file."""
```

The save format is YAML (human-readable, LLM-parseable). Binary data (RNG state)
is base64-encoded.

---

### 12. Field of View & Exploration

FOV uses **recursive shadowcasting** (8-octant) for efficient, symmetric
visibility calculation. This is the standard algorithm used by most modern
roguelikes.

```python
class FOV:
    @staticmethod
    def compute(origin: Position, radius: int,
                is_blocking: Callable[[int, int], bool]) -> set[Position]:
        """Return set of visible positions from origin."""
```

Tiles have two boolean flags:
- `visible`: currently in FOV (updated each turn)
- `explored`: ever been visible (persistent, used for map rendering)

The renderer shows:
- Visible tiles: full color with entities
- Explored but not visible: dimmed, no entities
- Unexplored: black

---

### 13. Dependencies

```
# Core
pyyaml          # Dungeon level serialization
blessed         # Terminal rendering (curses wrapper)
aiofiles        # Async file I/O (save/load, level loading)

# LLM integration
anthropic       # Claude API client (async client included)
mcp             # MCP server library (async stdio transport)

# Development
pytest          # Testing
pytest-asyncio  # Async test support
```

Minimal dependency footprint. The game should run with just `pyyaml` and
`blessed` if LLM features are disabled. `asyncio` is stdlib — no extra
dependency for the core async architecture.

---

### 14. Implementation Phases

**Phase 1 — Walking Skeleton**
- ECS foundation, game loop, turn processing
- Terminal renderer with basic ASCII dungeon
- Player movement, collision, FOV
- One static hand-authored level
- Basic message log

**Phase 2 — Knave Combat**
- Ability scores, attack rolls, damage
- Health, death
- 3-5 creature types with basic AI (seek & attack)
- Melee and ranged weapons
- Armor system

**Phase 3 — Dungeon Generation**
- Classic room-and-corridor generator
- Generation parameters
- Stairs / multi-level dungeon
- Populator (creature & item placement)

**Phase 4 — Items & Inventory**
- Inventory system (slot-based per Knave)
- Potions, weapons, armor, gold
- Item interaction: pick up, drop, equip, use
- Loot tables

**Phase 5 — Magic**
- Spell tomes as inventory items
- 10-15 spells (offensive, defensive, utility)
- Spell casting and slot consumption

**Phase 6 — LLM Narrative**
- Event bus → narrative engine pipeline
- Context builder
- Room/level descriptions from LLM
- NPC dialogue generation
- MCP server for external LLM access

**Phase 7 — Advanced Generation & Content**
- BSP and cellular automata generators
- Themed level generation (crypt, cave, castle)
- 20+ creature types, 30+ item types
- Traps, features (fountains, altars, etc.)
- Emergent quest system

**Phase 8 — Polish**
- Save/load system
- Character creation
- Death screen / score
- Key rebinding
- Graphical renderer prototype (pygame/tcod)
