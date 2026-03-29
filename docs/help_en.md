# NHC — Nethack-like Crawler

A roguelike dungeon crawler with Knave rules, multilingual support,
and optional LLM-driven narrative.

## Game Modes

### Classic Mode (default)
Traditional roguelike controls. Move with arrow keys or vi keys.
Actions via single keypresses. Fast, direct, no LLM required.

### Typed Mode (--mode typed)
Type natural language commands. An LLM Game Master interprets
your actions, resolves them with Knave rules, and narrates the
outcome. Like a solo tabletop RPG session.

Press TAB to switch between modes at any time.

## Keyboard Shortcuts — Classic Mode

### Movement
  Arrow keys     Move in 4 directions
  h j k l        Vi keys (left, down, up, right)
  y u b n        Vi diagonal (NW, NE, SW, SE)
  . or 5         Wait one turn

Bumping into a creature attacks it.
Bumping into a closed door opens it.
Bumping into a chest opens it and drops its loot.

### Items & Equipment
  g or ,         Pick up item at your feet
  i              Open inventory
  a              Use an item (shows inventory menu)
  q              Quaff a potion
  e              Equip weapon, armor, shield, helmet, or ring
  d              Drop an item from inventory
  t              Throw a potion at a visible creature
  z              Zap a wand at a visible creature

### Exploration
  x              Look at distance (move cursor to examine tiles)
  s              Search for hidden traps and secret doors
  p              Pick a lock (requires lockpicks, DEX save)
  f              Force a door open (STR save, tools help)
  >              Descend stairs
  <              Ascend stairs

### Interface
  [ ]            Scroll message log up/down
  ?              Show this help screen
  TAB            Switch between classic and typed mode
  S              Save game
  L              Load game
  Q              Quit

## Keyboard Shortcuts — Typed Mode

### Text Input
  Enter          Submit command to the Game Master
  ESC            Clear current input
  Up/Down        Browse input history
  Backspace      Delete character before cursor
  Left/Right     Move cursor within text
  Home/End       Jump to start/end of line

### Shortcuts (bypass text input)
  Arrow keys     Move directly (no GM interpretation)
  h j k l        Vi movement (same as classic)
  TAB            Switch back to classic mode
  ?              Show this help screen
  [ ]            Scroll narrative log
  S              Save game
  Q              Quit

## Typed Mode Examples

  > attack the skeleton
  > pick up the potion
  > open the chest
  > I try to listen at the door
  > use the sleep scroll on the goblins
  > quaff the healing potion
  > throw the frost potion at the ogre
  > zap the wand at the goblin

## Character Stats (Knave Rules)

  STR  Strength      Melee attack, force, saves
  DEX  Dexterity     Ranged attack, dodge, AC
  CON  Constitution  Hit points, inventory slots
  INT  Intelligence  Arcane knowledge, scrolls
  WIS  Wisdom        Perception, willpower, traps
  CHA  Charisma      Social, morale, charm

  Defense = bonus + 10.  Inventory slots = CON defense.
  Max level: 10.  Each level-up raises 3 abilities by 1.

## Identification

Potions, scrolls, rings, and wands have randomized appearances
each game. They must be used to identify them:
  - Potions: quaff to identify
  - Scrolls: read/use to identify
  - Rings and wands: use Scroll of Identify or Wand of Identify

## Equipment Slots

  Weapon      One melee or ranged weapon
  Body armor  Gambeson, brigantine, half plate, full plate
  Shield      Buckler or shield (+1 AC each)
  Helmet      Leather cap or helmet (+1 AC each)
  Ring (L/R)  Two ring slots for passive magical effects

Equipped items still occupy inventory slots.

## Magic Items

### Rings (passive, always active while equipped)
  Mending, Haste, Detection, Elements, Accuracy,
  Evasion, Shadows, Protection

### Wands (zap at targets, limited charges, recharge over time)
  Firebolt, Lightning, Teleport, Poison, Slowness,
  Disintegrate, Magic Missile, Amok

## Dungeon Features

  = Chest      Bump to open, drops loot
  ^ Trap       Hidden until detected (search with 's')
  + Door       Bump to open, some are secret
  > Stairs     Descend to next level
  < Stairs     Ascend to previous level
  % Corpse     Remains of a slain creature

## Status Bar

  Line 1: Location, Depth, Turn, Level/XP, Gold, HP bar
  Line 2: Name (class), stats, equipped weapon, AC
  Line 3: Equipped armor/shield/helmet, inventory contents

## Tips

  - Pick up everything. Inventory management is key in Knave.
  - Scrolls are powerful but single-use. Save them.
  - Wands recharge slowly — don't waste charges.
  - Gold doesn't take inventory slots. Grab it all.
  - Search ('s') near walls to find secret doors and traps.
  - Bump into chests to open them for loot.
  - Rings provide passive bonuses — equip two for best effect.
  - Higher CON means more inventory slots.
  - Every 1000 XP you level up, gaining HP and +1 to 3 stats.

## Command Line Options

  --seed N        Set RNG seed for reproducibility
  --lang LANG     Language: en, ca, es
  --god           God mode (invulnerable, all items identified)
  --reset         Start a new game, ignoring autosave
  -G              Generate a random dungeon
  --mode MODE     classic or typed
  --no-narrative  Disable LLM narrative
  -v              Verbose logging
