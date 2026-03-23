# NHC — Nethack-like Crawler

## Project Overview

A roguelike dungeon crawler with Knave rules, multilingual support
(en/ca/es), LLM-driven typed gameplay mode, BSP dungeon generation,
and a complete BEB/Knave equipment catalog.

## Quick Reference

```bash
# Run the game
./play --lang ca -G              # Generate dungeon, Catalan
./play --lang ca --god -G        # God mode (invulnerable)
./play --mode typed --lang ca -G # Typed mode with LLM GM
./play --seed 12345 -G           # Reproducible seed

# Run tests (ALWAYS before committing)
.venv/bin/pytest
.venv/bin/pytest tests/unit/test_specific.py -v  # Single file
.venv/bin/pytest -k "test_name"                  # Pattern match

# Check item/creature counts
.venv/bin/python -c "
from nhc.entities.registry import EntityRegistry
EntityRegistry.discover_all()
print(f'Items: {len(EntityRegistry.list_items())}')
print(f'Creatures: {len(EntityRegistry.list_creatures())}')
"
```

## Development Discipline

### Test-Driven Development (TDD)

**This project follows strict TDD.** For every change:

1. **Write tests FIRST** — before implementing the feature or fix.
2. **Run tests** — confirm the new tests fail (red).
3. **Implement** — write the minimum code to pass.
4. **Run tests** — confirm all pass (green), including existing tests.
5. **Commit** — only commit when ALL tests pass.

### When to Write Tests

- **New features**: test the public API, edge cases, and error paths.
- **Bug fixes**: write a regression test that reproduces the bug FIRST,
  then fix the code.
- **Refactors**: ensure existing tests still pass; add tests for any
  new code paths.
- **New entities** (creatures, items): verify they register correctly
  and have i18n entries.
- **Dungeon generation**: test layout properties (connectivity,
  room spacing, corridor rules, wall rendering).
- **Actions**: test validate + execute with mock World/Level.
- **UI changes**: verify rendering doesn't crash (no ANSI alignment
  issues — pad text BEFORE applying color codes).

### Test Coverage Gaps (priority areas for new tests)

- Ring passive effects (mending HP regen, detection auto-reveal)
- Wand charge/recharge mechanics
- Equip/unequip all slot types (weapon, armor, shield, helmet, rings)
- Drop action (item returns to map)
- Throw action (potion effect on target)
- Zap action (wand charges decrement, effects apply)
- Potion/scroll/ring/wand identification (disguise on spawn,
  reveal on use, all-of-type update)
- Floor transitions (descend, ascend, floor cache preservation)
- Starting equipment (Knave rules, slot cost limits)
- Typed mode: GM pipeline, fallback parser
- God mode (HP restore, auto-identify)

## Architecture

```
nhc/
├── nhc.py                  # CLI entry point
├── nhc/
│   ├── core/
│   │   ├── game.py         # Game loop, state, floor management
│   │   ├── ecs.py          # Entity-Component-System
│   │   ├── events.py       # Event bus (pub/sub)
│   │   ├── actions.py      # All player/creature actions
│   │   ├── save.py         # JSON save/load (manual)
│   │   └── autosave.py     # Binary autosave (pickle+zlib)
│   ├── entities/
│   │   ├── components.py   # All ECS components (dataclasses)
│   │   ├── registry.py     # Auto-discovery entity registry
│   │   ├── creatures/      # 78 creature factories
│   │   ├── items/          # 155 item factories
│   │   └── features/       # Trap factories
│   ├── dungeon/
│   │   ├── generators/bsp.py  # BSP dungeon generator
│   │   ├── room_types.py   # Room specialization + painters
│   │   ├── terrain.py      # Cellular automata water/grass
│   │   ├── populator.py    # Entity placement (encounter groups)
│   │   ├── loader.py       # YAML level loader (multilingual)
│   │   └── model.py        # Level, Tile, Room data structures
│   ├── rendering/terminal/
│   │   ├── renderer.py     # 4-zone terminal renderer
│   │   ├── panels.py       # Status bar + message log
│   │   ├── glyphs.py       # Tile/color mappings (16/256 color)
│   │   ├── input.py        # Key → intent mapping
│   │   ├── input_line.py   # Text input widget (typed mode)
│   │   ├── narrative_log.py # Narrative log (typed mode)
│   │   └── help_overlay.py # Scrollable help popup
│   ├── narrative/
│   │   ├── gm.py           # LLM Game Master pipeline
│   │   ├── context.py      # Game state → LLM context
│   │   ├── parser.py       # JSON action plan parser
│   │   ├── prompts.py      # Multilingual prompt loader
│   │   ├── prompts/{lang}/ # 6 prompt files × 3 languages
│   │   ├── story.py        # Story compression
│   │   └── fallback_parser.py # Keyword parser (no LLM)
│   ├── rules/
│   │   ├── combat.py       # Attack rolls, damage, healing
│   │   ├── chargen.py      # Knave character generator
│   │   ├── identification.py # Potion/scroll/ring/wand ID system
│   │   ├── advancement.py  # XP and leveling
│   │   └── loot.py         # Loot table resolution
│   ├── ai/
│   │   └── behavior.py     # Creature AI (chase, attack, abilities)
│   ├── i18n/
│   │   ├── locales/{en,ca,es}.yaml  # Full translations
│   │   └── manager.py      # Translation lookup with fallback
│   ├── llm.py              # LLM backends (MLX, Ollama, Anthropic)
│   └── utils/
│       ├── rng.py          # Seeded RNG + dice roller
│       ├── fov.py          # Shadowcasting FOV
│       └── spatial.py      # Distance/adjacency helpers
├── levels/
│   └── test_level.yaml     # Hand-crafted test dungeon
├── design/                 # Design documents
├── docs/                   # Help files, BEB/Knave rules
└── tests/unit/             # 29 test files, 433+ tests
```

## Key Patterns

### Entity Creation (creature/item factory)

```python
# nhc/entities/creatures/goblin.py
from nhc.entities.components import AI, Health, Renderable, Stats
from nhc.entities.registry import EntityRegistry, creature_desc

@EntityRegistry.register_creature("goblin")
def create_goblin() -> dict:
    return {
        "Stats": Stats(strength=1, dexterity=2),
        "Health": Health(current=4, maximum=4),
        "Renderable": Renderable(glyph="g", color="green", render_order=2),
        "AI": AI(behavior="aggressive_melee", morale=7, faction="goblinoid"),
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

Catalan entries include `gender: "m"` or `gender: "f"`.

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

Potions (colors), scrolls (cryptic labels), rings (gems), wands (woods)
are shuffled per game seed. Items show appearance until identified by
use. `_potion_id` component tracks real identity.

## Coding Standards

- **Entity IDs in English** — no Catalan/Spanish in code identifiers
- **All code in English** — comments, variable names, docstrings
- **Translations in locale files** — never hardcode user-facing strings
- **No trailing whitespace** — clean source files
- **Type hints** — Python 3.10+ style
- **pytest** as test framework, `pytest-asyncio` for async tests
- **Conventional commits** — `feat:`, `fix:`, `refactor:`, `test:`, `docs:`

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

- **155 items** (34 scrolls, 9 potions, 8 rings, 8 wands, 96 equipment)
- **78 creatures** (complete BEB bestiary)
- **433+ tests** across 29 test files
- **3 languages** (English, Catalan, Spanish)
