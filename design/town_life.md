# Town Life

This document is the design contract for the **town life** subsystem: the set of citizens,
schedules, behaviours, and events that make a town *site* feel inhabited rather than static. It
covers what a "living town" is, how time flows inside it, how citizens know where to be, what new
behaviours and roster entries exist, and how the player perceives all of it.

It builds on three existing contracts and does not restate them:

- `design/sites.md` — how a town surface Level is assembled and dispatched (`assemble_town`,
  `Game.enter_site`, the site cache).
- `design/views.md` — the five-view hierarchy; town life is active only in the **site** view (and
  the **structure** view of buildings on that site).
- The AI layer in `nhc/ai/` — `behavior.py` (dispatch, `CHASE_RADIUS`, `PEACEFUL_BEHAVIORS`),
  `pathfinding.py` (A*), `tactics.py` (morale).

## Design intent

A living town is a **diorama the player walks through**, not a social-RPG conversation system. The
life is carried by *what citizens do* — crowds that thin at dusk, a watch that comes out at night, a
blacksmith who leaves the forge at the evening hour — and narrated through the message log. It is
read through **behaviour and text, not through new visuals or dialogue UI**.

Concretely, in scope:

- A visible **day/night rhythm** inside a single visit (slow-drift clock).
- **Bustle**: a wider cast of human citizens with purposeful motion.
- **Things happening**: scheduled spectacle and minor incidents the town reacts to.

Explicitly **out of scope** (deferred or rejected during design):

- Dialogue / `TalkAction`, NPC personality, memory, relationships, reputation, trade UI.
- Night/time-of-day surface tinting or any new render-pipeline atmospherics.
- Speech bubbles or any new canvas UI.
- Animals / strays as citizens.
- Player-facing event stakes (events never target or endanger the player directly).

Citizens read as distinct through their **role name on hover** (existing entity metadata) and their
behaviour; events read through **message-log lines**. No new web client code is required.

## Town time: slow drift

Today the world clock (`HexWorld.day`, `HexWorld.time: TimeOfDay`) only advances during overland
travel. A town site is frozen in time while the player walks it. Town life requires time to move,
but not at a stopwatch pace.

**Model: hybrid slow drift.** While `Game._active_site` is set (the player is in the site or a
structure on it), each player turn advances the clock by a small fraction of a segment. A short
errand feels stable; a long visit can tip morning into midday. The throttle is a single tunable
(turns-per-segment) and the advance is purely additive on the existing clock — no second clock.

`TimeOfDay` keeps its four segments: `MORNING`, `MIDDAY`, `EVENING`, `NIGHT`. The current segment is
exposed to AI decisions (passed into / readable from `decide_action`) so schedule-aware behaviours
can branch on it. Crossing a segment boundary inside a town is an observable event (see
**Events** — the crier announces the new hour).

Persistence is **deterministic-by-time** (see below): the clock value is real and saved, but citizen
positions are *re-derived* from it on entry rather than stored per-NPC.

## Schedules: the DailyRoutine model

Citizens know where to be via a new `DailyRoutine` component. It generalizes today's single-anchor
`Errand` (`anchor_x/y`, `anchor_weight`) into a per-segment anchor map:

```
DailyRoutine:
    anchors: dict[TimeOfDay, RoutineAnchor]   # where this NPC belongs, per segment
    default_behavior: str                      # "errand" | "idle" | "patrol"
```

A `RoutineAnchor` resolves to a tile region on the surface — bound at spawn to a meaningful place:

- **Workplace** — a building door or interior tied to the NPC's trade (forge, market stall, well,
  tavern). Working folk anchor here during work segments.
- **Social** — a plaza, fountain, or well apron. Street-margin folk and off-duty workers cluster
  here; door-adjacent bias (already in errand) provides natural gathering.
- **Home** — a residential building. At `NIGHT`, most folk route home and despawn at the threshold
  (deterministic regen means they reappear next visit, not a saved body in a bed).
- **Route** — a patrol waypoint loop (watch, crier). See `patrol` below.

Schedule-aware `errand` reads the current segment's anchor instead of a fixed one. The existing
loiter loop (3–8 idle turns at destination, door-adjacent bias) is retained. The net effect: the
same NPC drifts toward the market at `MIDDAY` and the tavern at `EVENING` without any new pathfinding.

Default day shape (per role family, tunable):

| Segment   | Working folk        | Watch / authority      | Street margins          |
| --------- | ------------------- | ---------------------- | ----------------------- |
| `MORNING` | open up / to work   | patrol routes          | wake, drift to social   |
| `MIDDAY`  | at workplace        | patrol routes          | cluster at plaza/market |
| `EVENING` | wind down / tavern  | patrol routes          | tavern / busk           |
| `NIGHT`   | home (despawn)      | the watch comes out    | thin out; few remain    |

`NIGHT` is where the rhythm is most legible: the bustle empties, working folk are gone, and the watch
becomes the dominant presence — all conveyed through behaviour, not lighting.

## Behaviours

Town life reuses two existing peaceful behaviours and adds one:

- **`idle`** (existing) — stand and serve. Workplace NPCs that don't roam (blacksmith at the forge,
  vendor at the stall) are `idle` anchored to a workplace, *active by segment* (gone at night).
- **`errand`** (existing, extended) — wander with anchor bias, now **schedule-aware** via
  `DailyRoutine`. Destination picking reads the current segment's anchor.
- **`patrol`** (new) — follow a fixed route of waypoints, looping. Backed by a new `PatrolRoute`
  component (ordered waypoint list + loop flag + cursor). **Interruptible**: a patrolling guard can
  break route to converge on an incident, then resume from the nearest waypoint. Used by guards and
  the town crier.

`patrol` joins `PEACEFUL_BEHAVIORS` (the first-attack confirmation guard applies) and gets a
`CHASE_RADIUS` entry of 0 — patrollers do not hunt the player; they only break route for *town
events*, never for the player as a target.

Morale, retreat, and the aggressive/guard state machine are untouched — town citizens are peaceful
and do not participate in them except when an incident makes a specific NPC (e.g. a caught
pickpocket) a temporary target of the *guards*, not the player.

## Citizen roster

All new citizens are `human` faction (or `neutral` where apt), reusing the registry factory pattern
(`@EntityRegistry.register_creature`) and requiring `name`/`short`/`long`/`gender` entries in all
three locale files (`en`/`ca`/`es`). Three families:

- **Working folk** (workplace-anchored): `blacksmith`, `market_vendor`, `baker`, `water_carrier`,
  `washerwoman`, `porter`. Mostly `idle` at a workplace, `errand` between segments.
- **Watch & authority** (`patrol`): `town_guard`, `watch_captain`, `town_crier`. The crier
  announces segment changes; guards form the incident-response pool.
- **Street margins** (`errand`/`idle`, social-anchored, cluster): `beggar`, `drunk`, `busker`,
  `urchin`, `preacher`.

Exact glyphs/colours are chosen at implementation time to stay legible against existing town NPCs
(merchant, innkeeper, priest, villager, noble, pilgrim, pickpocket, guard). Where a sensible existing
creature already covers a slot (e.g. `guard`), it is reused/extended rather than duplicated.

## Population and density scaling

The new cast is spawned by `assemble_town` / the town population path, scaled across all four size
classes from the start (no later scaling pass):

| Size      | Working folk | Watch          | Street margins | Notes                          |
| --------- | ------------ | -------------- | -------------- | ------------------------------ |
| `hamlet`  | 1–2          | 0–1            | 0–1            | sparse; maybe a single guard   |
| `village` | 2–4          | 1–2            | 1–2            | a vendor, a guard, a beggar    |
| `town`    | 4–7          | 2–3 + crier    | 2–4            | market, patrol, tavern crowd   |
| `city`    | 8–14         | 4–6 + captain  | 4–8            | full bustle, multiple patrols  |

Counts are budgets, not fixed — rolled per seed. Each spawned citizen is assigned a `DailyRoutine`
whose anchors bind to actual generated features (workplace building of matching role, nearest plaza,
a residential building, a patrol loop around the street spine). Density and routine assignment are
deterministic from the site seed + size class.

## Events: spectacle and minor incidents

A **town event director** rolls, per visit and at segment boundaries, what (if anything) is staged.
Two tiers, both surfaced through the message log; the player may watch or nudge but is never the
target:

- **Scheduled spectacle** — atmospheric, no reaction logic: a **market day** (extra vendors + a
  crowd anchored to the big plaza), a **procession** (a line of citizens crossing the spine), the
  **crier announcing the hour** at each segment change.
- **Minor incidents** — the town reacts: a **pickpocket caught** → nearby guards break patrol and
  converge/chase the thief; a **tavern brawl** → two drunks scuffle near the inn; a **public
  argument**. Incidents drive the `patrol` interrupt path: guards path to the incident tile, resolve
  it (the offender flees to a town edge and despawns, as the existing `thief` flee logic already
  does), then resume their route.

Incidents reuse existing primitives — `thief` flee-to-edge, A* convergence, message events. No new
combat or consequence system, and no balancing against the player.

## Perception

Per the web-only constraint, the player perceives town life with **no new client code**:

- **Motion** — the existing per-turn entity broadcast and canvas rendering carry crowds, patrols,
  and clustering. (Confirm the visible-entity gather scales to higher town NPC counts.)
- **Message-log text** — events emit log lines ("A crier calls the evening hour.", "Guards rush
  toward a commotion."). Segment changes and incidents are the primary textual signal of the
  day/night rhythm.
- **Hover role names** — each new citizen's `Description.name`/`short` gives a distinct label on the
  existing hover tooltip, so the cast reads as varied.

No night tinting, no speech bubbles, no inspect/talk/trade UI.

## Persistence

**Deterministic-by-time regeneration.** Citizen positions and events are *not* written to the
save/site-cache mutation log. On entering a town, citizens are placed according to the current
`TimeOfDay` (derived from the saved clock) and a per-visit event roll keyed on the site seed + day +
segment. Re-entering an hour later genuinely looks different because the clock moved, not because
state was stored.

Consequence accepted at design time: an incident in progress is **not** frozen and resumed across a
leave/re-enter — stepping out and back rolls fresh. This keeps saves lean and revisits lively, which
matched the design priority over continuity.

The town *surface* itself (layout, dug tiles, building mutations) persists exactly as today via the
site cache; only the *animate* layer is regenerated.

## Relationship to existing systems

- **Clock** — `nhc/hexcrawl/clock.py`, `HexWorld.advance_clock*`. Town drift adds a throttled call
  on the site turn path; it does not change overland advance.
- **AI** — `decide_action` gains read access to the current segment; `errand` becomes schedule-aware;
  `patrol` is a new branch alongside `idle`/`errand`/`thief`.
- **Sites** — `assemble_town` (and the town population path) own roster spawning and routine binding;
  `Game.enter_site` is where deterministic-by-time placement runs.
- **Registry / i18n** — new creatures via `@EntityRegistry.register_creature`; locale entries in all
  three YAML files with grammatical gender for `ca`/`es`.

See `design/town_generator.md` for the town layout/role primitives the routines anchor to.
