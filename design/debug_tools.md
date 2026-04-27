# Debug Tools

## Overview

NHC includes a suite of debugging and development tools designed to
support gameplay testing, visual inspection, and AI-assisted analysis.
The toolkit comprises:

- **God mode** for invulnerable gameplay testing with full item
  identification and map reveal.
- **Topic-based debug logging** with 24+ filterable topics and
  colored, timestamped output.
- **Web debug panel** for toggling render layers, overlays, and
  exporting game state.
- **Export endpoints** for dumping game state, layer state, and map
  SVG to timestamped files.
- **MCP debug server** exposing 17 tools for AI-assisted game state
  analysis via Claude Code.

## God Mode

### Activation

- CLI flag: `--god`
- Config file: `god=true` in `~/.nhcrc`

### Features

- **Invulnerability**: HP restored to maximum each turn
  (implemented in `game.py`).
- **Full identification**: all potions, scrolls, rings, and wands
  are pre-identified on game start.
- **Map reveal**: press `M` to reveal the entire dungeon
  temporarily.
- **Debug panel**: gear icon appears in the web toolbar, opening a
  tabbed floating panel for layer toggles and data export.
- **Export endpoints**: REST endpoints for dumping game state, layer
  state, and map SVG.

## Debug Logging

Source: `nhc/utils/log.py`

### Architecture

| Class / Function | Purpose                                       |
|------------------|-----------------------------------------------|
| `TopicFilter`    | Filters DEBUG logs by topic; INFO+ always pass |
| `GameFormatter`  | Aligned output with elapsed time, topic, colors|
| `setup_logging()`| Configures root logger with file + console     |

**Log file location** (in order of precedence):
1. `debug/nhc.log`
2. `$NHC_DATA_DIR/nhc.log`
3. `/tmp/nhc.log` (fallback)

**Output format**: `[HH:MM:SS] LEVEL:TOPIC: message`

### Debug Topics (24+)

Topics are organized by subsystem:

| Subsystem | Topics                                       |
|-----------|----------------------------------------------|
| Core      | game, ecs, action, event, save               |
| Rules     | combat, xp, loot, magic                      |
| AI        | ai, pathfind, tactics                        |
| Dungeon   | dungeon, loader, populate                    |
| Web       | webapp, ws, webclient, sessions, autosave    |
| Other     | render, narrative, llm, registry, fov, rng,  |
|           | config, i18n                                 |

### CLI Flags

| Flag                     | Effect                              |
|--------------------------|-------------------------------------|
| `-v` / `--verbose`       | Enable DEBUG for all topics         |
| `--debug-topics TOPICS`  | Comma-separated topic filter        |
| `--list-topics`          | List available topics and exit      |
| `--log-file PATH`        | Custom log file path                |

## Web Debug Panel

Source: `nhc/web/static/js/debug.js`

Only available in god mode. Accessed via the gear icon in the web
toolbar. The panel is a tabbed floating window with Layers, Map Gen,
and Export tabs, plus one extra tab per hired henchman.

### Layers Tab

**Visibility toggles** for render layers:
- Floor SVG
- Door Canvas
- Entity Canvas
- Hatch Canvas
- Fog Canvas

**Debug overlays**:
- Room Labels: `#N shape WxH`
- Door Labels: `DN type`
- Corridor Labels: `CN`
- Tile Coordinates: `x,y`

### Export Tab

- Individual export buttons: Game State, Layer State, Map SVG.
- "Export All" button to download all three at once.
- Files are saved to `debug/exports/` with timestamped filenames.

### Henchman Tabs

One tab per hired henchman is appended on panel open. Each shows:
- Header with name, level, and XP progress.
- Vitals (HP / max HP).
- Abilities grid with the six Knave ability bonuses.
- Equipment slots (weapon, armor, shield, helmet, ring L/R) with
  damage / AC / magic bonus annotations.
- Inventory list with slot usage.

Data is fetched from `GET /api/game/{sid}/henchmen` (god mode only).

## Export Endpoints

Source: `nhc/web/app.py`

All export endpoints require god mode. Files are written to
`debug/exports/` with timestamped names.

### POST /api/game/{sid}/export/game_state

Output: `debug/exports/game_state_YYYYMMDD_HHMMSS.json`

Contents:
- `turn`, `seed`, `player_id`
- `stats`: char_name, hp, level_name, depth, AC, abilities, items
- `entities`: id, x, y, glyph, color, hp, max_hp, name
- `level`: width, height, tiles, rooms, corridors
- `ecs`: full entity component state

### POST /api/game/{sid}/export/layer_state

Output: `debug/exports/layer_state_YYYYMMDD_HHMMSS.json`

Contents:
- `turn`, `timestamp`
- `fov`: visible tile coordinates
- `explored`: explored tile coordinates
- `doors`: positions and states
- `debug`: rooms, corridors, doors with indices

### POST /api/game/{sid}/export/map_svg

Output: `debug/exports/map_YYYYMMDD_HHMMSS.svg`

Contents: full floor plan SVG rendering.

## MCP Debug Server

Source: `nhc/debug_tools/`

### Launch

```bash
.venv/bin/python -m nhc.debug_tools.mcp_server
```

Configure in `.mcp.json` for Claude Code integration.

### Architecture

| Module          | Role                                        |
|-----------------|---------------------------------------------|
| `mcp_server.py` | FastMCP server with dynamic tool registration|
| `base.py`       | Base tool class                             |
| `tools/`        | 17 tool implementations across 6 modules    |

## MCP Debug Tools

The MCP server exposes 17 tools organized into six categories.

### Export Management (tools/exports.py)

**list_exports** -- Lists debug export files. Accepts an optional
type filter: `game_state`, `layer_state`, or `map`.

**read_export** -- Reads a specific export file. JSON files are
returned parsed; SVG files are returned as text.

### Game State Queries (tools/game_state.py)

**get_game_snapshot** -- High-level overview: turn number, seed,
player position, entity count, HP.

**get_entity_list** -- All entities in the current level. Filterable
by glyph or room_index.

**get_tile_info** -- Detailed tile data at a given (x, y) position:
terrain, feature, FOV status, entities present, room index, door
state.

**get_henchman_sheets** -- Character sheets for all henchmen in the
most recent `game_state` export: name, level, XP, HP, ability stats,
equipped weapon/armor/shield/helmet/rings, and carried inventory
items. Optional `henchman_id` filters by entity id.

### Dungeon Structure (tools/dungeon.py)

**get_room_info** -- Room bounds and adjacent doors for a given
room_index.

**get_door_analysis** -- All doors with positions and states.
Includes counts by type: C (closed), O (open), S (secret),
L (locked).

**get_tile_map** -- ASCII tile map of the entire level or a
specific region, showing terrain, features, and entities.

**search_tiles** -- Find tiles matching criteria: terrain type,
feature type, or explored status.

### Rendering State (tools/rendering.py)

**get_fov_analysis** -- Visible and explored tile counts with
percentages, perimeter tiles, and FOV radius.

**get_layer_state** -- Rendering layer summary: FOV coverage,
explored area, door positions, room and corridor metadata.

### SVG Query (tools/svg_query.py)

**get_svg_tile_elements** -- Returns SVG elements overlapping a
given tile position: floor_fill, wall_segment, shadow, hatch_line,
and other element types.

### IR Query (tools/ir_query.py — Phase 2 of `design/map_ir.md`)

These tools land alongside the existing SVG ones once the
FlatBuffers IR is wired in. The SVG tools stay available for
backwards compatibility but become cold-path-only after the IR
cutover.

**get_ir_region** -- Returns a region polygon + shape tag for a
given region id (e.g. `dungeon`, `cave_0`, `room_3`).

**get_ir_ops** -- Returns the op vector with optional filtering by
op kind (e.g. `hatch`, `floor_detail`, `tree_feature`).

**get_ir_buffer** -- Returns the full FlatBuffers buffer + a
canonicalised JSON dump for offline analysis.

**get_ir_diff** -- High-level structural diff between two IR
buffers: which regions changed, which ops were added or removed.
Useful for catching regressions in IR emission.

### Autosave Diagnostics (tools/autosave.py)

**get_autosave_info** -- Autosave state diagnostics: seed, turn,
depth, player position, room analysis, entity counts, floor cache
inspection, and character snapshot.

## Usage Examples

### Terminal Debugging

```bash
# God mode with combat and AI logging
./play --god --debug-topics combat,ai -G

# All debug topics written to file
./play -v --log-file debug/full.log -G

# List available debug topics
./play --list-topics
```

### Web Debugging

```bash
# Start server with debug panel enabled
./server --god

# In the browser: click the gear icon in the toolbar
# Use Layers tab to toggle overlays
# Use Export tab to dump game state
```

### MCP Debugging (Claude Code)

Add the server to `.mcp.json`:

```json
{
  "mcpServers": {
    "nhc-debug": {
      "command": ".venv/bin/python",
      "args": ["-m", "nhc.debug_tools.mcp_server"]
    }
  }
}
```

Then use the tools from Claude Code:

- `get_game_snapshot` -- quick status check
- `get_tile_info` -- inspect a specific tile
- `get_tile_map` -- ASCII overview of the level layout
- `get_door_analysis` -- audit door placement and states
- `get_entity_list` -- find entities by glyph or room
- `search_tiles` -- locate tiles by terrain or feature
- `get_autosave_info` -- inspect autosave state and diagnostics
- `get_henchman_sheets` -- inspect henchman character sheets
