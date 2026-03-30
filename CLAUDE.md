# NHC — Nethack-like Crawler

## Project Overview

A roguelike dungeon crawler built on Knave rules with an
Entity-Component-System architecture, BSP dungeon generation,
LLM-driven typed gameplay mode, multilingual support (en/ca/es),
and a web frontend for multi-session play.

## Quick Reference

```bash
# Terminal game
./play --lang ca -G              # Generate dungeon, Catalan
./play --lang ca --god -G        # God mode (invulnerable)
./play --mode typed --lang ca -G # Typed mode with LLM GM
./play --seed 12345 -G           # Reproducible seed
./play --help                    # All options

# Web server
./server                         # Local dev, no auth
./server --auth                  # Generate token, require auth
./server --host 0.0.0.0 --auth  # Expose on network

# Tests (ALWAYS before committing)
.venv/bin/pytest
.venv/bin/pytest tests/unit/test_specific.py -v
.venv/bin/pytest -k "test_name"
.venv/bin/pytest -m core         # By marker: core, dungeon,
                                 # entities, rules, narrative

# Entity counts
.venv/bin/python -c "
from nhc.entities.registry import EntityRegistry
EntityRegistry.discover_all()
print(f'Items: {len(EntityRegistry.list_items())}')
print(f'Creatures: {len(EntityRegistry.list_creatures())}')
"
```

## Architecture

```
nhc/
├── nhc.py                     # Terminal CLI entry point
├── nhc_web.py                 # Web server entry point
├── play / server              # Bash launchers (auto-venv)
├── nhc/
│   ├── config.py              # 3-tier config (defaults→~/.nhcrc→CLI)
│   ├── llm.py                 # LLM backends (Ollama, MLX, Anthropic)
│   ├── log_utils.py           # Debug logging with topic filters
│   ├── core/
│   │   ├── ecs.py             # Entity-Component-System store
│   │   ├── game.py            # Async game loop, floor management
│   │   ├── events.py          # Event bus (pub/sub)
│   │   ├── actions.py         # All player/creature actions
│   │   ├── save.py            # JSON manual save/load
│   │   └── autosave.py        # Binary autosave (pickle+zlib)
│   ├── entities/
│   │   ├── components.py      # ECS components (dataclasses)
│   │   ├── registry.py        # Auto-discovery entity registry
│   │   ├── creatures/         # 78 creature factories
│   │   ├── items/             # 193 item factories
│   │   └── features/          # 13 trap factories
│   ├── dungeon/
│   │   ├── generators/bsp.py  # BSP dungeon generator
│   │   ├── room_types.py      # Room specialization + painters
│   │   ├── terrain.py         # Cellular automata water/grass
│   │   ├── populator.py       # Entity placement (encounter groups)
│   │   ├── loader.py          # YAML level loader (multilingual)
│   │   └── model.py           # Level, Tile, Room data structures
│   ├── rendering/
│   │   ├── base.py            # Abstract renderer protocol
│   │   ├── client.py          # Client abstraction
│   │   ├── svg.py             # Static SVG export
│   │   ├── web_client.py      # WebSocket JSON renderer
│   │   └── terminal/
│   │       ├── renderer.py    # 4-zone terminal TUI (blessed)
│   │       ├── panels.py      # Status bar + message log
│   │       ├── glyphs.py      # Tile/color mappings (16/256)
│   │       ├── themes.py      # Color theme definitions
│   │       ├── input.py       # Key → intent mapping
│   │       ├── input_line.py  # Text input widget (typed mode)
│   │       ├── narrative_log.py # Narrative log (typed mode)
│   │       └── help_overlay.py  # Scrollable help popup
│   ├── narrative/
│   │   ├── gm.py              # LLM Game Master pipeline
│   │   ├── context.py         # Game state → LLM context
│   │   ├── parser.py          # JSON action plan parser
│   │   ├── fallback_parser.py # Keyword parser (no LLM)
│   │   ├── narrator.py        # Outcome narration
│   │   ├── dialogue.py        # NPC dialogue system
│   │   ├── quests.py          # Quest tracking
│   │   ├── story.py           # Story compression
│   │   ├── mcp_server.py      # MCP tool server
│   │   ├── prompts.py         # Multilingual prompt loader
│   │   └── prompts/{en,ca,es}/ # Prompt templates per language
│   ├── rules/
│   │   ├── combat.py          # Attack rolls, damage, healing
│   │   ├── chargen.py         # Knave character generation
│   │   ├── identification.py  # Potion/scroll/ring/wand ID
│   │   ├── advancement.py     # XP and leveling
│   │   ├── loot.py            # Loot table resolution
│   │   ├── conditions.py      # Status effects
│   │   ├── abilities.py       # Special abilities
│   │   └── magic.py           # Magic system rules
│   ├── ai/
│   │   └── behavior.py        # Creature AI (chase, attack, flee)
│   ├── web/
│   │   ├── app.py             # Flask application factory
│   │   ├── ws.py              # WebSocket handler
│   │   ├── auth.py            # Token-based authentication
│   │   ├── sessions.py        # Multi-session manager (max 8)
│   │   └── config.py          # Web-specific configuration
│   ├── i18n/
│   │   ├── manager.py         # Translation lookup + fallback
│   │   └── locales/{en,ca,es}.yaml  # ~2000 lines each
│   └── utils/
│       ├── rng.py             # Seeded RNG + dice roller
│       ├── fov.py             # Shadowcasting FOV
│       └── spatial.py         # Distance/adjacency helpers
├── levels/                    # Hand-crafted YAML dungeons
├── design/                    # Design documents
├── docs/                      # Help files, Knave rules, BEB bestiary
└── tests/unit/                # 53 test files, 780 tests
```

## Implemented Systems

### Core Engine
- **ECS**: Dataclass components, World store, entity queries
- **Async game loop**: Turn-based with event pub/sub
- **Save/load**: JSON manual + binary autosave (pickle+zlib)
- **Config**: 3-tier hierarchy (defaults → `~/.nhcrc` → CLI args)

### Content
- **78 creatures** — full BEB bestiary with AI behaviors, factions,
  morale, loot tables
- **193 items** — 38 scrolls, 14 potions, 14 wands, 8 rings,
  119 equipment (weapons, armor, shields, helmets, tools, treasure)
- **13 trap types** — pit, fire, poison, paralysis, teleport, alarm,
  arrow, darts, falling stone, spores, gripping, summoning, percussion
- **Identification system** — potions (colors), scrolls (cryptic labels),
  rings (gems), wands (woods) shuffled per seed, revealed on use

### Dungeon Generation
- **BSP generator** with configurable room sizes and spacing
- **Room specialization** — treasure, guard, shrine rooms with painters
- **Cellular automata** terrain (water, grass)
- **Corridors** — main path + extra loops, box-drawing walls
- **YAML loader** for hand-authored levels

### Combat & Rules
- **Knave ruleset** — d20 attack vs armor defense, dice pool damage
- **Character generation** with starting equipment (slot cost limits)
- **XP advancement** with level-up
- **Status effects** — paralysis, poison, confusion, stun, regeneration
- **Morale system** — creatures flee at low HP

### Rendering
- **Terminal TUI** (blessed) — 4-zone layout, shadowcasting FOV,
  16/256 color, box-drawing walls
- **Web client** — HTML5 Canvas + WebSocket, point-and-click,
  inventory panel, action toolbar
- **SVG export** — static map rendering

### Narrative & LLM
- **Game Master pipeline** — player types intent → LLM interprets →
  actions execute → LLM narrates outcome
- **LLM backends** — Ollama, MLX (Apple Silicon), Anthropic, None
- **Fallback parser** — keyword-based when LLM unavailable
- **Story compression** — summarizes history for context window
- **Multilingual prompts** — 3 languages × prompt templates
- **MCP server** — tool integration for narrative

### Web Server
- **Flask + WebSocket** — multi-session (up to 8 concurrent)
- **Token auth** — optional SHA256-hashed token
- **Session manager** — independent game instances

### Internationalization
- **3 languages** — English, Catalan, Spanish (~2000 lines each)
- **Dotted key lookup** — `t("creature.goblin.name")`
- **Fallback chain** — current lang → English → key itself
- **Gender support** — grammatical gender for Catalan/Spanish

## Key Patterns

### Entity Creation (factory + auto-registration)

```python
# nhc/entities/creatures/goblin.py
from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc

@EntityRegistry.register_creature("goblin")
def create_goblin() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=2),
        "Health": Health(current=4, maximum=4),
        "Renderable": Renderable(glyph="g", color="green",
                                 render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7,
                 faction="goblinoid"),
        "Description": creature_desc("goblin"),
    }
```

### i18n — Always add entries to ALL 3 locale files

```yaml
# en.yaml, ca.yaml, es.yaml — MUST stay in sync
creature:
  goblin:
    name: "Goblin"
    short: "a snarling goblin"
    long: >-
      A wiry, green-skinned creature...
```

Catalan/Spanish entries include `gender: "m"` or `gender: "f"`.

### ANSI Color Safety

When rendering UI boxes, **pad text BEFORE applying color**:
```python
# WRONG — ANSI codes mess up width
line = term.bold(text).ljust(width)

# RIGHT — pad plain text, then color
padded = text[:width].ljust(width)
line = term.bold(padded)
```

### Wall Rendering

Walls use box-drawing (`┌─┐│└┘├┤┬┴┼`). Key rules:
- VOID tiles don't connect (clean room borders)
- Doors count as wall connections for box-drawing
- `door_open` must be included in connection checks
- Corridors have VOID on their sides (no wall leaks)

### Identification System

Potions (colors), scrolls (cryptic labels), rings (gems),
wands (woods) are shuffled per game seed. Items show appearance
until identified by use. `_potion_id` component tracks real
identity.

## Coding Standards

- **Entity IDs in English** — no Catalan/Spanish in code
- **All code in English** — comments, variables, docstrings
- **Translations in locale files** — never hardcode user-facing
  strings
- **No trailing whitespace** — clean source files
- **Type hints** — Python 3.10+ style
- **pytest** as test framework, `pytest-asyncio` for async

### Commit Style (GStreamer Convention)

```
topic: short summary (max 70 chars total)

Description of the changes, wrapped at 80 characters. Explain
what changed and why.
```

## Test Coverage Gaps (priority areas)

- Ring passive effects (mending HP regen, detection auto-reveal)
- Ascend stairs action and floor state cleanup on transitions
- GM pipeline integration tests (context building + action plan)

## Keyboard Shortcuts

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| Arrows/hjkl | Move | g/, | Pickup |
| a | Use item | q | Quaff potion |
| e | Equip/unequip | d | Drop item |
| t | Throw potion | z | Zap wand |
| s | Search secrets | x | Look around |
| > | Descend stairs | < | Ascend stairs |
| i | Inventory | ? | Help |
| S | Save | L | Load |
| TAB | Toggle mode | Q | Quit |

## Current Stats

- **193 items** (38 scrolls, 14 potions, 14 wands, 8 rings,
  119 equipment)
- **78 creatures** (complete BEB bestiary)
- **780 tests** across 53 test files
- **3 languages** (English, Catalan, Spanish)
- **13 trap types**
