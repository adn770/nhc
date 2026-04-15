# NHC — Nethack-like Crawler

A roguelike dungeon crawler with Knave rules, multilingual support,
and optional LLM-driven narrative. You descend through procedurally
generated levels, fight creatures, loot treasure, recruit henchmen,
identify magic items, and try to stay alive.

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
  Arrow keys        Move in 4 directions
  h j k l           Vi keys (left, down, up, right)
  y u b n           Vi diagonal (NW, NE, SW, SE)
  . or 5            Wait one turn

Bumping a hostile creature attacks it.
Bumping a closed door opens it.
Bumping a hired henchman swaps positions with you.
Bumping a chest, barrel or crate opens it and drops its loot.
Bumping a merchant or priest opens their shop/service menu.
Bumping an unhired adventurer opens the encounter menu.

### Items & Equipment
  g or ,            Pick up item at your feet
  i                 Open inventory
  a                 Use an item (shows inventory menu)
  q                 Quaff a potion
  e                 Equip weapon, armor, shield, helmet, or ring
  d                 Drop an item from inventory
  t                 Throw a potion at a visible creature
  z                 Zap a wand at a visible creature

### Exploration
  :                 Farlook — move cursor to examine tiles
  s                 Search for hidden traps and secret doors
  p                 Pick a lock (requires lockpicks, DEX save)
  f                 Force a door open (STR save, tools help)
  c                 Close an adjacent open door
  D                 Dig a wall or floor (requires digging tool)
  >                 Descend stairs
  <                 Ascend stairs

### Party
  G                 Give an item to a hired henchman
  P                 Dismiss a henchman from your party

### Interface
  [ ]               Scroll message log up/down
  ?                 Show this help screen
  TAB               Switch between classic and typed mode
  Q                 Quit

## Keyboard Shortcuts — Typed Mode

### Text Input
  Enter             Submit command to the Game Master
  ESC               Clear current input
  Up/Down           Browse input history
  Backspace         Delete character before cursor
  Left/Right        Move cursor within text
  Home/End          Jump to start/end of line

### Shortcuts (bypass text input)
  Arrow keys        Move directly (no GM interpretation)
  h j k l           Vi movement (same as classic)
  TAB               Switch back to classic mode
  ?                 Show this help screen
  [ ]               Scroll narrative log
  Q                 Quit

## Typed Mode Examples

  > attack the skeleton
  > pick up the potion
  > open the chest
  > I try to listen at the door
  > use the sleep scroll on the goblins
  > quaff the healing potion
  > throw the frost potion at the ogre
  > zap the wand at the goblin
  > give the crowbar to my henchman

## Web Client Extras

The browser client adds a few features not available in the terminal:

  Mouse click       Move towards / act on clicked tile
  Right-click       Context menu on an inventory item (Use, Quaff,
                    Equip, Throw, Give, Drop)
  Farlook button    Toggle single-tile inspection; right-click for
                    Autolook mode (continuous inspection while moving)
  Dig button        Toggle Autodig — walk into walls to tunnel through
                    them using the equipped digging tool
  TTS checkbox      Read game messages aloud via Piper text-to-speech
  Leaderboard       Completed runs are ranked (god-mode runs excluded)

## Character Stats (Knave Rules)

  STR  Strength      Melee attack, force, saves
  DEX  Dexterity     Ranged attack, dodge, AC
  CON  Constitution  Hit points, inventory slots
  INT  Intelligence  Arcane knowledge, scrolls
  WIS  Wisdom        Perception, willpower, traps
  CHA  Charisma      Social, morale, charm

  Defense = bonus + 10.  Inventory slots = CON defense.
  Level 1 starts with maximum HP (8).
  Max level: 10.  Each level-up raises the 3 lowest abilities by 1.
  1000 XP per level. Creatures award XP equal to their max HP × 5.

## Equipment Slots

  Weapon            One melee or ranged weapon
  Body armor        Gambeson, brigandine, chain, half plate,
                    full plate
  Shield            Buckler or shield (+1 AC each)
  Helmet            Leather cap or helmet (+1 AC each)
  Ring (L/R)        Two ring slots for passive magical effects

Equipped items still occupy inventory slots.

## Legend of Symbols

### Terrain & Dungeon Features

  .   Floor               ,   Grass
  #   Corridor / dug      ~   Water or lava
  -   Wall (box-drawing in-game)
  +   Closed door         '   Open door
  <   Stairs up           >   Stairs down
  ^   Trap (once detected)
  =   Chest               0   Barrel              #   Crate
  ◎   Buried treasure marker (cyan, after digging or detection)

Secret doors look like walls until found with search.
Detected items and magic glow briefly, then fade.

### Items

  !   Potion              ?   Scroll
  =   Ring                /   Wand or arrow
  )   Weapon              [   Body armor
  *   Gem or worthless glass
  (   Tool, food, key, lockpick, lamp, holy symbol, etc.
  $   Gold pile           %   Corpse

Potions, scrolls, rings, wands and gems show a random appearance
(colors, labels, gem type) until identified — appearances reshuffle
each game.

### Creatures

Player and friendly NPCs share the `@` glyph but differ by color:

  @   Player        (blue outline in web client)
  @   Henchman      (cyan)
  @   Merchant      (green)
  @   Priest        (bright white)
  @   Bandit        (yellow, hostile)

Most other creatures take a single letter. A few examples grouped
by family (the full bestiary is larger):

  Humanoids / goblinoids
    g goblin   h hobgoblin   k kobold   o orc     O ogre
    G gnoll    f frogman     L lizardman           n snakeman
  Beasts & canines
    b bat      r rat         w wolf     d dire wolf
    c bear     U warg        W werewolf / winter wolf
  Reptiles & serpents
    l lizard   S snake       D dragon lizard        F giant frog
  Undead
    s skeleton Z zombie      M mummy    W wight / wraith
    S spectre  g ghoul
  Vermin, insects & arachnids
    s spider   i insect swarm  a fire beetle
    L cave locust  S giant scorpion  c giant centipede
  Oozes & plants
    P black pudding   j ochre jelly   o gray ooze
    f fungus / carnivorous flower     m yellow mold
  Exotic & chaos
    T troll (regenerates)    $ mimic (disguised as chest/gold)
    ! shrieker (alerts nearby creatures)
    C centaur  H harpy       V wyvern    I invisible stalker
    A animated armor         G gargoyle  B basilisk (gaze)

Rule of thumb: lower-case = smaller, upper-case = larger or tougher.
Troll regenerates 3 HP per turn; mimics and shriekers disguise
themselves as items — surprises are part of the game.

## Magic Items

### Potions (14)
  Healing, Strength, Speed, Frost, Invisibility, Levitation,
  Liquid Flame, Mind Vision, Paralytic Gas, Purification,
  Confusion, Blindness, Acid, Sickness.

Some potions are better thrown at enemies than drunk.
Quaffing any potion restores a small amount of hunger.

### Scrolls
Detection (fade-in glow, reveal things for a while):
  Detect Magic, Detect Evil, Detect Gold, Detect Food,
  Detect Gems, Detect Invisibility, Find Traps, Reveal Map.
Offensive / status:
  Lightning, Fireball, Magic Missile, Sleep, Hold Person,
  Web, Charm Person, Phantasmal Force, Dispel Magic.
Defensive / buff:
  Bless, Shield, Haste, Cure Wounds, Mirror Image,
  Invisibility, Protection from Evil, Protection from
  Missiles, Resist Fire, Resist Cold, Silence, Levitate, Fly.
Utility:
  Identify, Charging, Teleportation, Enchant Weapon,
  Enchant Armor, Clairvoyance, Infravision, Water Breathing,
  Charm Snakes.

### Rings (passive, active while equipped)
  Mending, Haste, Detection, Elements, Accuracy,
  Evasion, Shadows, Protection.

### Wands (zap at targets, limited charges, recharge over time)
  Firebolt, Lightning, Cold, Magic Missile, Disintegrate,
  Teleport, Poison, Slowness, Amok, Opening, Locking,
  Digging, Cancellation, Death.

### Gems & Glass
Real gems (ruby, sapphire, emerald, diamond, amethyst, topaz,
opal, garnet) sell for gold. Worthless glass looks the same
until identified — a Scroll of Identify or the appraisal eye
of a merchant tells them apart.

## Identification

Potions, scrolls, rings, wands and gems have randomized
appearances each game. Identify them by:
  - Potions: quaff to identify (or throw a known type)
  - Scrolls: read/use to identify
  - Rings and wands: equip/zap, or use Scroll/Wand of Identify
  - Gems: use Scroll of Identify, or sell to a merchant

## Dungeon Features & Special Rooms

  Temple (2+)       Guaranteed on depth 2. A priest offers heal,
                    remove curse, and bless services, plus holy
                    goods. Prices scale with depth.
  Shops             A merchant sells items and buys loot at 50%
                    value. Bump to trade.
  Lairs (3+)        1–3 connected rooms of the same humanoid
                    species. Surrounding tiles hide reactivatable
                    traps.
  Zoos (5+)         Rare rooms packed with creatures.
  Vermin nests      Rooms full of rats, bats, or insects.
  Vaults            Hidden treasure caches with piles of gold.
  Caves             Organic layouts with no doors but more pits
                    and trapdoors.

## Traps

Traps are hidden until detected. Use `s` (search) adjacent to
a suspected tile, rely on Ring of Detection, or cast Find Traps.
Traps include: pit, trapdoor, arrow, dart, falling stone, fire,
poison, paralysis, alarm, teleport, summoning, gripping, spores.
Some traps around lairs reactivate after 40 turns.

## Doors

  Closed            Bump to open (only humanoid creatures can).
  Locked            Use `p` to pick (DEX save, may break a lockpick)
                    or `f` to force (STR save, may hurt you).
  Force tools       A crowbar absorbs rebound damage and lowers DC;
                    a weapon lowers DC a little and may chip.
  Secret            Look like walls. Find with `s`.
  Caves             No doors — just open passages.

## Digging & Buried Treasure

A digging tool (shovel, pick, pickaxe, or mattock) lets you tunnel.
One is guaranteed to appear on depths 1–5.

  Walls             Any digging tool. STR save DC 12 minus tool
                    bonus.
  Floors            Shovel only. May reveal buried items (shown
                    as ◎). 1 in 20 (plus 1 per STR bonus) chance
                    to dig through and fall to the next floor for
                    2d6 damage. Digging the same tile twice
                    guarantees a fall.
  Picks             Striking the floor with a pick, pickaxe or
                    mattock can rebound for 1d2 damage on a
                    natural 1.

In the web client, right-click the Dig button to toggle Autodig
and tunnel by simply moving into walls.

## Henchmen / Party

  Recruiting        Bump an unhired adventurer to open the
                    encounter menu. Hiring costs 100 gold × their
                    level.
  Party size        Up to two henchmen at once.
  Behaviour         They fight, heal themselves with potions, pick
                    up loot, avoid visible traps, and follow you
                    between rooms and down stairs.
  Giving            Press `G` (or use the context menu) to hand
                    over items. Their AI picks smart equipment to
                    wear.
  Swapping          Bump a henchman to trade places.
  Dismissing        Press `P` to release a henchman.
  Death             Reported in the log. Henchmen earn half XP.

## Hunger & Food

A hunger clock runs as you explore. Eat food (`a` then choose
a ration, bread, cheese, apple, mushroom, dried meat…) before
you starve. Mushrooms can heal, poison or confuse. Quaffing a
potion gives a small nutrition bonus, but never enough to live on.

## Combat Basics

  Melee             d20 + STR bonus + weapon magic vs target AC.
                    Natural 20 = max damage. Natural 1 = auto miss.
                    Damage = weapon die + STR bonus + magic (min 1).
  Ranged            Throw (`t`), zap (`z`), or shoot (via wielded
                    bow).
  Defense           AC = 10 + DEX bonus + armor/shield/helmet/ring.
  Morale            Enemies roll morale on first seeing you and
                    again when reduced to half HP; cowards flee.
  Henchmen          Add their weapons and spells to your damage
                    output.

## Status Bar

  Line 1            Location, Depth, Turn, Level/XP, Gold, HP bar
  Line 2            Name (class), stats, equipped weapon, AC
  Line 3            Equipped armor/shield/helmet, inventory contents

## How to Play — A Short Guide

1. **Explore cautiously.** Step into each new room once, check
   what's inside, and back off if the odds are bad.
2. **Pick up almost everything.** Gold is free; other items
   cost inventory slots but most are worth the room.
3. **Identify safely.** Quaff unknown potions when at full HP.
   Read unknown scrolls in empty rooms — some summon or teleport.
   Never identify in a lair.
4. **Use consumables.** Scrolls and wand charges don't carry
   over if you die. Use them on tough fights, not easy ones.
5. **Search often.** Secret doors and buried treasure hide in
   walls and floors. Pressing `s` a few times costs little.
6. **Read the room.** A packed room is probably a zoo, a
   single big room of kin is a lair, a perfect grid with a
   merchant is a shop, tile decorations mark temples.
7. **Level up smart.** Each level raises your three lowest
   stats by 1. Don't try to dump everything into STR — CON
   gives slots, DEX gives AC, WIS resists magic.
8. **Manage hunger.** Don't waste corridors idling. Carry at
   least two rations when descending.

## Tactical Tips

- **Corridors funnel enemies** — fight groups in 1-wide
  chokepoints so only one enemy can reach you.
- **Close doors behind you** with `c` to block pursuit and
  gain a free first hit when something re-opens it.
- **Throw potions at enemies** — Frost, Liquid Flame,
  Paralytic Gas, Acid, Confusion and Blindness all debuff
  on impact.
- **Wands shine vs strong foes** — save Magic Missile for
  hard-to-hit targets; it never misses.
- **Rings of Mending + Detection** carry most runs. Equip
  both ring slots whenever possible.
- **Crowbars make force-door safe** — they absorb rebound
  damage and lower the DC.
- **Trolls regenerate** — burn them (Liquid Flame, Wand of
  Firebolt, Scroll of Fireball) to stop the regen.
- **Mimics pretend to be chests** and **shriekers look like
  potions** — examine (`:`) something that seems out of place.
- **Temples are a reset button** — a priest's heal and remove
  curse can save a dying run for a pile of gold.
- **Hire early.** A depth-1 adventurer is cheap, tanks hits,
  and heals himself. Give him your spare crowbar.
- **Dig sparingly.** Floor digging saves time but can dump
  you into a pit fight at low HP — heal first.
- **Don't ascend for fun.** Going back up kills XP pacing and
  only depth-1 ascent stairs exist.

## Saving

The game autosaves after each turn — there is no manual save
key. Autosaves are signed with HMAC to detect tampering. Use
`--reset` to start fresh and ignore the current autosave.

## Command Line Options

  --seed N          Set RNG seed for reproducibility
  --lang LANG       Language: en, ca, es
  --god             God mode (invulnerable, all items identified)
  --reset           Start a new game, ignoring autosave
  -G                Generate a random dungeon
  --mode MODE       classic or typed
  --no-narrative    Disable LLM narrative
  -v                Verbose logging
