# View hierarchy

NHC renders the game through **five discrete views**. A "view" is
a player-facing rendering mode with its own tile layout, its own
toolbar action set, its own keyboard bindings, and its own
remembered zoom level. This document is the single source of
truth for the vocabulary and the classification rules; every
piece of the codebase that reasons about "what's the player
looking at right now?" should funnel through
:func:`Game.current_view`.

## The five views

| name | what it shows | main gameplay signals |
|------|---------------|-----------------------|
| `hex` | the overland hex crawl map | macro hex movement, day-clock ticks, `hex_explore`, `hex_rest` |
| `flower` | the 7-hex sub-hex "flower" around a macro hex | `hex_enter`, `flower_search`, `flower_forage`, `flower_rest`, `flower_exit` |
| `site` | the outdoor layer of a named location reached from the flower — town, keep, mansion, tower, mage_residence, temple, cottage, ruin, farm, plus the sub-hex variants (wayside well/signpost, clearing, sacred shrine/cairn, animal den, graveyard, campsite, orchard, sub-hex farm) | npc encounters, site-edge exit, `flower_exit` (via **L**), building entry doors |
| `structure` | the interior of a building on a site | shop / temple / inn interactions, stairs up / down, cross-building interior doors |
| `dungeon` | a procedural underground level (standalone or descent from a site) | combat, stairs, dig, traps, item pickups |

`hex` and `flower` each have their own DOM container
(`#hex-container`, `#flower-container`). `site`, `structure`
and `dungeon` share `#map-container` -- they're structurally the
same kind of tile layer but remain distinct views for UX
purposes.

## Classification rules

Implemented by :func:`Game.current_view`. Applied in order:

1. If :attr:`world_type` is ``WorldType.HEXCRAWL`` and
   :attr:`level` is ``None``:
   - If ``hex_world.exploring_sub_hex`` is not ``None`` →
     **`flower`**.
   - Else → **`hex`**.
2. If :attr:`level` is ``None`` (dungeon-only game) → **`hex`**.
3. If ``level.building_id`` is not ``None`` → **`structure`**.
4. If :attr:`_active_site` is not ``None`` and ``level`` is the
   site surface → **`site`**. M5 collapsed the unified site
   path (every site, sub-hex or macro, parks itself on
   ``_active_site``) so the classifier no longer needs a
   separate sub-hex branch.
5. Otherwise → **`dungeon`** (covers both procedural dungeons
   reached from a building's descent and standalone
   dungeon-only-mode levels).

The rules intentionally let `dungeon` absorb the descent case: a
dungeon reached through a building still plays as a dungeon
(combat + stairs + traps) -- ``building_id`` gates `structure`,
not "did I enter from a site".

## How the five views flow

```
             +---------------------+
             |        hex          |
             |  (overland crawl)   |
             +----^--------|-------+
                  |        | hex_enter (macro hex)
      flower_exit |        |
                  |        v
             +----|----------------+
             |      flower         |
             |  (sub-hex preview)  |
             +----^--------|-------+
                  |        | hex_enter (site/feature)
        leave-site|        |
      (site edge) |        v
                  |   +---------+     building door
                  +---|  site   |<------+
                      +----|----+      |
                           |           |
                 enter     |           v
                 building  |    +-----------+
                           +--->| structure |
                                +----|------+
                                     |
                            stairs_down / descent
                                     v
                                +----------+
                                | dungeon  |
                                +----------+
```

## Per-view control gates

| intent | hex | flower | site | structure | dungeon |
|--------|-----|--------|------|-----------|---------|
| move (orthogonal) | ✓ (macro step) | ✓ (sub-hex step) | ✓ (tile step) | ✓ | ✓ |
| `hex_explore` | ✓ | | | | |
| `hex_rest` | ✓ | | | | |
| `hex_enter` | ✓ | ✓ | | | |
| `flower_exit` | | ✓ (toolbar) | ✓ (**L**) | | |
| `flower_search` | | ✓ | | | |
| `flower_forage` | | ✓ | | | |
| `flower_rest` | | ✓ | | | |
| `pickup` | | | ✓ | ✓ | ✓ |
| `inventory` | ✓ | ✓ | ✓ | ✓ | ✓ |
| stairs up / down | | | | ✓ | ✓ |
| `dig` | | | | | ✓ |
| `close_door`, `force_door`, `pick_lock` | | | ✓ | ✓ | ✓ |

Anything outside this table is not wired.

## Why this matters

Before this refactor the three tile-layer views (`site`,
`structure`, `dungeon`) were lumped into one "map" mode on the
client: a single toolbar with the full combat action set, one
zoom preference, one key binding table. As a result:

- The "Leave (**L**)" action was available inside buildings and
  dungeons where it has no meaning.
- Zooming the dungeon to 1.5× also zoomed the town street.
- Toolbar icons unrelated to the player's situation (dig icon
  in a shop) added visual noise.

Splitting into five named views gives the renderer, the toolbar
builder, the input router, and the zoom-memory map a single
shared vocabulary to branch on. Future UI work anchors to this
table.

## References

- Helper: :func:`nhc.core.game.Game.current_view`
- WS message types: ``state_hex`` / ``state_flower`` /
  ``state_site`` / ``state_structure`` / ``state_dungeon``.
- Client dispatch: ``GameMap.setActiveView(view)`` in
  ``nhc/web/static/js/map.js``.
- Per-view zoom memory: ``GameMap._zoomByView`` (persisted to
  ``localStorage`` key ``nhc.zoom.byView.v2``).
- Sites subsystem (the substance behind the ``site`` view):
  see ``design/sites.md`` for the unified dispatcher, tier
  scheme, and cache contract.
