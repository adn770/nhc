# Typed Gameplay Mode — Design Document

> **Status**: Implemented. All 5 phases complete. GM pipeline,
> context builder, multilingual prompts (3 langs x 6 files),
> fallback parser, story compression, input widget, and
> narrative log are all functional.

## 1. Vision

A hybrid gameplay mode where the player types natural language intents
instead of pressing roguelike keys. A local LLM (gemma3:27b) acts as
**Game Master**: it interprets the player's typed intent, resolves it
against the game's mechanical state, narrates the outcome, and drives
an emergent story that weaves together dungeon exploration, combat, and
TTRPG-style role-playing.

The result is a game that feels like a solo TTRPG session — the player
describes what they want to do ("I search the corpse for anything
useful", "I try to sneak past the skeletons", "I cast the fireball
scroll at the group"), and the GM responds with mechanical resolution
*and* narrative flavor, all grounded in the Knave ruleset and the
actual ECS world state.

```
┌─────────────────────────────────────────────────────────┐
│                    DUNGEON MAP                          │
│  (same as classic mode — FOV, entities, 256-color)      │
├─────────────────────────────────────────────────────────┤
│  📍 El Celler Enfonsat │ ⬇ 1 │ ⏳ 12 │ Lv 1 │ 💰 18   │
│  Arnau Ferrer (mercenari) │ FOR:+2 DES:+3 ...          │
│  🎒 3/12  Espasa · Poció de Curació · Pergamí de Dormir │
├─────────────────────────────────────────────────────────┤
│  GM: The skeleton's bones clatter as it swings its      │
│  notched blade. You parry — sparks fly off the stone    │
│  walls. It staggers back, ribs cracked. 4 damage.       │
│                                                         │
│  GM: The goblin behind it shrieks and flees south.      │
├─────────────────────────────────────────────────────────┤
│> I loot the skeleton and check for traps ahead_         │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Design Principles

- **Mechanics are sovereign.** The LLM narrates; the ECS resolves.
  The LLM never bypasses game rules. It interprets intents into
  mechanical actions, then narrates the outcome of those actions.
- **Grounded generation.** Every LLM call receives the full relevant
  game state as structured context. The GM cannot hallucinate rooms,
  creatures, or items that don't exist in the world.
- **Local-first.** Uses gemma3:27b running locally — MLX on macOS
  (auto-download, cached), Ollama on Linux/others. No cloud dependency
  for gameplay.
- **Fully multilingual.** All LLM prompts (system, interpret, narrate,
  compress) are written natively in each supported language — not
  translated at runtime. The GM thinks, reasons, and narrates in the
  player's language. Prompt files live alongside the i18n locale
  system and are selected by the active `--lang` flag.
- **Graceful fallback.** If the LLM is slow or unavailable, the game
  remains playable — typed commands are parsed as best-effort
  mechanical intents without narrative.

---

## 3. UI Layout

The terminal layout gains a fourth zone: a text input area at the
bottom where the player types their intent.

```
Zone 1: MAP (unchanged — full width, FOV-centered)
──────────────────────────────────────────────────
Zone 2: STATUS (3 lines — identity, stats, inventory)
──────────────────────────────────────────────────
Zone 3: NARRATIVE LOG (replaces message log, 6+ lines)
  - GM narration displayed here with streaming output
  - Mechanical outcomes interleaved ("→ 4 damage to Skeleton")
  - Scrollable with [ ] keys
──────────────────────────────────────────────────
Zone 4: INPUT (1-2 lines)
  > player types here, Enter to submit, ESC to cancel
```

### 3.1 Zone 3 — Narrative Log

The classic 4-line message log expands to a larger narrative area
(6–10 lines depending on terminal height). Two message types:

- **Narrative** (from LLM): Streamed word-by-word as the model
  generates. Shown in default color. Prefixed with nothing or a
  subtle marker.
- **Mechanical** (from ECS events): Shown in `bright_black` or
  bracketed. E.g., `[→ Skeleton: 4 damage, slain]`,
  `[→ Picked up Healing Potion]`.

### 3.2 Zone 4 — Text Input

A single-line input field with:
- Prompt character `> ` in bright_yellow.
- Standard line editing (backspace, left/right cursor, home/end).
- **Enter** submits the intent to the GM pipeline.
- **ESC** clears the input (or switches to classic key mode if
  we support hybrid).
- **Up/Down arrows** scroll through input history (last 20).
- The input is non-blocking: while the player types, the map and
  status bar remain visible and responsive.

### 3.3 Hybrid Mode Toggle

- `--mode typed` enables typed gameplay (default when LLM is available).
- `--mode classic` forces roguelike key mode (current behavior).
- In typed mode, single-key shortcuts still work for movement
  (arrow keys, hjkl) — only non-movement actions go through the
  text input.

---

## 4. LLM Provider Strategy

### 4.1 macOS (Apple Silicon) — MLX Default

On macOS with Apple Silicon, use `mlx-lm` to run gemma3:27b
natively on the GPU. The model is downloaded automatically on first
run and cached in `~/.cache/nhc/models/`.

```
Default model: mlx-community/gemma-3-27b-it-4bit
Cache dir:     ~/.cache/nhc/models/
```

**Auto-download flow:**
1. Check if model exists in cache dir.
2. If missing, print "Downloading gemma3:27b (first run)..." and
   download via `huggingface_hub.snapshot_download()`.
3. Load model with `mlx_lm.load()`.

### 4.2 Non-macOS — Ollama Default

On Linux/Windows, default to Ollama with `gemma3:27b`.

```
Default model: gemma3:27b
Endpoint:      http://localhost:11434
```

The game checks if Ollama is running and the model is available.
If not, it prints instructions to install/pull the model.

### 4.3 CLI Override

```
--provider {mlx,ollama,anthropic,none}
--model MODEL_NAME_OR_PATH
--mode {typed,classic}
```

On macOS, `--provider ollama` forces Ollama even on Apple Silicon.
On any platform, `--provider none --mode typed` enables typed mode
with a simple keyword parser (no LLM narration).

### 4.4 Configuration Precedence

```
CLI flags  >  ~/.nhcrc  >  platform auto-detect
```

```ini
# ~/.nhcrc
[nhc]
provider = mlx
model = mlx-community/gemma-3-27b-it-4bit
mode = typed
lang = ca
```

---

## 5. GM Pipeline — Intent → Action → Narration

The core loop for typed mode replaces the single-keypress input with
a three-phase pipeline:

```
Player types intent
       │
       ▼
┌──────────────┐     ┌──────────────────┐
│  1. INTERPRET │────▶│  2. RESOLVE      │
│  (LLM call)  │     │  (ECS actions)   │
└──────────────┘     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  3. NARRATE      │
                     │  (LLM call)      │
                     └──────────────────┘
                              │
                              ▼
                     Narrative log + map update
```

### 5.1 Phase 1 — Interpret

The LLM receives the player's typed text plus structured game state
and returns a **JSON action plan**: a list of mechanical actions to
execute.

The system prompt is loaded from the active language's prompt file
(see **Section 14** for full prompts in all languages). The prompt
is written natively in each language so the LLM can understand
player intents expressed in that language. The action schema
(JSON keys, action names) stays in English across all languages
for reliable parsing.

**Prompt loaded from:** `nhc/narrative/prompts/{lang}/interpret.txt`

**User message includes:**
```json
{
  "player_intent": "I search the corpse and check for traps",
  "game_state": {
    "player": {
      "name": "Arnau Ferrer",
      "hp": "8/12",
      "stats": {"str": 2, "dex": 3, "con": 2, ...},
      "inventory": ["Sword", "Healing Potion"],
      "position": [24, 4],
      "conditions": []
    },
    "current_room": {
      "id": "guard_room",
      "description": "An old guard post...",
      "tags": ["combat"]
    },
    "visible_entities": [
      {"id": 42, "type": "item", "name": "goblin corpse", "pos": [24, 4]},
      {"id": 15, "type": "creature", "name": "Skeleton", "pos": [26, 5]}
    ],
    "recent_events": [
      "Killed goblin (turn 11)",
      "Goblin dropped: 10 Gold, Dagger (turn 11)"
    ],
    "narrative_hooks": ["Claw marks on the walls..."],
    "level": {"name": "The Sunken Cellar", "depth": 1, "theme": "crypt"}
  }
}
```

**LLM returns:**
```json
[
  {"action": "pickup", "item": 42},
  {"action": "custom", "description": "check for traps ahead",
   "check": {"ability": "wisdom", "dc": 12}}
]
```

### 5.2 Phase 2 — Resolve

The action plan is validated and executed against the ECS, exactly
like classic mode actions:

1. Parse JSON action list from LLM response.
2. For each action, create the corresponding `Action` object
   (MoveAction, MeleeAttackAction, PickupItemAction, etc.).
3. Validate and execute via the existing action pipeline.
4. Collect all resulting `Event` objects.
5. For `"custom"` actions, resolve as ability checks:
   - Roll d20 + ability bonus vs DC.
   - Success/failure becomes an event the narrator can describe.

**Custom action resolution:**
```python
@dataclass
class CustomActionEvent(Event):
    """Result of a TTRPG-style freeform action."""
    description: str = ""
    ability: str = ""
    roll: int = 0
    bonus: int = 0
    dc: int = 12
    success: bool = False
```

### 5.3 Phase 3 — Narrate

A second LLM call takes the mechanical outcomes and produces prose.
The narration prompt is loaded from the active language's prompt file,
written entirely in that language so the LLM generates natural prose
without translation artifacts.

**Prompt loaded from:** `nhc/narrative/prompts/{lang}/narrate.txt`

The prompt instructs the GM to:
- Write in second person ("You search...", "Escorcolles...", "Registras...")
- Mix action and atmosphere; not every sentence needs drama.
- Reference the dungeon theme and ambient when relevant.
- Keep mechanical numbers in brackets: [4 damage], [WIS 15 vs DC 12].
- Give dramatic moments more weight (near death, rare find, boss kill).
- End by setting up the player's next decision.

**User message includes:**
```json
{
  "intent": "I search the corpse and check for traps",
  "outcomes": [
    {"action": "pickup", "result": "Picked up goblin corpse"},
    {"action": "custom", "description": "check for traps ahead",
     "ability": "wisdom", "roll": 15, "bonus": 1, "dc": 12,
     "success": true}
  ],
  "story_so_far": "Arnau descended into the crypt...",
  "ambient": "Damp air clings to the stone..."
}
```

**LLM returns** (streamed to narrative log):
```
You rifle through the goblin's remains — nothing but a broken
fang necklace and the stench of decay. Straightening up, your
trained eye catches a faint irregularity in the flagstones ahead.
[WIS 16 vs DC 12 — trap spotted!] A concealed pit, poorly
disguised. The claw marks on the walls suddenly make more sense.
```

---

## 6. Context Management

### 6.1 Sliding Context Window

The GM maintains a rolling context that fits within gemma3:27b's
context window (8192 tokens for the 4-bit quantized version):

| Section | Token budget | Contents |
|---------|-------------|----------|
| System prompt | ~400 | GM instructions, style, language |
| Character sheet | ~100 | Name, stats, traits, conditions |
| Story summary | ~500 | Compressed adventure history |
| Current state | ~300 | Room, visible entities, inventory |
| Recent events | ~200 | Last 5 turns of outcomes |
| Player intent | ~50 | Current typed input |
| **Total** | **~1550** | Leaves ~6600 for generation |

### 6.2 Story Summary Compression

Every 10 turns, the story summary is recompressed by asking the
LLM to condense the last 10 turns of narrative into 2-3 sentences.
This prevents context overflow while preserving narrative continuity.

**Prompt loaded from:** `nhc/narrative/prompts/{lang}/compress.txt`

The prompt asks the LLM to condense the narrative in the same
language it was written in, preserving key events and character
development.

### 6.3 Event → Context Mapping

Game events are converted to concise context strings:

| Event | Context string |
|-------|---------------|
| CreatureAttacked | "Player hit Skeleton for 4 damage (turn 5)" |
| CreatureDied | "Skeleton slain by player (turn 6)" |
| ItemPickedUp | "Picked up Healing Potion (turn 7)" |
| ItemUsed | "Used Scroll of Sleep — 2 creatures fell asleep" |
| LevelEntered | "Descended to depth 2: The Forgotten Vault" |
| CustomActionEvent | "WIS check 15 vs DC 12: success — spotted trap" |

---

## 7. Turn Flow — Detailed Sequence

```
1. Display map + status (rendered from ECS state)
2. Display narrative log (scrollable)
3. Show input prompt "> "
4. Player types intent and presses Enter
5. Show "thinking..." indicator
6. [LLM CALL 1] Interpret intent → JSON action plan
7. Parse and validate action plan
8. Execute actions via ECS pipeline → collect Events
9. Update map, FOV, status
10. [LLM CALL 2] Narrate outcomes → stream to narrative log
11. Process creature AI turns → collect Events
12. [Optional LLM CALL 3] Narrate creature actions (brief)
13. Check win/death conditions
14. Loop to step 1
```

**Performance note:** Steps 6 and 10 are the bottlenecks. On Apple
Silicon with MLX, gemma3:27b-4bit generates ~30-50 tokens/second.
The interpret call (JSON, ~100 tokens) takes ~2-3s. The narrate call
(~150 tokens) takes ~3-5s. Total turn time: ~5-8 seconds, acceptable
for a TTRPG-style experience.

For faster feedback, the interpret and narrate calls can be pipelined:
start narrating as soon as the first action resolves, while later
actions are still executing.

---

## 8. Creature AI Narration

In typed mode, creature actions are also narrated (briefly). After
the player's turn resolves and creatures act:

```
[Turn 12 — Creature phase]
The remaining skeleton lurches forward, swinging its rusty blade.
[→ Skeleton attacks: miss!] Its blow glances off the stone beside
you. From the cistern below, you hear splashing.
```

This uses a lightweight LLM call with the creature action outcomes:
```json
{
  "creature_actions": [
    {"creature": "Skeleton", "action": "attack", "target": "player",
     "result": "miss"}
  ]
}
```

If multiple creatures act, their actions are batched into a single
narration call to minimize latency.

---

## 9. Special Interactions

### 9.1 NPC Dialogue

When the player talks to an NPC (e.g., the merchant), the GM
enters a dialogue sub-mode:

```
> I approach the merchant and ask about the claw marks

GM: The merchant eyes you warily over his heavy pack. "Those
marks? Made by something that came up from below. Three days ago.
Whatever it was, it killed two adventurers and dragged them down.
I only survived because I hid behind my wares." He spits.
"Looking to go down there? I've got a few things that might help.
For a price."

> What do you have for sale?
```

The NPC personality is derived from the creature's components (AI
faction, Description) and the player's CHA bonus affects disposition.

### 9.2 Creative Actions

The `"custom"` action type enables freeform TTRPG play:

- "I try to bluff the goblin into thinking I'm a wizard" → CHA check
- "I listen at the door before opening it" → WIS check
- "I try to break the rusty chain" → STR check
- "I examine the glowing sigil on the floor" → INT check

The LLM chooses the appropriate ability and DC based on the
action's nature and difficulty. The ECS resolves the roll. The
narrator describes the outcome.

### 9.3 Impossible Actions

If the player requests something impossible:

```
> I fly over the pit trap

GM: You lack the means to fly. Perhaps a Scroll of Levitate
would help? For now, the pit yawns before you — you'll need to
find another way around, or test your luck jumping.
```

The LLM returns `{"action": "impossible", "reason": "..."}` and
the narrator explains why, possibly suggesting alternatives.

---

## 10. Model Configuration

### 10.1 Recommended Models

| Provider | Model | Quantization | VRAM | Speed |
|----------|-------|-------------|------|-------|
| MLX (macOS) | gemma-3-27b-it | 4-bit | ~16GB | ~40 tok/s |
| Ollama | gemma3:27b | Q4_K_M | ~16GB | ~30 tok/s |
| Ollama (light) | gemma3:12b | Q4_K_M | ~8GB | ~50 tok/s |
| Anthropic | claude-haiku-4-5 | — | cloud | ~100 tok/s |

### 10.2 Auto-Detection Logic

```python
def auto_detect_provider() -> tuple[str, str]:
    """Return (provider, model) based on platform."""
    import platform
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return ("mlx", "mlx-community/gemma-3-27b-it-4bit")
    return ("ollama", "gemma3:27b")
```

### 10.3 MLX Model Cache

```
~/.cache/nhc/models/
└── mlx-community/
    └── gemma-3-27b-it-4bit/
        ├── config.json
        ├── model.safetensors
        ├── tokenizer.json
        └── ...
```

Download via `huggingface_hub`:
```python
from huggingface_hub import snapshot_download

snapshot_download(
    "mlx-community/gemma-3-27b-it-4bit",
    local_dir="~/.cache/nhc/models/mlx-community/gemma-3-27b-it-4bit",
)
```

---

## 11. Implementation Plan

All phases are complete.

### Phase 1 — Infrastructure (done)

1. `--mode {typed,classic}` CLI flag + config key
2. Zone 4 text input widget with line editing and history
   (`nhc/rendering/terminal/input_line.py`)
3. 4-zone terminal layout in renderer
4. NarrativeLog with narrative vs mechanical message types
   (`nhc/rendering/terminal/narrative_log.py`)

### Phase 2 — GM Pipeline Core (done)

5. GameMaster class in `nhc/narrative/gm.py`
6. ContextBuilder in `nhc/narrative/context.py`
7. Prompt files: 3 languages x 6 prompts each (interpret, narrate,
   compress, intro, creature_phase, follow_up)
8. `load_prompt()` with language fallback in `nhc/narrative/prompts.py`
9. Interpret prompt + JSON parsing in `nhc/narrative/parser.py`
10. Narrate prompt with streaming output
11. GameMaster wired into game loop

### Phase 3 — Model Management (done)

12. `auto_detect_provider()` platform logic in `nhc/llm.py`
13. MLX model auto-download with progress display
14. Ollama health check + model availability check
15. `create_backend()` with typed-mode defaults

### Phase 4 — Custom Actions & Dialogue (done)

16. CustomActionEvent and ability check resolution
17. NPC dialogue system (`nhc/narrative/dialogue.py`)
18. Story summary compression (`nhc/narrative/story.py`)
19. Creature AI narration batching

### Phase 5 — Polish (done)

20. Input history persistence (~/.cache/nhc/input_history.json)
21. Streaming narration (word-by-word display)
22. Fallback keyword parser (`nhc/narrative/fallback_parser.py`)

### Remaining test gaps

- GM pipeline integration tests (context building + action plan)
- Prompt loading tests across all 3 languages

---

## 12. Key Files

| File | Purpose |
|------|---------|
| `nhc/narrative/gm.py` | GameMaster: orchestrates the GM pipeline |
| `nhc/narrative/context.py` | ContextBuilder: game state → LLM context |
| `nhc/narrative/prompts.py` | `load_prompt()` loader with lang fallback |
| `nhc/narrative/prompts/en/*.txt` | English prompt files (6 files) |
| `nhc/narrative/prompts/ca/*.txt` | Catalan prompt files (6 files) |
| `nhc/narrative/prompts/es/*.txt` | Spanish prompt files (6 files) |
| `nhc/narrative/parser.py` | JSON action plan parser + validator |
| `nhc/narrative/story.py` | Story state: summary, threads, compression |
| `nhc/rendering/terminal/input_line.py` | Text input widget |
| `nhc/rendering/terminal/narrative_log.py` | Narrative log display |
| `nhc/utils/llm.py` | Extended with auto-detect + MLX cache logic |
| `nhc/core/game.py` | Typed-mode game loop branch |
| `nhc/core/actions.py` | CustomAction for freeform ability checks |
| `nhc/core/events.py` | CustomActionEvent dataclass |

---

## 13. Multilingual Prompt Architecture

### 13.1 Prompt File Layout

All LLM prompts live as plain text files organized by language.
Each prompt is written **natively** in its target language — not
machine-translated. This ensures the LLM receives natural,
idiomatic instructions and produces equally natural output.

```
nhc/narrative/prompts/
├── en/
│   ├── interpret.txt      # Intent → JSON action plan
│   ├── narrate.txt        # Outcomes → prose narrative
│   ├── compress.txt       # Story summary compression
│   ├── intro.txt          # Opening scene narration
│   ├── creature_phase.txt # Creature AI action narration
│   └── follow_up.txt      # Follow-up context prompts
├── ca/
│   ├── interpret.txt
│   ├── narrate.txt
│   ├── compress.txt
│   ├── intro.txt
│   ├── creature_phase.txt
│   └── follow_up.txt
└── es/
    ├── interpret.txt
    ├── narrate.txt
    ├── compress.txt
    ├── intro.txt
    ├── creature_phase.txt
    └── follow_up.txt
```

### 13.2 Loading Mechanism

```python
# nhc/narrative/prompts.py

from pathlib import Path
from nhc.i18n import current_lang

_PROMPT_DIR = Path(__file__).parent / "prompts"

def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt file for the active language.

    Falls back to English if the file doesn't exist for the
    active language.  Interpolates {placeholders} from kwargs.
    """
    lang = current_lang()
    path = _PROMPT_DIR / lang / f"{name}.txt"
    if not path.exists():
        path = _PROMPT_DIR / "en" / f"{name}.txt"
    text = path.read_text()
    if kwargs:
        text = text.format(**kwargs)
    return text
```

### 13.3 Design Principles for Prompts

- **JSON keys stay English.** Action names (`move`, `attack`,
  `pickup`), JSON field names, and entity IDs are always English
  regardless of the active language. This makes parsing reliable.
- **Instructions in the player's language.** The prose around
  the schema, the rules, the style guide — all written natively.
- **No runtime translation.** The prompt is never passed through
  `t()` or any translation layer. It's authored by a human in each
  language and loaded as-is.
- **Cultural tone.** Each language can have its own narrative voice:
  English prompts might be terse and Anglo-Saxon; Catalan prompts
  can lean into Mediterranean flair; Spanish can be more formal.

### 13.4 Prompt: Interpret (English)

```
You are the Game Master for a Knave roguelike dungeon crawler.
The player types what they want to do in natural language. Your
job is to interpret their intent and return a JSON action plan
grounded in the current game state.

Return ONLY a valid JSON array. Do not narrate or explain.

Available actions:
  {{"action": "move", "direction": "north|south|east|west|ne|nw|se|sw"}}
  {{"action": "attack", "target": <entity_id>}}
  {{"action": "pickup", "item": <entity_id>}}
  {{"action": "use_item", "item": <entity_id>, "target": <entity_id>|"self"}}
  {{"action": "wait"}}
  {{"action": "look", "target": <entity_id>|"room"|"around"}}
  {{"action": "talk", "target": <entity_id>}}
  {{"action": "search", "target": "room"|"corpse"|<entity_id>}}
  {{"action": "descend"}}
  {{"action": "open_door", "direction": "north|south|east|west"}}
  {{"action": "custom", "description": "...",
   "check": {{"ability": "strength|dexterity|constitution|intelligence|wisdom|charisma", "dc": <int>}}}}
  {{"action": "impossible", "reason": "..."}}

Rules:
- You may return up to 3 actions for complex intents.
- Actions must reference entities/items visible in the game state.
- If the intent is impossible given the current state, return a
  single "impossible" action explaining why.
- Use "custom" for creative TTRPG actions (bluffing, searching,
  intimidating, etc.) and choose the appropriate ability and DC.
```

### 13.5 Prompt: Interpret (Catalan)

```
Ets el Director de Joc d'un dungeon crawler roguelike basat en
Knave. El jugador escriu el que vol fer en llenguatge natural.
La teva feina és interpretar la seva intenció i retornar un pla
d'accions en format JSON fonamentat en l'estat actual del joc.

Retorna NOMÉS un array JSON vàlid. No narris ni expliquis res.

Accions disponibles:
  {{"action": "move", "direction": "north|south|east|west|ne|nw|se|sw"}}
  {{"action": "attack", "target": <entity_id>}}
  {{"action": "pickup", "item": <entity_id>}}
  {{"action": "use_item", "item": <entity_id>, "target": <entity_id>|"self"}}
  {{"action": "wait"}}
  {{"action": "look", "target": <entity_id>|"room"|"around"}}
  {{"action": "talk", "target": <entity_id>}}
  {{"action": "search", "target": "room"|"corpse"|<entity_id>}}
  {{"action": "descend"}}
  {{"action": "open_door", "direction": "north|south|east|west"}}
  {{"action": "custom", "description": "...",
   "check": {{"ability": "strength|dexterity|constitution|intelligence|wisdom|charisma", "dc": <int>}}}}
  {{"action": "impossible", "reason": "..."}}

Regles:
- Pots retornar fins a 3 accions per intencions complexes.
- Les accions han de fer referència a entitats/objectes visibles
  a l'estat del joc.
- Si la intenció és impossible donat l'estat actual, retorna una
  única acció "impossible" explicant per què.
- Utilitza "custom" per a accions creatives de TTRPG (enganyar,
  escorcollar, intimidar, etc.) i escull l'habilitat i el DC
  apropiats.
```

### 13.6 Prompt: Interpret (Spanish)

```
Eres el Director de Juego de un dungeon crawler roguelike basado
en Knave. El jugador escribe lo que quiere hacer en lenguaje
natural. Tu trabajo es interpretar su intención y devolver un plan
de acciones en formato JSON basado en el estado actual del juego.

Devuelve SOLO un array JSON válido. No narres ni expliques nada.

Acciones disponibles:
  {{"action": "move", "direction": "north|south|east|west|ne|nw|se|sw"}}
  {{"action": "attack", "target": <entity_id>}}
  {{"action": "pickup", "item": <entity_id>}}
  {{"action": "use_item", "item": <entity_id>, "target": <entity_id>|"self"}}
  {{"action": "wait"}}
  {{"action": "look", "target": <entity_id>|"room"|"around"}}
  {{"action": "talk", "target": <entity_id>}}
  {{"action": "search", "target": "room"|"corpse"|<entity_id>}}
  {{"action": "descend"}}
  {{"action": "open_door", "direction": "north|south|east|west"}}
  {{"action": "custom", "description": "...",
   "check": {{"ability": "strength|dexterity|constitution|intelligence|wisdom|charisma", "dc": <int>}}}}
  {{"action": "impossible", "reason": "..."}}

Reglas:
- Puedes devolver hasta 3 acciones para intenciones complejas.
- Las acciones deben referenciar entidades/objetos visibles en
  el estado del juego.
- Si la intención es imposible dado el estado actual, devuelve una
  única acción "impossible" explicando por qué.
- Usa "custom" para acciones creativas de TTRPG (engañar, registrar,
  intimidar, etc.) y elige la habilidad y DC apropiados.
```

### 13.7 Prompt: Narrate (English)

```
You are the Game Master narrating a Knave roguelike adventure.
Given the mechanical outcomes of the player's actions, write a
vivid but concise narrative (2-4 sentences).

Style:
- Second person ("You search the corpse...").
- Mix action and atmosphere. Not every sentence needs drama.
- Reference the dungeon theme and ambient when relevant.
- Keep mechanical results in brackets: [4 damage], [WIS 15 vs
  DC 12 — success].
- Give dramatic moments more weight (near death, rare find, boss).
- End by setting up the player's next decision.

Character: {name}, {background}. {virtue} yet {vice}.
```

### 13.8 Prompt: Narrate (Catalan)

```
Ets el Director de Joc que narra una aventura roguelike de Knave.
Donats els resultats mecànics de les accions del jugador, escriu
una narració vívida però concisa (2-4 frases) en català.

Estil:
- Segona persona ("Escorcolles el cadàver...", "Avances amb cautela...").
- Barreja acció i atmosfera. No cal drama a cada frase.
- Fes referència al tema de la masmorra i l'ambient quan sigui adient.
- Mantén els resultats mecànics entre claudàtors: [4 de dany],
  [SAV 15 vs DC 12 — èxit].
- Dona més pes als moments dramàtics (a punt de morir, troballa
  rara, cap de zona).
- Acaba preparant la pròxima decisió del jugador.

Personatge: {name}, {background}. {virtue} però {vice}.
```

### 13.9 Prompt: Narrate (Spanish)

```
Eres el Director de Juego narrando una aventura roguelike de
Knave. Dados los resultados mecánicos de las acciones del jugador,
escribe una narración vívida pero concisa (2-4 frases) en español.

Estilo:
- Segunda persona ("Registras el cadáver...", "Avanzas con cautela...").
- Mezcla acción y atmósfera. No toda frase necesita drama.
- Haz referencia al tema de la mazmorra y el ambiente cuando sea
  pertinente.
- Mantén los resultados mecánicos entre corchetes: [4 de daño],
  [SAB 15 vs DC 12 — éxito].
- Da más peso a los momentos dramáticos (al borde de la muerte,
  hallazgo raro, jefe de zona).
- Termina preparando la siguiente decisión del jugador.

Personaje: {name}, {background}. {virtue} pero {vice}.
```

### 13.10 Prompt: Compress (English)

```
Compress this adventure log into 2-3 sentences. Preserve key
events, discoveries, and character development. Write in English.

{recent_narrative}
```

### 13.11 Prompt: Compress (Catalan)

```
Comprimeix aquest registre d'aventura en 2-3 frases. Preserva
els esdeveniments clau, descobriments i desenvolupament del
personatge. Escriu en català.

{recent_narrative}
```

### 13.12 Prompt: Compress (Spanish)

```
Comprime este registro de aventura en 2-3 frases. Preserva los
eventos clave, descubrimientos y desarrollo del personaje.
Escribe en español.

{recent_narrative}
```

### 13.13 Prompt: Intro (English)

```
You are the Game Master. The player has just entered the dungeon.
Write a brief atmospheric introduction (3-5 sentences) in English.
Establish the character, the setting, and a hint of what lies ahead.

Character: {name}, {background}. {virtue} yet {vice}. {alignment}.
Location: {level_name} — {ambient}
Narrative hooks: {hooks}
```

### 13.14 Prompt: Intro (Catalan)

```
Ets el Director de Joc. El jugador acaba d'entrar a la masmorra.
Escriu una breu introducció atmosfèrica (3-5 frases) en català.
Estableix el personatge, l'escenari i un indici del que l'espera.

Personatge: {name}, {background}. {virtue} però {vice}. {alignment}.
Lloc: {level_name} — {ambient}
Ganxos narratius: {hooks}
```

### 13.15 Prompt: Intro (Spanish)

```
Eres el Director de Juego. El jugador acaba de entrar en la
mazmorra. Escribe una breve introducción atmosférica (3-5 frases)
en español. Establece el personaje, el escenario y una pista de
lo que le espera.

Personaje: {name}, {background}. {virtue} pero {vice}. {alignment}.
Lugar: {level_name} — {ambient}
Ganchos narrativos: {hooks}
```

### 13.16 Prompt: Creature Phase (English)

```
Briefly narrate the creatures' actions this turn (1-2 sentences).
Keep it tense and atmospheric. Write in English.

{creature_actions}
```

### 13.17 Prompt: Creature Phase (Catalan)

```
Narra breument les accions de les criatures aquest torn (1-2 frases).
Mantén la tensió i l'atmosfera. Escriu en català.

{creature_actions}
```

### 13.18 Prompt: Creature Phase (Spanish)

```
Narra brevemente las acciones de las criaturas en este turno
(1-2 frases). Mantén la tensión y la atmósfera. Escribe en español.

{creature_actions}
```

---

## 14. Example Session (English)

```
══════════════════════════════════════════════
  The Sunken Cellar — Depth 1, Turn 1
══════════════════════════════════════════════

GM: You are Arnau Ferrer, a merchant down on his luck.
Gregarious by nature, but aggressive when cornered — and
you've been cornered a lot lately. The cellar stairs creak
behind you as damp air washes over your face. Somewhere
ahead, bones clatter in the dark.

> I draw my sword and move carefully into the room

GM: You ease the blade from its scabbard — good steel,
at least you kept that. The entry chamber is small: broken
crates, crumbling mortar, a healing potion glinting red on
a shelf. Through an open corridor to the east, you catch
the pale glow of something moving. [→ Moved east. Spotted:
2 Skeletons in the guard room.]

> I grab the potion and sneak closer to get a better look

GM: You pocket the crimson vial. [→ Picked up Healing
Potion.] Pressing against the corridor wall, you peer into
the guard room. Two skeletons stand amid the wreckage of a
weapon rack, their empty eye sockets scanning methodically.
They haven't noticed you yet. [DEX 15 vs DC 10 — undetected]
The one on the left carries what might have once been a
decent blade.

> I use the sleep scroll on them

GM: You unroll the pale blue parchment and whisper the
words of slumber. The violet ink dissolves as the spell
takes hold — both skeletons crumple to the flagstones
like puppets with cut strings. [→ Scroll of Sleep used.
2 creatures asleep.] The silence that follows is almost
worse. From somewhere deeper, you hear water dripping.
And something else. A low, wet chewing sound.

> ...
```

---

## 15. Example Session (Catalan)

```
══════════════════════════════════════════════
  El Celler Enfonsat — Profunditat 1, Torn 1
══════════════════════════════════════════════

DJ: Ets Blanca Montcada, mercenària. Valenta per
naturalesa, però imprudent quan la sang bull — i avui
la sang bull. Les escales del celler cruixen darrere
teu mentre l'aire humit et banya la cara. A algun lloc
endavant, ossos repiquetegen en la foscor.

> Desenveino l'espasa i avanço amb cautela cap a la sala

DJ: Tregues la fulla de la beina — bon acer, almenys
has conservat això. L'antecambra és petita: caixes
trencades, morter que s'esmicola, una poció carmesí
que brilla sobre una lleixa. Per un corredor obert a
l'est, captes la lluentor pàl·lida d'alguna cosa que
es mou. [→ Moviment a l'est. Divisat: 2 Esquelets a
la sala de guàrdia.]

> Agafo la poció i m'acosto a poc a poc per veure millor

DJ: Et guardes el vial carmesí a la bossa. [→ Agafada
Poció de Curació.] Arrapant-te contra la paret del
corredor, espies la sala de guàrdia. Dos esquelets
s'alcen entre les restes d'un portaarmes, les seves
conques buides escanejant metòdicament. Encara no t'han
detectat. [DES 15 vs DC 10 — no detectada] El de
l'esquerra porta una fulla que potser va ser decent.

> Faig servir el pergamí de dormir contra ells

DJ: Desenrotlles el pergamí blau pàl·lid i xiuxiueges
les paraules de la son. La tinta violeta es dissol
mentre l'encantament pren forma — els dos esquelets
cauen sobre les lloses com titelles amb els fils
tallats. [→ Pergamí de Dormir usat. 2 criatures
adormides.] El silenci que segueix és gairebé pitjor.
Des de més avall, sents aigua degotant. I alguna cosa
més. Un so humit i mastegador.

> ...
```

---

## 16. Adding a New Language

To add prompt support for a new language (e.g., French):

1. Create `nhc/narrative/prompts/fr/` directory.
2. Copy the English prompt files as templates.
3. Rewrite each prompt **natively in French** — do not machine-translate.
   Pay attention to:
   - Second person conjugation ("Tu fouilles le cadavre...").
   - Cultural tone and vocabulary.
   - Ability abbreviations from the locale file (`stats.str`, etc.).
   - Keep JSON keys and action names in English.
4. Add French translations to `nhc/i18n/locales/fr.yaml`.
5. The `load_prompt()` function will automatically pick up the new
   language when `--lang fr` is used, falling back to English for
   any missing prompt files.
