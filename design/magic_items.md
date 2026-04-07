# Magic Items — Rings and Wands

> **Status**: Implemented. All phases complete. Wands expanded
> from 8 to 14 types beyond original design.

## 1. Overview

Rings and wands add persistent and rechargeable magical effects to the
game.  Rings provide passive buffs while worn.  Wands are targeted
magical weapons with limited charges that recharge over time.  Both
use the existing identification system — unidentified rings show gem
names, unidentified wands show wood types.

---

## 2. Rings

### 2.1 Mechanics

- **Equip slots**: 2 ring slots on the Equipment component.  The
  player can wear up to 2 rings simultaneously.
- **Passive effect**: while equipped, the ring's buff is active.
  No activation needed — just equip/unequip with `e`.
- **Identification**: unidentified rings show gem appearance
  ("a diamond ring", "un anell de diamant").  Identified after
  wearing for 100 turns or via Scroll of Detect Magic.
- **No charges**: rings work indefinitely while worn.
- **Inventory cost**: 1 slot each (Knave rules).

### 2.2 Ring Types (8)

| ID | Name (en) | Effect | Implementation |
|----|-----------|--------|----------------|
| `ring_mending` | Ring of Mending | Regenerate 1 HP every 5 turns | Tick in game loop |
| `ring_haste` | Ring of Haste | Double movement speed | Extra move per turn |
| `ring_detection` | Ring of Detection | Auto-reveal traps and secret doors in FOV | Check in `_update_fov` |
| `ring_elements` | Ring of Elements | Halve fire and cold damage | Modify in damage resolution |
| `ring_accuracy` | Ring of Accuracy | +2 to melee attack rolls | Modify in combat |
| `ring_evasion` | Ring of Evasion | +2 to AC defense | Modify in `_gather_stats` |
| `ring_shadows` | Ring of Shadows | Creatures detect player at half range | Modify AI chase radius |
| `ring_protection` | Ring of Protection | +1 AC defense | Modify in `_gather_stats` |

### 2.3 Ring Appearances (shuffled per game)

| Appearance | i18n key | Glyph color |
|-----------|----------|-------------|
| Diamond | `diamond` | bright_white |
| Ruby | `ruby` | bright_red |
| Emerald | `emerald` | bright_green |
| Sapphire | `sapphire` | bright_blue |
| Opal | `opal` | bright_cyan |
| Amethyst | `amethyst` | magenta |
| Topaz | `topaz` | bright_yellow |
| Onyx | `onyx` | bright_black |

### 2.4 Equipment Component Changes

```python
@dataclass
class Equipment:
    weapon: int | None = None
    armor: int | None = None
    shield: int | None = None
    helmet: int | None = None
    ring_left: int | None = None   # NEW
    ring_right: int | None = None  # NEW
```

### 2.5 Ring Component

```python
@dataclass
class Ring:
    """Passive magical ring."""
    effect: str = ""  # "mending", "haste", "detection", etc.
```

### 2.6 Ring Effect Resolution

Ring effects are checked at specific points in the game loop:

| Effect | Check point | How |
|--------|------------|-----|
| Mending | End of turn tick | If equipped, heal 1 HP every 5 turns |
| Haste | Player action | Grant extra move action |
| Detection | `_update_fov` | Reveal traps/secrets on visible tiles |
| Elements | Damage resolution | Halve fire/cold damage before applying |
| Accuracy | `resolve_melee_attack` | Add +2 to attack roll |
| Evasion | AC calculation | Add +2 to armor defense |
| Shadows | AI `decide_action` | Halve chase radius |
| Protection | AC calculation | Add +1 to armor defense |

---

## 3. Wands

### 3.1 Mechanics

- **Charges**: each wand starts with 2d10 charges (rolled at creation).
  Using the wand costs 1 charge.
- **Recharge**: wands regain 1 charge every 20 turns while in
  inventory (not necessarily equipped).  Max charges = initial roll.
- **Targeting**: player selects a visible creature (same menu as
  throw).  Some wands (blink, regrowth) target a tile instead.
- **Identification**: unidentified wands show wood type ("a holly
  wand", "una vareta de grèvol").  Identified on first use.
- **Equip**: wands don't need equipping — use directly from inventory
  with `a` (use item) or `z` (new dedicated zap key).
- **Inventory cost**: 1 slot each.

### 3.2 Wand Types (14)

| ID | Name (en) | Effect | Dice |
|----|-----------|--------|------|
| `wand_firebolt` | Wand of Firebolt | Fire damage to target | 2d6 |
| `wand_lightning` | Wand of Lightning | Lightning damage | 3d4 |
| `wand_teleport` | Wand of Teleportation | Teleport target to random tile | — |
| `wand_poison` | Wand of Poison | Apply poison (2 dmg/turn, 5 turns) | — |
| `wand_slowness` | Wand of Slowness | Halve target speed for 8 turns | — |
| `wand_disintegrate` | Wand of Disintegration | Piercing damage through line | 3d6 |
| `wand_magic_missile` | Wand of Magic Missile | Force damage, never misses | 1d6+1 |
| `wand_amok` | Wand of Amok | Confuse target for 6 turns | — |
| `wand_cancellation` | Wand of Cancellation | Strip all magical effects | — |
| `wand_cold` | Wand of Cold | Cold damage to target | 2d6 |
| `wand_death` | Wand of Death | Instant kill (very rare, 1d2 charges) | — |
| `wand_digging` | Wand of Digging | Destroy wall tiles in a line | — |
| `wand_locking` | Wand of Locking | Lock a door | — |
| `wand_opening` | Wand of Opening | Unlock a locked door | — |

### 3.3 Wand Appearances (14, shuffled per game)

| Appearance | i18n key | Glyph color |
|-----------|----------|-------------|
| Holly | `holly` | green |
| Yew | `yew` | yellow |
| Ebony | `ebony` | bright_black |
| Cherry | `cherry` | bright_red |
| Teak | `teak` | yellow |
| Rowan | `rowan` | bright_green |
| Willow | `willow` | bright_cyan |
| Oak | `oak` | bright_yellow |
| Birch | `birch` | bright_white |
| Maple | `maple` | bright_red |
| Ash | `ash` | white |
| Cedar | `cedar` | yellow |
| Elm | `elm` | green |
| Pine | `pine` | bright_green |

### 3.4 Wand Component

```python
@dataclass
class Wand:
    """Rechargeable magical device."""
    effect: str = ""          # "firebolt", "lightning", etc.
    charges: int = 0          # current charges
    max_charges: int = 0      # maximum charges
    recharge_timer: int = 0   # turns until next charge gained
```

### 3.5 Wand Recharge

In the game loop, after status effect ticks:
```python
def _tick_wand_recharge(self):
    inv = self.world.get_component(self.player_id, "Inventory")
    if not inv:
        return
    for item_id in inv.slots:
        wand = self.world.get_component(item_id, "Wand")
        if wand and wand.charges < wand.max_charges:
            wand.recharge_timer -= 1
            if wand.recharge_timer <= 0:
                wand.charges += 1
                wand.recharge_timer = 20  # turns per charge
```

### 3.6 Zap Action

New `z` key for zapping wands (like `q` for quaff, `t` for throw):

1. Show inventory filtered by `Wand` component (show charges)
2. Select a wand
3. If wand has 0 charges → "The wand fizzles" message
4. Select a visible target
5. Apply effect, decrement charge, identify wand type

---

## 4. Identification

### 4.1 Unified System

Extend `ItemKnowledge` (nhc/rules/identification.py) with ring and
wand IDs + appearances:

```python
RING_IDS = [
    "ring_mending", "ring_haste", "ring_detection",
    "ring_elements", "ring_accuracy", "ring_evasion",
    "ring_shadows", "ring_protection",
]

RING_APPEARANCES = [
    ("diamond", "bright_white"),
    ("ruby", "bright_red"),
    ...
]

WAND_IDS = [
    "wand_firebolt", "wand_lightning", "wand_teleport",
    ...
]

WAND_APPEARANCES = [
    ("holly", "green"),
    ("yew", "yellow"),
    ...
]
```

The `display_name()` method routes based on prefix:
- `ring_*` → `ring_appearance.{key}`
- `wand_*` → `wand_appearance.{key}`
- `scroll_*` → `scroll_appearance.{key}`
- `potion_*` / `potion_healing` → `potion_appearance.{key}`

### 4.2 Identification Triggers

| Item type | Identified when |
|-----------|----------------|
| Potion | Quaffed or thrown |
| Scroll | Read (used) |
| Ring | Worn for 100 turns, or Detect Magic scroll |
| Wand | Zapped (first use) |

---

## 5. Glyph and Display

| Item type | Glyph | Example display |
|-----------|-------|----------------|
| Ring | `=` | `=` bright_red (ruby) |
| Wand | `/` | `/` green (holly) |

### 5.1 Inventory Display

Wands show charges: `Wand of Firebolt (3/7)`

Rings show `[E]` when equipped (same as weapons/armor).

### 5.2 Status Bar

Equipped rings shown on line 2 after armor:
```
Arnau (mercenari) │ FOR:+2 ... │ ⚔️ Espasa │ Brigantina │ 💍 Diamant │ 💍 Robí │ AC 15
```

---

## 6. Loot Distribution

| Depth | Ring chance | Wand chance |
|-------|-----------|-------------|
| 1-2 | 2% per item | 3% per item |
| 3-4 | 4% per item | 5% per item |
| 5+ | 6% per item | 7% per item |

Rings and wands are rare — finding one is significant.

Special rooms:
- **Treasury**: 15% chance to contain a ring
- **Library**: 20% chance to contain a wand

---

## 7. Implementation Phases

All phases are complete.

### Phase 1 — Components and Factories (done)

1. Ring and Wand dataclasses in components.py
2. Equipment expanded with ring_left, ring_right
3. 8 ring + 14 wand factory files
4. i18n entries in all 3 locales
5. Ring/wand appearances in identification.py

### Phase 2 — Equip and Use (done)

7. EquipAction handles ring slots
8. `z` key for zap (wand targeting)
9. ZapAction in nhc/core/actions/_ranged.py
10. Wand effect handlers implemented

### Phase 3 — Passive Effects (done)

11. Ring effects tick in game loop
12. Ring modifiers in combat resolution
13. Shadows ring modifies AI chase radius
14. Wand recharge ticking
15. Wand charge display in inventory

### Phase 4 — Loot and Balance (done)

16. Rings/wands in populator item pools (tier 3+)
17. Added to room painters (treasury, library)

### Remaining test gaps

- Ring passive effects (mending HP regen, detection auto-reveal)
  need more thorough test coverage.

---

## 8. Key Files

| File | Changes |
|------|---------|
| `nhc/entities/components.py` | Ring, Wand dataclasses; Equipment ring slots |
| `nhc/entities/items/ring_*.py` | 8 ring factory files |
| `nhc/entities/items/wand_*.py` | 14 wand factory files |
| `nhc/rules/identification.py` | RING_IDS, WAND_IDS, appearances |
| `nhc/core/actions.py` | ZapAction, ring equip handling |
| `nhc/core/game.py` | Ring effect ticks, wand recharge |
| `nhc/rendering/terminal/input.py` | z key for zap |
| `nhc/rendering/terminal/panels.py` | Ring display on line 2 |
| `nhc/dungeon/populator.py` | Ring/wand in loot pools |
| `nhc/i18n/locales/*.yaml` | All translations |
