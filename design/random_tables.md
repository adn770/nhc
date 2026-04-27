# Multilingual Random Tables & Dressing Generators

> **Status**: Design — not yet implemented. Supersedes the ad-hoc rumor generator
> in `nhc/hexcrawl/rumors.py` and unblocks dressing/naming subsystems required by
> the world expansion plan (`design/world_expansion.md`).

## 1. Overview

A generalized subsystem for multilingual random tables and composed dressing
generators. One mental model replaces the current one-off rumor pool and powers
every future "roll on a list" need in the game: room/hex dressing, NPC
attributes, encounter tables, folk sayings, character-name generators.

The subsystem has five capabilities:

1. **Pure flavor text** — pick one of N localized strings (e.g. room smell).
2. **Parameterized text** — strings with caller-supplied slots (e.g. `{hex_name}`).
3. **Composed/nested text** — sub-tables stitched together with `{@table_id}`.
4. **Structured outputs with side-effects** — roll returns text *plus* an
   effect (e.g. rumor reveals a hex, trap dressing spawns an entity).
5. **Weighted and conditional entries** — per-entry weights, and context-gated
   entries (`only_if: terrain=forest`).

### 1.1 Design principles

- **Data-driven.** Tables live in YAML. Adding a table does not require Python.
- **Language-quality baseline.** Tables provide the high-quality prose the
  smaller-LLM referees (a future experiment) can lean on without needing to
  generate fluent Catalan/Spanish themselves. See §9.
- **Deterministic where it matters.** World-gen rolls are seed-reproducible and
  baked into saves; ephemeral play-time rolls are live. Each table declares
  which lifetime it uses (§8).
- **Migration-friendly.** The template formatter sits behind an interface so a
  future move to Jinja is a one-file swap plus a mechanical YAML rewrite (§6.5).
- **Strict TDD.** Every milestone is red-green-refactor; one commit per
  milestone. See §11.
- **Python 3.14+.** Consistent with the rest of the codebase. The subsystem
  uses modern typing (`|` unions, `list[T]`, `dict[K, V]`), dataclasses with
  `match` where appropriate, and decorators for handler registration. No new
  runtime dependencies — `pyyaml` (already present) is the only non-stdlib
  module used.

### 1.2 Non-goals

- **Not a full morphology engine.** We handle gender/number agreement via
  inline forms declared on entries, not via inflection rules.
- **Not a replacement for the i18n UI-strings pipeline.** UI strings stay in
  `nhc/i18n/locales/*.yaml`. Tables live in a separate directory (§4).
- **Not an LLM orchestrator.** LLM paraphrase of table output is an opt-in
  bridge (§9), not a requirement.

### 1.3 Relationship to existing systems

| System                        | Role                                                            |
|-------------------------------|-----------------------------------------------------------------|
| `nhc/i18n/`                   | UI strings (buttons, action verbs, menu labels). Unchanged.     |
| `nhc/hexcrawl/rumors.py`      | Replaced by Phase 2 (§10). Wrapper then deletion.               |
| `nhc/narrative/` (LLM)        | Consumes table output as seed material in the opt-in §9 bridge. |
| `nhc/entities/` registries    | Pattern reference for the `TableRegistry` API (§5).             |

---

## 2. Data Model

Each table is a YAML document with a fixed schema. A table is the smallest unit
of "roll on this list" — the ID that callers pass to `registry.roll(...)`.

### 2.1 Table file shape

```yaml
# nhc/tables/locales/en/rumors.yaml
id: rumor.true_feature
kind: structured          # flavor | parameterized | composed | structured
lifetime: gen_time        # gen_time | ephemeral
shared_structure: true    # entries must match across en/ca/es

entries:
  - id: innkeeper_whisper
    weight: 2             # default 1
    text: >-
      The innkeeper leans close and whispers: "Folks swear there's
      something at hex ({q}, {r}). Worth a look."
    effect:
      kind: reveal_hex
      payload: { source: context }   # pulls {q},{r} from caller context

  - id: patron_mutter
    text: >-
      A grizzled patron mutters: "Seen lights near ({q}, {r}) on moonless
      nights." Worth asking around.
    effect:
      kind: reveal_hex
      payload: { source: context }
```

```yaml
# nhc/tables/locales/en/room_dressing.yaml
id: room.dressing.smell
kind: composed
lifetime: gen_time
shared_structure: true

only_if:
  room_type: [barracks, storeroom, crypt]   # condition on caller context

entries:
  - id: damp_moss
    text: The air smells of damp moss and wet stone.
  - id: rusted_iron
    text: A sharp tang of rusted iron lingers here.
  - id: old_tallow
    text: Old tallow and smoke cling to the walls.
```

### 2.2 Required fields

| Field             | Type         | Notes                                                 |
|-------------------|--------------|-------------------------------------------------------|
| `id`              | string       | Dotted ID, unique across all tables.                  |
| `kind`            | enum         | `flavor`, `parameterized`, `composed`, `structured`.  |
| `lifetime`        | enum         | `gen_time` (seed-reproducible) or `ephemeral` (live). |
| `shared_structure`| bool         | If `true`, validator enforces parity across locales.  |
| `entries`         | list         | One or more entries (see §2.3).                       |

### 2.3 Entry fields

| Field     | Type          | Notes                                                           |
|-----------|---------------|-----------------------------------------------------------------|
| `id`      | string        | Unique within the table.                                        |
| `text`    | string        | Template string. Substitution syntax in §6.                     |
| `weight`  | int (≥1)      | Optional; default `1`. Higher = more common.                    |
| `only_if` | map           | Optional; context conditions to include this entry.             |
| `effect`  | map           | Optional; `kind` + `payload`. See §7.                           |
| `forms`   | map           | Optional; inflected variants for agreement. See §6.3.           |
| `tags`    | list[string]  | Optional; free-form metadata (useful for Phase 4 callers).      |

### 2.4 Table-level conditions

A table may declare `only_if` at the top level; it gates the entire table and is
a convenience for the common "this whole room_dressing set only applies to
crypts" case. Entry-level `only_if` filters further.

---

## 3. Storage Layout

### 3.1 Directory

```
nhc/tables/
├── __init__.py              # re-exports TableRegistry, roll helpers
├── loader.py                # YAML → Table objects + schema validation
├── roller.py                # weighted pick + condition gating + seeding
├── formatter.py             # template resolution (str.format + {@...})
├── effects.py               # effect handler hybrid (built-in + custom)
├── registry.py              # TableRegistry class (lazy per-language load)
├── validator.py             # shared_structure drift check + CLI entry
└── locales/
    ├── en/
    │   ├── rumors.yaml
    │   ├── room_dressing.yaml
    │   └── hex_dressing.yaml
    ├── ca/
    │   ├── rumors.yaml
    │   └── ...
    └── es/
        └── ...
```

### 3.2 Shared-structure vs divergent tables

- **`shared_structure: true`** — same entry IDs, same weights, same `only_if`
  conditions across `en/ca/es`; only `text` (and optional `forms`) differ.
  Used for rumors, room dressing, hex dressing, most narrative content.
- **`shared_structure: false`** — entries genuinely differ per language. Used
  for name generators (English vs Catalan name pools are not translations),
  folk sayings, proverbs.

The validator (§3.3) enforces this flag. Divergent tables still live under the
per-language directory so the mental model stays "one file per table per
language"; they just opt out of the drift check.

### 3.3 Validator (M1)

For each `shared_structure: true` table, the validator asserts across
`en/ca/es`:

- Identical set of entry IDs.
- Identical `weight` per entry (missing = default `1`).
- Identical `only_if` conditions per entry.
- Identical top-level `kind`, `lifetime`, `only_if`.

Mismatches print the diff and exit non-zero.

#### 3.3.1 Invocation surfaces

Validator cost compounds as tables grow (dozens of tables × 3 languages). To
keep the default dev loop fast, the validator is **not** baked into the
standard `pytest` run. It has three entry points:

1. **CLI (primary).** Standalone Python entry:

   ```
   .venv/bin/python -m nhc.tables.validator
   ```

   Exits non-zero on any mismatch. Prints a diff per failing table. The
   programmatic API (`nhc.tables.validator.validate_all() -> list[ValidationError]`)
   is what both the CLI and the pytest marker call under the hood.

2. **Pytest marker (supplement).** A single parametrized test gated behind
   a `validator` marker:

   ```
   .venv/bin/pytest -m validator
   ```

   Not included in `-m "not slow"` (the default dev loop) or in the full
   suite. Devs run it explicitly before pushing. Scoped narrowly so it stays
   a one-liner option — not a tax on every iteration.

3. **Pre-deploy gate (CI stand-in).** `deploy/update.sh` runs the validator
   in the `nhc-base` Docker image between the base-image build and the
   app-image build. Deploy aborts if validation fails — no half-rolled
   release. Backwards-compatible via `[[ -d nhc/tables ]]` guard so pre-M1
   commits deploy unchanged.

   ```bash
   # In deploy/update.sh, after base-image build, before app-image build:
   if [[ -d nhc/tables ]]; then
       info "Validating multilingual tables..."
       docker run --rm -v "$REPO_DIR:/app" -w /app "$BASE_IMAGE" \
           python -m nhc.tables.validator \
           || fail "Table validation failed — deploy aborted."
       ok "Tables validated."
   fi
   ```

The unit tests in M1 cover `validator.py`'s logic on hand-crafted fixtures
under `tests/fixtures/tables/`, not on real `nhc/tables/locales/` content —
that stays a job for the CLI and pre-deploy hook.

> **Do not add the real-content scan to the default `pytest` run.** Validator
> cost scales with `tables × languages`; wiring it into the default dev loop
> would slow every iteration as the subsystem grows. The `validator` marker
> and the pre-deploy hook are the sanctioned surfaces.

---

## 4. Caller API

### 4.1 `TableRegistry`

```python
from nhc.tables import TableRegistry

registry = TableRegistry.load(lang="ca")         # lazy, cached per language
result = registry.roll(
    "rumor.true_feature",
    rng=rng,                                     # seeded or live
    context={"q": 5, "r": 3, "terrain": "forest"},
)
# result.text     — fully formatted string
# result.entry_id — which entry was picked (useful for tests / debug)
# result.effect   — TableEffect | None  (see §7)

# Deterministic re-render (no RNG): pick an entry by ID and format it.
# Used for language-switch re-render and save-replay.
result = registry.render(
    "rumor.true_feature",
    entry_id="innkeeper_whisper",
    context={"q": 5, "r": 3},
)
```

`roll()` picks an entry from the table (weighted + condition-gated + RNG).
`render()` takes an already-chosen `entry_id` and just formats it. Both
return `TableResult` so callers use them interchangeably downstream.

### 4.2 `TableResult` dataclass

```python
@dataclass(frozen=True)
class TableResult:
    text: str
    entry_id: str
    effect: TableEffect | None = None

@dataclass(frozen=True)
class TableEffect:
    kind: str                  # "reveal_hex", "spawn_entity", ...
    payload: dict              # handler-specific data
```

### 4.3 Module-level convenience wrapper

```python
from nhc.tables import roll

# Loads the registry for lang once, then rolls:
text = roll("room.dressing.smell", lang="ca", rng=rng,
            context={"room_type": "crypt"}).text
```

Internally calls `TableRegistry.get_or_load(lang).roll(...)`. Callers that
don't need the structured result can use `.text` directly.

### 4.4 Error model

| Situation                            | Behavior                                                     |
|--------------------------------------|--------------------------------------------------------------|
| Unknown table ID                     | `UnknownTableError` at `roll()` time.                        |
| No entries match `only_if` filters   | `NoMatchingEntriesError`; caller decides fallback.           |
| Sub-table `{@id}` unknown            | `UnknownTableError` (surfaces in the recursion pre-pass).    |
| Sub-table recursion > depth 8        | `RecursionTooDeepError` (guards against cyclic references).  |
| Context variable missing for `{v}`   | `MissingContextError`, names the variable.                   |
| Agreement slot missing in context    | Fall back to entry's `text` (§5.3); no error.                |
| Agreement tag missing from `forms`   | Fall back to entry's `text`; no error.                       |
| Effect `kind` has no registered handler | `UnknownEffectError` at `roll()` return time.             |

All errors carry the table ID and entry ID (where applicable) in the message.

**Design note on agreement fallbacks.** Agreement (`:agree=slot`) is best-effort
and non-fatal: missing metadata degrades gracefully to the default `text`
form. Rationale: a stray missing gender tag on one creature shouldn't crash
the rumor generator; at worst the line reads with a mildly-off adjective form.
Lint-level drift is the validator's job (Phase 4 extension), not the roller's.

---

## 5. Formatter

### 5.1 Substitution syntax

| Syntax                     | Meaning                                                      |
|----------------------------|--------------------------------------------------------------|
| `{name}`                   | Caller-supplied context variable (`context["name"]`).        |
| `{@table_id}`              | Roll `table_id`, substitute its resulting text.              |
| `{@table_id:agree=slot}`   | Roll `table_id`, then inflect per `slot`'s gender/number.    |

Example:

```yaml
- id: approach_line
  text: >-
    {@table:adjective:agree=creature} {@table:creature} was seen
    near the {landmark}.
```

### 5.2 Resolution order

1. **Pre-pass** — recursively resolve `{@...}` markers, bottom-up. Each
   sub-roll produces its own `TableResult`, whose `text` replaces the marker.
   The outermost call's effect is preserved; sub-roll effects are dropped
   unless the caller opts into collecting them (future extension).
2. **`str.format(**context)`** — substitute remaining `{name}` slots. A
   missing key raises `MissingContextError` (§4.4), naming the variable.

### 5.3 Agreement (`:agree=slot`)

When an entry declares `forms:`, it exposes variants for gender/number:

```yaml
- id: savage
  text: savage                    # default (used when no agreement hint)
  forms:
    m: salvatge
    f: salvatge
    mp: salvatges
    fp: salvatges
```

(Catalan adjective `salvatge` happens to be invariant; Spanish adjectives like
`viejo`/`vieja`/`viejos`/`viejas` show the inflection more sharply.)

When a parent template uses `{@table:adjective:agree=creature}`:

1. The formatter rolls `table.adjective` normally.
2. It reads `context["creature"]` or the most recent `{@creature}` sub-roll's
   metadata to determine gender/number (`m`/`f`/`mp`/`fp`).
3. If the picked adjective entry has `forms[<tag>]`, use that; else fall back
   to `text`.

Your existing creature i18n already tags `gender: "m"` / `gender: "f"`, so
creatures are agreement-ready. Number defaults to singular unless the context
supplies `{count: >1}`.

### 5.4 Recursion and cycle protection

The resolver tracks a depth counter (max 8) and a visited-table stack. A
sub-table that refers to itself, even transitively, raises
`RecursionTooDeepError` with the cycle printed.

### 5.5 Interface (Jinja escape hatch)

```python
class TableFormatter(Protocol):
    def format(self, template: str, context: dict,
               roll_subtable: Callable[[str], TableResult]) -> str: ...
```

The default implementation is `StrFormatFormatter` (~30 lines). Swapping to a
`Jinja2Formatter` later is a one-file change plus a mechanical YAML rewrite:

| Current                    | Jinja                                     |
|----------------------------|-------------------------------------------|
| `{name}`                   | `{{ name }}`                              |
| `{@id}`                    | `{{ roll("id") }}`                        |
| `{@id:agree=slot}`         | `{{ roll("id") \| agree("slot") }}`       |

A `sed` pass over `nhc/tables/locales/` handles the rewrite. No data model
changes.

---

## 6. Effects (Hybrid Handler Model)

### 6.1 Built-in handlers (ship with Phase 1)

| `kind`          | Payload shape                                 | Behavior                                           |
|-----------------|-----------------------------------------------|----------------------------------------------------|
| `reveal_hex`    | `{q: int, r: int}` or `{source: "context"}`   | Reveal the hex on the fog-of-war map.              |

Only `reveal_hex` is built in for Phase 1; it's the one effect needed to
replace the current rumor system (§10).

### 6.2 Custom handler registration

```python
from nhc.tables.effects import register_effect_handler

@register_effect_handler("spawn_creature")
def spawn_creature(payload: dict, world) -> None:
    creature_id = payload["entity"]
    at = payload["at"]
    world.spawn(creature_id, at)
```

Handlers receive the effect's payload and a caller-supplied context object
(type-erased so each caller passes what it needs — `world`, `game`, `level`).
Effects are **applied by the caller**, not automatically by `roll()`. The roll
returns `TableResult`; the caller decides when/whether to dispatch the effect:

```python
result = registry.roll("rumor.true_feature", rng=rng, context=ctx)
if result.effect:
    apply_effect(result.effect, world=world)
```

This keeps `roll()` pure and testable, and lets callers introspect or veto the
effect (e.g. save-game replay doesn't re-apply reveals because the state was
persisted).

### 6.3 Dispatcher

```python
from nhc.tables.effects import apply_effect
apply_effect(result.effect, world=world)   # routes to the registered handler
```

Unknown `kind` → `UnknownEffectError`.

### 6.4 Why hybrid, not pure DSL or pure callback

- **Pure DSL** fails at the long tail: some effects need game-state access no
  YAML can express (conditional spawn based on floor level, etc.).
- **Pure callback** forces every caller to write glue for common cases and
  defeats the "data-driven" principle.
- **Hybrid** gives built-ins for the 80% cases (`reveal_hex`,
  `spawn_entity` in a later milestone) and an escape hatch for the rest.

---

## 7. Determinism & Lifetime

### 7.1 Two lifetimes

| `lifetime`  | RNG source          | Persisted in save?     | Use cases                          |
|-------------|---------------------|------------------------|------------------------------------|
| `gen_time`  | Seeded `Random`     | Yes (result is baked)  | Rumors, baked room/hex dressing.   |
| `ephemeral` | Live `random.Random`| No                     | Innkeeper dialog, on-inspect prose.|

### 7.2 Why both

- Save/restore reproduces the world state, not the flavor text *per look*.
  Room dressing rolled at dungeon-gen is written into the room's state and
  shown identically every time the player enters. That's `gen_time`.
- Interactive flavor (e.g. a barkeep's comment when the player chats) shouldn't
  lock to a save-game seed — the same save replayed should give different
  lines each time. That's `ephemeral`.

### 7.3 Enforcement

`TableRegistry.roll` inspects the table's `lifetime`:

- `gen_time`: requires the caller to pass a seeded `rng`. Passing `None` or
  `random.Random()` without a seed raises `GenTimeRNGRequiredError` to catch
  accidental live-rolls of save-critical content.
- `ephemeral`: accepts any RNG; a `None` argument uses the process-global
  `random` module.

---

## 8. LLM Bridge (Phase 4+, not built in Phase 1)

### 8.1 Motivation

You plan to experiment with **smaller LLMs as DM referees** whose language
capabilities are weaker than flagship models. High-quality Catalan/Spanish
prose is hard for small models. Tables ship with human-authored prose, so a
small LLM can:

- Pick a decision (which rumor, which room to describe).
- Accept a table-rolled line as the final prose, or paraphrase it lightly.

### 8.2 Default path (Phase 1–3)

Pure-table. `result.text` goes straight to the player. No LLM involved.

### 8.3 Opt-in paraphrase (later)

Callers who want LLM enrichment pass the `TableResult.text` as seed material:

```python
seed = registry.roll("room.dressing.sight", ...).text
prose = narrator.paraphrase(seed, tone="ominous", lang="ca")
```

The narrator prompt instructs: *"Rewrite the given line in the player's voice
and tone without changing the facts. Keep it under 2 sentences."* This
preserves table-level determinism for facts and gives prose variation for
atmosphere. Gated by a per-use-case config flag; default off.

---

## 9. Rumor Migration (Strangler-Fig)

Three-milestone cutover (§11: M6, M7, M8).

### 9.1 Current state

- `nhc/hexcrawl/rumors.py` — `generate_rumors()`, `generate_rumors_god_mode()`,
  `gather_rumor_at()`, two hardcoded keys (`rumor.true_feature`,
  `rumor.false_lead`).
- Locale files already carry the two keys (`en.yaml:1341`, `ca.yaml:1447`,
  `es.yaml:1373`).
- Callers: `nhc/core/game.py` (`_maybe_seed_rumors`), `nhc/entities/creatures/innkeeper.py`,
  `nhc/core/actions/_innkeeper.py`, `nhc/hexcrawl/town.py`, debug tools,
  `nhc/core/save.py`.
- Tests: `tests/unit/hexcrawl/test_rumors.py`, `test_rumor_refresh.py`,
  `test_rumor_auto_seed.py`, `test_innkeeper.py`, plus debug-tool tests.

### 9.2 Target state

- Two tables: `nhc/tables/locales/{en,ca,es}/rumors.yaml` with
  `rumor.true_feature` and `rumor.false_lead` entries, `shared_structure: true`,
  `lifetime: gen_time`, `effect.kind: reveal_hex`.
- The locale `rumor:` block becomes redundant and is removed.
- `nhc/hexcrawl/rumors.py` deleted; callers use `TableRegistry` directly.

### 9.3 `Rumor` dataclass evolution

To support language switching mid-save and sub-table composition, the `Rumor`
dataclass stores both pre-rendered prose and enough metadata to re-render in
a different locale.

```python
@dataclass
class Rumor:
    """A piece of intel acquired at a settlement."""
    id: str                         # stable UUID ("rumor_<seed>_<idx>")
    text: str                       # pre-rendered prose for UI (current lang)
    truth: bool = True
    reveals: HexCoord | None = None
    # Provenance — enough to re-render in another language:
    source: RumorSource | None = None

@dataclass(frozen=True)
class RumorSource:
    table_id: str                   # "rumor.true_feature"
    entry_id: str                   # which entry was picked
    context: dict                   # the context dict passed to roll()
    lang: str                       # the language the text is currently in
```

**Re-render on language switch** (e.g. player flips UI language mid-run):

```python
def refresh_rumor_language(rumor: Rumor, new_lang: str) -> None:
    if rumor.source is None or rumor.source.lang == new_lang:
        return
    registry = TableRegistry.get_or_load(new_lang)
    result = registry.render(                    # not roll — pick by entry_id
        rumor.source.table_id,
        entry_id=rumor.source.entry_id,
        context=rumor.source.context,
    )
    rumor.text = result.text
    rumor.source = replace(rumor.source, lang=new_lang)
```

This requires one additional `TableRegistry.render(table_id, entry_id, context)`
method alongside `roll()` — it looks up an entry by ID (no RNG, no weights)
and runs the formatter. Useful for both this language-refresh path and future
deterministic-replay use cases.

**Save serialization.** `RumorSource` becomes a plain dict in the save JSON.
Old saves without `source` still load (field is optional) — rumors from pre-
migration saves simply don't re-render on language switch, which is graceful.

### 9.3 Cutover steps

See M6–M8 in §11. Each milestone keeps the test suite green and lands in a
single commit.

---

## 10. Milestones & TDD Discipline

**Every milestone follows the same loop, stated once here and referenced below:**

1. **Red** — write the failing tests first under `tests/unit/tables/`
   (or `tests/unit/hexcrawl/` for rumor-migration milestones). Run:
   `.venv/bin/pytest tests/unit/tables/ -v`.
2. **Green** — implement the minimum code to pass.
3. **Refactor** — clean up; ensure the dev loop stays green:
   `.venv/bin/pytest -n auto --dist worksteal -m "not slow"` (~24s).
4. **Commit** — one commit per milestone, GNOME/freedesktop convention
   (`topic: short summary`, ≤70 chars, imperative mood, no trailing period,
   body wrapped at 80 chars). Strip trailing whitespace before staging.

### 10.1 Phase 1 — Foundation

#### M1 — Loader + schema validator + deploy gate
- **Scope**:
  - `nhc/tables/loader.py`, `nhc/tables/validator.py`. YAML → in-memory
    `Table` objects. Enforce required fields, `kind`/`lifetime` enums.
    Shared-structure drift check across `en/ca/es`.
  - Programmatic `validate_all() -> list[ValidationError]` API.
  - `python -m nhc.tables.validator` CLI entry (prints diffs, exits non-zero
    on failure).
  - `validator` pytest marker registered in `pyproject.toml`
    (`[tool.pytest.ini_options]` `markers` list). One parametrized test
    under the marker scans real table files via `validate_all()` — runs
    on explicit `pytest -m validator`, excluded from default dev loop.
  - `deploy/update.sh` pre-deploy gate: run the validator in `nhc-base`
    between base-image build and app-image build (see §3.3.1). Guarded by
    `[[ -d nhc/tables ]]` for pre-M1 deploys.
- **Tests (write first)**: happy-path load; missing required fields; bad enums;
  shared-structure mismatch (entry IDs, weights, `only_if`); divergent tables
  skip the check; validator CLI exit code on success and failure. Unit tests
  use small hand-crafted fixtures in `tests/fixtures/tables/` — they do NOT
  scan real `nhc/tables/locales/` content, so they stay fast.
- **Commit**: `tables: add loader, schema validator, and deploy gate`

#### M2 — Roller core
- **Scope**: `nhc/tables/roller.py`. Seeded RNG, weighted pick, `only_if`
  context gating (table-level and entry-level).
- **Tests**: distribution over 10 000 rolls is within weight tolerance; two
  rolls with the same seed produce the same entry; `only_if` filters exclude
  non-matching entries; `NoMatchingEntriesError` when every entry is filtered.
- **Commit**: `tables: add weighted roller with context gating`

#### M3 — Formatter
- **Scope**: `nhc/tables/formatter.py`. `TableFormatter` protocol,
  `StrFormatFormatter` implementation: `{name}` substitution, `{@id}`
  recursive sub-table roll, `{@id:agree=slot}` agreement lookup,
  depth/cycle guard.
- **Tests**: plain context substitution; nested sub-table; two-level nesting;
  agreement hits masculine/feminine/plural forms; cycle raises
  `RecursionTooDeepError`; missing context key raises `MissingContextError`
  with the variable name.
- **Commit**: `tables: add template formatter with sub-table composition`

#### M4 — Effects hybrid
- **Scope**: `nhc/tables/effects.py`. `TableEffect`, `TableResult`,
  `register_effect_handler`, `apply_effect` dispatcher, built-in
  `reveal_hex` handler.
- **Tests**: `reveal_hex` mutates a fake world's fog; custom handler registers
  and fires; unknown `kind` raises `UnknownEffectError`; entries without an
  effect return `result.effect is None`.
- **Commit**: `tables: add effect handler hybrid with reveal_hex builtin`

#### M5 — Registry API
- **Scope**: `nhc/tables/registry.py`. `TableRegistry.load(lang)`,
  `.roll(id, rng, context)`, `.render(id, entry_id, context)`, lazy
  per-language caching, module-level `roll()` wrapper, lifetime enforcement
  (gen_time RNG check).
- **Tests**: per-language load isolation; cache hit on second `load(lang)`;
  unknown-id error; gen_time roll without seeded RNG raises
  `GenTimeRNGRequiredError`; ephemeral roll accepts `None` RNG;
  `render(entry_id=...)` returns the same entry deterministically across
  languages (load `ca`, render by `entry_id`, result text differs from `en`).
- **Commit**: `tables: add TableRegistry with lifetime enforcement`

### 10.2 Phase 2 — Rumor migration

#### M6 — Rumor port (inner layer)
- **Scope**: Create `nhc/tables/locales/{en,ca,es}/rumors.yaml` with the two
  existing keys. Rewrite `nhc/hexcrawl/rumors.py::generate_rumors` to call
  `registry.roll("rumor.true_feature" | "rumor.false_lead")` internally.
  Evolve the `Rumor` dataclass (§9.3): replace `text_key` with `text`, add
  optional `source: RumorSource`. Add `refresh_rumor_language()` helper.
  Locale `rumor:` block stays for this milestone to minimize blast radius.
- **Tests**: existing rumor tests stay green (signature of `generate_rumors`
  unchanged). New tests: `Rumor.source` is populated; `refresh_rumor_language`
  swaps `.text` but preserves `.id`/`.reveals`/`.truth`; save/load roundtrip
  preserves `source`; old-save compatibility (missing `source` → `None`);
  registry is used (spy).
- **Commit**: `rumors: port generator onto TableRegistry`

#### M7 — Callers migrate
- **Scope**: Replace `generate_rumors()` call sites in `nhc/core/game.py`,
  `nhc/entities/creatures/innkeeper.py`, `nhc/core/actions/_innkeeper.py`,
  `nhc/hexcrawl/town.py`, debug tools, with direct `TableRegistry` usage.
  Delete the now-unused wrapper functions in `nhc/hexcrawl/rumors.py` (module
  still exists for the `Rumor` dataclass if needed).
- **Tests**: all rumor/innkeeper tests still green. No new behavior, only
  call-site changes.
- **Commit**: `rumors: migrate callers to TableRegistry`

#### M8 — Delete `nhc/hexcrawl/rumors.py`
- **Scope**: Move the `Rumor` dataclass to `nhc/hexcrawl/model.py` (it's
  already referenced from there) or `nhc/tables/types.py` if it's better
  sitting in the new subsystem. Delete `nhc/hexcrawl/rumors.py`. Remove the
  redundant `rumor:` block from `{en,ca,es}.yaml` (text now lives in the
  tables file).
- **Tests**: full suite green.
- **Commit**: `rumors: remove legacy module`

### 10.3 Phase 3 — New consumers (unblocks world expansion)

#### M9 — Room dressing (gen-time)
- **Scope**: Tables for `room.dressing.smell`, `room.dressing.sight`,
  `room.dressing.sound` with condition gating by `room_type`. BSP dungeon gen
  rolls dressing at generation time, bakes result into the room's state,
  serialized in saves.
- **Tests**: generator rolls dressing during dungeon-gen; reproducible under
  world-gen seed; `only_if: room_type=X` filters correctly; save/restore
  preserves the dressing text.
- **Commit**: `dungeon: add gen-time room dressing via tables`

#### M10 — Hex dressing (gen-time)
- **Scope**: Tables for `hex.dressing.<terrain>` keyed by terrain and feature
  type. Hexcrawl world-gen rolls dressing at overland generation time.
- **Tests**: one dressing per terrain type; feature-gated entries
  (e.g. cave-only lines only appear on cave hexes); reproducible.
- **Commit**: `hexcrawl: add gen-time hex dressing via tables`

#### M11 — Ephemeral rolls
- **Scope**: Formalize the ephemeral path. Add `nhc.tables.roll_ephemeral()`
  convenience or a `lifetime=ephemeral` check path in `roll()`. Wire one
  live-play example (e.g. innkeeper idle chatter pulled from a new
  `innkeeper.chatter` table).
- **Tests**: two ephemeral rolls of the same table with no seed produce
  different results across runs; ephemeral content is not in saves; gen_time
  tables still reject non-seeded RNGs.
- **Commit**: `tables: add ephemeral roll path with innkeeper chatter demo`

#### M12 — Character name generator (divergent tables)
- **Scope**: First consumer of `shared_structure: false`. Unblocks settlements
  (world-expansion Phase 4) by providing per-language name pools ahead of
  them needing names.
  - Files: `nhc/tables/locales/{en,ca,es}/names.yaml`.
  - Tables per language (`shared_structure: false`, `lifetime: gen_time`):
    - `name.given.male` — flat list, ~30 entries.
    - `name.given.female` — flat list, ~30 entries.
    - `name.surname` — flat list, ~40 entries.
    - `name.person.full` — composed; dispatches on `context["gender"]` via
      `only_if` (no new syntax needed):
      ```yaml
      - id: name.person.full
        kind: composed
        lifetime: gen_time
        shared_structure: false
        entries:
          - id: male_full
            only_if: { gender: m }
            text: "{@name.given.male} {@name.surname}"
          - id: female_full
            only_if: { gender: f }
            text: "{@name.given.female} {@name.surname}"
      ```
  - **Content authenticity**: Catalan pool reflects native culture (e.g.
    Jordi, Marta, Josep; Puig, Fabra, Roca) — not translations of English
    names. Spanish likewise (Jorge, María; García, Martínez). English
    standard pool.
  - **No downstream integration in this milestone.** The generator is
    callable via `registry.roll("name.person.full", ...)`; consumer wiring
    (innkeeper name, settlement NPCs) happens when those features land.
- **Tests (write first)**:
  - Divergent table loads; validator skips the cross-lang drift check and
    does not error on differing entry IDs.
  - `roll("name.person.full", context={"gender": "m"})` returns "given
    surname" format from the male pool.
  - Gender gating: `gender=f` picks from female pool; `gender=m` from male.
    Missing `gender` in context raises `NoMatchingEntriesError`.
  - Reproducibility: same seed + same lang + same gender → same full name.
  - Language isolation: rolling on `en` vs `ca` vs `es` produces names from
    distinct pools (no overlap on the lexical level).
  - Character-set sanity: at least one entry in the `ca` pool contains a
    Catalan-specific character (`ç`, `l·l`, or an accented vowel) — catches
    a regression where someone accidentally populates `ca/` with English
    strings.
- **Commit**: `tables: add divergent character name generator`

### 10.4 Phase 4 — Future (documented, not built)

Each becomes its own milestone when the consuming feature needs it.

- **NPC dressing** — profession, quirk, appearance. Ties into the small-LLM
  referee plan (§8.1); tables provide the prose, LLM decides the plot role.
  Integrates with the M12 name generator via `{@name.person.full}`.
- **Wandering-encounter / trap tables** — demonstrates a new built-in handler
  `spawn_entity`. Per-terrain encounter tables; per-floor trap tables.
- **Folk sayings / proverbs** — pure divergent; adds atmosphere per region or
  faction. Hooked into dialogue tables via `{@sayings.dwarvish}`.
- **Caves of Chaos faction tables** (world-expansion Phase 6) — faction
  names, war cries, banner descriptions, all composed.

---

## 11. Open Questions (future design work)

These are deliberately deferred. Each has a known answer direction but isn't
needed for Phase 1–3 and would bloat the initial scope:

1. **Sub-roll effect propagation.** Currently sub-rolls' effects are dropped.
   A later caller may want to collect them (e.g. a composed encounter that
   both spawns a creature and reveals a hex). Add opt-in collection mode
   when a concrete case arrives.
2. **Per-seed pool depletion.** Some tables want "don't repeat the same entry
   within N rolls" (e.g. room dressing across one dungeon). Solvable with a
   caller-maintained exclusion set passed in via `context`, but a built-in
   helper may be warranted once we have the data.
3. **Localized effect payloads.** If an effect ever needs language-specific
   data (unlikely — effects are mechanical), we'd need per-locale payloads.
   Not worth modeling until it happens.

---

## 12. Appendix — Full example (rumors)

### 12.1 `nhc/tables/locales/en/rumors.yaml`

```yaml
- id: rumor.true_feature
  kind: structured
  lifetime: gen_time
  shared_structure: true
  entries:
    - id: innkeeper_whisper
      weight: 1
      text: >-
        The innkeeper leans close and whispers: "Folks swear there's
        something at hex ({q}, {r}). Worth a look."
      effect:
        kind: reveal_hex
        payload: { source: context }

- id: rumor.false_lead
  kind: structured
  lifetime: gen_time
  shared_structure: true
  entries:
    - id: old_timer_tale
      text: >-
        An old timer nurses his ale and mumbles: "Saw something queer
        out near ({q}, {r}), years ago." The tale feels thin.
      effect:
        kind: reveal_hex
        payload: { source: context }
```

### 12.2 Caller (replaces `generate_rumors`)

```python
from nhc.tables import TableRegistry

def generate_rumors(world, seed, count=3, lang="en"):
    rng = random.Random(seed)
    registry = TableRegistry.get_or_load(lang)
    rumors: list[Rumor] = []
    features = _feature_coords(world)
    plains = _plain_coords(world)
    true_n = (count + 1) // 2
    false_n = count - true_n

    def _make(table_id: str, truth: bool, coord: HexCoord) -> Rumor:
        context = {"q": coord.q, "r": coord.r}
        result = registry.roll(table_id, rng=rng, context=context)
        return Rumor(
            id=f"rumor_{seed}_{len(rumors)}",
            text=result.text,                              # rendered prose
            truth=truth,
            reveals=coord,
            source=RumorSource(
                table_id=table_id,
                entry_id=result.entry_id,
                context=context,
                lang=lang,
            ),
        )

    for _ in range(true_n):
        if not features: break
        rumors.append(_make("rumor.true_feature", True, rng.choice(features)))
    for _ in range(false_n):
        if not plains: break
        rumors.append(_make("rumor.false_lead", False, rng.choice(plains)))
    return rumors
```

Note: `Rumor.text_key` becomes `Rumor.text` (pre-rendered). The `source`
field carries provenance (table ID, picked entry, context, language) so
`refresh_rumor_language()` can re-render into a different locale without
needing the original RNG or re-rolling. The narrator no longer resolves a
locale key at dialogue time.
