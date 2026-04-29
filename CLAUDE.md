# NHC — Nethack-like Crawler

Roguelike dungeon crawler on Knave rules. ECS architecture,
BSP dungeon generation, LLM-driven typed gameplay, multilingual
(en/ca/es), terminal TUI + web frontend.

## Quick Reference

```bash
# Terminal game
./play --lang ca -G              # Generate dungeon, Catalan
./play --lang ca --god -G        # God mode (invulnerable)
./play --mode typed --lang ca -G # Typed mode with LLM GM
./play --seed 12345 -G           # Reproducible seed

# Web server
./server                         # Local dev, no auth
./server --auth                  # Generate token, require auth
./server --host 0.0.0.0 --auth  # Expose on network
./server --render-mode svg       # Serve SVG floors instead of PNG
                                 # (env: NHC_RENDER_MODE=svg)

# Tests (ALWAYS before committing)
.venv/bin/pytest -n auto --dist worksteal -m "not slow"
                                        # Default dev loop, ~24s
.venv/bin/pytest -n auto --dist worksteal
                                        # Full run incl. slow
                                        # subprocess tests, ~2.5 min
.venv/bin/pytest tests/unit/test_specific.py -v
.venv/bin/pytest -k "test_name"
.venv/bin/pytest -m core         # Markers: core, dungeon,
                                 # entities, rules, narrative,
                                 # slow
```

## Current Focus

**Web-only development.** Terminal TUI is paused. Do not
add or modify terminal-specific features. All new work
targets the web frontend.

## Development Rules

- **Strict TDD**: Write tests first. No functional change
  without a corresponding test.
- **Clean code**: Remove trailing whitespace before staging.
- **Entity IDs in English** — no Catalan/Spanish in code.
- **All code in English** — comments, variables, docstrings.
- **Translations in locale files** — never hardcode
  user-facing strings.
- **Type hints** — Python 3.14+ style.
- **pytest** as test framework, `pytest-asyncio` for async.

## Interaction Preferences

- Ask questions **one at a time**, not in batches.
- Give the user the opportunity to clarify before proceeding.

## Commit Style (GNOME/freedesktop Convention)

First line is `topic: short summary`, max 70 characters.
Followed by a blank line and a description paragraph wrapped
at 80 characters explaining what changed and why.

The topic can be a **component** (`web`, `dungeon`, `rules`,
`narrative`, `i18n`, `ai`, `rendering`, `deploy`) or a
**semantic type** (`fix`, `perf`, `refactor`, `test`, `docs`,
`chore`). Use whichever reads most naturally.

```
dungeon: add octagon room shape to BSP generator

Add OctagonShape to the room shape hierarchy. Clips corners
at 45 degrees using max(1, min(w,h)//3) as clip size.
```

```
fix: token extraction priority and copy button on HTTP
```

Rules:
- Use lowercase after the colon
- No period at the end of the first line
- Use imperative mood ("add" not "added")
- Body explains *what* and *why*, wrapped at 80 characters

## Key Patterns

### Entity Creation (factory + auto-registration)

```python
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
```

Catalan/Spanish entries include `gender: "m"` or `gender: "f"`.

### ANSI Color Safety

Pad text BEFORE applying color:
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

Potions (colors), scrolls (labels), rings (gems), wands (woods)
shuffled per game seed. Show appearance until identified by use.

## Test Coverage Gaps

- Ring passive effects (mending HP regen, detection auto-reveal)
- Ascend stairs action and floor state cleanup on transitions
- GM pipeline integration tests (context building + action plan)

## Reference

Architecture, stats, and directory structure are documented in
`design/design.md`. See also `design/` for dungeon generator,
web client, debug tools, magic items, and typed gameplay docs.
The player-facing view hierarchy (hex / flower / site /
structure / dungeon) is formalised in `design/views.md`; when
branching on "which view is the player in?" route through
`Game.current_view()` rather than re-deriving the answer.
The unified site subsystem (every flower feature → walled
surface site, dispatcher + cache shape) is in `design/sites.md`.
