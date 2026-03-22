# NHC — Nethack-like Crawler

A roguelike dungeon crawler with Knave rules and LLM-driven narrative.

## Game Modes

### Classic Mode (default)
Traditional roguelike controls. Move with arrow keys or vi keys.
Actions via single keypresses. Fast, direct, no LLM required.

### Typed Mode (--mode typed)
Type natural language intents. An LLM Game Master interprets your
actions, resolves them with Knave rules, and narrates the outcome.
Feels like a solo TTRPG session.

Press TAB to switch between modes at any time during gameplay.

## Keyboard Shortcuts — Classic Mode

### Movement
  Arrow keys     Move in 4 directions
  h j k l        Vi keys (left, down, up, right)
  y u b n        Vi diagonal (NW, NE, SW, SE)
  . or 5         Wait one turn

### Actions
  g or ,         Pick up item at your feet
  i              Open inventory
  a              Use an item (shows inventory menu)
  >              Descend stairs
  x              Look around (inspect tile)
  s              Search for hidden traps and secret doors

### Interface
  [ ]            Scroll message log up/down
  ?              Show this help screen
  TAB            Switch between classic and typed mode
  S              Save game
  L              Load game
  q              Quit

## Keyboard Shortcuts — Typed Mode

### Text Input
  Enter          Submit typed intent to the Game Master
  ESC            Clear current input
  Up/Down        Browse input history
  Backspace      Delete character before cursor
  Left/Right     Move cursor
  Home/End       Jump to start/end of line

### Shortcuts (bypass text input)
  Arrow keys     Move directly (no GM interpretation)
  h j k l        Vi movement (same as classic)
  TAB            Switch back to classic mode
  ?              Show this help screen
  [ ]            Scroll narrative log
  S              Save game
  q              Quit

## Typed Mode Examples

  > I draw my sword and move east
  > attack the skeleton
  > pick up the potion
  > I try to listen at the door
  > use the sleep scroll on the goblins
  > look around carefully

## Character Stats (Knave Rules)

  STR  Strength      Melee attack, force
  DEX  Dexterity     Ranged attack, dodge, AC
  CON  Constitution  Hit points, inventory slots
  INT  Intelligence  Arcane knowledge
  WIS  Wisdom        Perception, willpower
  CHA  Charisma      Social, morale

  Defense = bonus + 10.  Inventory slots = CON defense.

## Status Bar

  Line 1: Location, Depth, Turn, Level/XP, Gold, HP bar
  Line 2: Name (background), ability scores, weapon, AC
  Line 3: Inventory contents

## Tips

  - Pick up everything. Inventory management is key in Knave.
  - Scrolls are powerful but single-use. Save them for tough fights.
  - Gold doesn't take inventory slots. Grab it all.
  - In typed mode, try creative actions — the GM can resolve
    ability checks for things like bluffing or searching.
  - Press TAB to quickly switch to classic mode for movement,
    then TAB back to typed mode for complex actions.
