# NHC Web Frontend and Deployment

## 1. Overview

Web frontend for the NHC roguelike dungeon crawler. The backend uses
Flask with WebSocket support, while the frontend renders dungeon maps
through an SVG + Canvas hybrid approach. The visual style draws from
Dyson Logos hand-drawn dungeon maps, with a dark terminal theme
throughout. The entire stack is Dockerized for production deployment
with automatic TLS via Caddy.

## 2. Architecture

- **Backend**: Flask + flask-sock WebSocket. Development runs the
  built-in server; production uses gunicorn with gevent workers.
- **Frontend**: HTML5 with a 4-zone layout: map viewport, action
  toolbar, status bar, and history/input panel.
- **Rendering**: Static SVG serves as the dungeon floor, overlaid
  with 4 canvas layers for doors, hatching, fog, and entities.
- **Communication**: Bidirectional JSON over WebSocket with
  delta-encoded FOV and hatch updates to minimize bandwidth.
- **Authentication**: Two-tier system with an admin token and
  per-player tokens, all SHA256 hashed at rest.

## 3. SVG Rendering

**Source**: `nhc/rendering/svg.py`

Procedural dungeon maps in the Dyson Logos style, rendered at
CELL=32px per grid cell with PADDING=32px border.

Rendering layers, back to front:

1. Background fill
2. Room shadows
3. Corridor shadows
4. Exterior cross-hatching
5. Corridor cross-hatching
6. Walls and floor fills
7. Floor grid lines
8. Floor detail (stone patterns)
9. Stairs

Cross-hatching uses Shapely geometry for proper wall-exterior
detection. The `hatch_distance` parameter controls how far hatching
extends from the dungeon perimeter.

The hatch pattern is a separate 8x8 tileable SVG definition using
Perlin noise, weighing approximately 100KB.

SVG output is cached on disk after the first render and served with
a 1-day HTTP cache header.

## 4. Canvas Layers

**Source**: `nhc/web/static/js/map.js`

Four stacked canvas layers sit over the SVG base image:

1. **Door canvas** (z-index 0): Door overlays rendered on room edges.
2. **Hatch canvas** (z-index 1): Dyson hatching pattern masking
   unexplored areas.
3. **Fog canvas** (z-index 2): Dark overlay on tiles outside the
   current field of view.
4. **Entity canvas** (z-index 3): Player (@), creatures, and items
   rendered as text glyphs.

A fifth debug canvas (z-index 4) activates in god mode for room
boundary, corridor, and door overlays.

Features:

- **Zoom**: 6 discrete levels from 0.5x to 2.0x.
- **Click-to-move**: Pixel coordinates map to grid cells for
  point-and-click movement.
- **Viewport**: Smooth centering on the player after each move.

## 5. Frontend Architecture

JavaScript modules in `nhc/web/static/js/`:

| File | Lines | Responsibility |
|------|-------|----------------|
| `nhc.js` | 223 | Entry point, WS message routing, game lifecycle |
| `map.js` | 600 | Canvas rendering, FOV/hatch updates, zoom, scroll |
| `ui.js` | 438 | Status bar (3 lines), message history, modals, inventory |
| `input.js` | 224 | Keyboard shortcuts (vi-like), toolbar (15 actions), clicks |
| `ws.js` | 50 | WebSocket connection, message handler registry |
| `debug.js` | 472 | God mode debug panel, layer toggles, exports, overlays |

**Stylesheet**: `nhc.css` (637 lines) defines the dark terminal
theme with `#1a1a2e` background and `#e6c07b` accent color.

## 6. WebSocket Protocol

**Source**: `nhc/web/ws.py`

Each connection spawns 3 threads: main (receive), sender (drain
outbound queue), and game loop (async turn processing).

### Client to Server

| Message | Fields | Purpose |
|---------|--------|---------|
| `action` | type, intent, data | Player command |
| `typed` | type, text | Typed mode text input |
| `click` | type, x, y | Map click coordinates |
| `item_action` | type, action, item_id | Inventory interaction |
| `menu_select` | type, choice | Modal dialog selection |

### Server to Client

| Message | Fields | Purpose |
|---------|--------|---------|
| `state` | entities, doors, FOV delta, turn | Turn update |
| `message` | text, level | Log entry |
| `narrative` | text | Narrative text |
| `stats_init` | static character data | Sent once on connect |
| `stats` | HP, XP, gold, inventory | Dynamic character data |
| `floor` | SVG URL, full state | New dungeon level |
| `menu` | title, options | Modal dialog |
| `game_over` | info | End game |

### Delta Encoding

FOV and hatch updates send add/del sets when the change affects
fewer than 50% of tiles; otherwise they send the full list. This
achieves roughly 80% bandwidth reduction in typical play.

## 7. Web Client Renderer

**Source**: `nhc/rendering/web_client.py`

A GameClient subclass that translates ECS state into JSON messages
for the WebSocket protocol.

Key methods:

- `_gather_entities()`: Visible entities with position, glyph, color,
  and HP bar data.
- `_gather_stats()`: Character sheet, dynamic stats, and full
  inventory listing.
- `_gather_doors()`: Door positions, open/closed states, wall edges,
  and orientation.
- `_gather_fov()`: Visible tile coordinates, delta-tracked against
  the previous frame.
- `_gather_hatch_clear()`: Tiles to unhatch, filtered to FLOOR and
  WATER types only, with door-awareness.
- `_gather_debug_data()`: Room boundaries, corridor paths, and door
  metadata for the debug overlay.

## 8. Authentication

**Sources**: `nhc/web/auth.py`, `nhc/web/registry.py`

Two-tier token system:

- **Admin token**: Single master token granting access to /admin
  routes. Optional LAN-only mode bypasses authentication.
- **Player tokens**: Per-player tokens stored in `players.json`.
  Each token can be revoked or regenerated independently.

Token extraction priority: query parameter, then cookie, then
Authorization header.

Cookies used:

- `nhc_token` — player session token
- `nhc_admin_token` — admin session token

## 9. Session Management

**Source**: `nhc/web/sessions.py`

- Configurable maximum concurrent sessions (default 8).
- Auto-suspend on WebSocket disconnect, auto-resume on reconnect.
- 30-minute idle timeout with automatic session reaping.
- Player-to-session mapping ensures continuity across reconnections.

## 10. Admin Panel

**Source**: `nhc/web/templates/admin.html`

Features:

- Player registration: enter a name, receive a token and access link.
- Player management: regenerate tokens, revoke access, view save
  file status.
- Active session monitoring: session ID, player name, language,
  last activity timestamp.
- Auto-refresh every 10 seconds.

## 11. Flask Routes

**Source**: `nhc/web/app.py`

### Public

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Index page |
| GET | `/health` | Health check |
| GET | `/api/tilesets` | Available tilesets |
| GET | `/api/help/<lang>` | Help text by language |

### Admin (requires admin token)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/admin` | Admin panel |
| CRUD | `/api/admin/players` | Player management |
| GET | `/api/admin/sessions` | Active session list |

### Player (requires player token)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/player/login` | Player login |
| POST | `/api/game/new` | Create new game |
| POST | `/api/game/resume` | Resume saved game |

### Game (active session)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/game/<sid>/floor.svg` | Dungeon floor SVG |
| GET | `/api/game/<sid>/hatch.svg` | Hatch pattern SVG |
| GET | `/api/game/<sid>/debug.json` | Debug data |
| GET | `/api/game/<sid>/labels.json` | Room labels |

### Export (god mode only)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/api/game/<sid>/export/game_state` | Full game state |
| POST | `/api/game/<sid>/export/layer_state` | Rendering layers |
| POST | `/api/game/<sid>/export/map_svg` | Full map SVG |

Rate limiting: 5 requests per 60 seconds per IP on game creation
endpoints.

## 12. Deployment Stack

### Docker

- **Dockerfile**: Python 3.12-slim base, gunicorn with gevent
  workers, built-in health check endpoint.
- **docker-compose.yml**: 3 services:
  - `nhc`: Application container on port 8080.
  - `caddy`: Reverse proxy with automatic TLS certificate
    provisioning.
  - `duckdns`: Dynamic DNS updater sidecar.
- **Caddyfile**: Routes `{subdomain}.duckdns.org` to the nhc
  container with gzip compression enabled.

### Systemd

- **deploy/nhc.service**: Systemd unit with automatic restart on
  failure. Environment secrets live in an `override.conf` drop-in.
- **deploy/setup.sh**: Interactive production setup script that
  handles Docker image building, admin token generation, DuckDNS
  configuration, and systemd service enablement.

### Data Persistence

The `/var/nhc` volume holds persistent data:

- `players.json` — registered players and hashed tokens
- `saves/` — game save files
- `svg_cache/` — cached SVG renders

## 13. Configuration

**Source**: `nhc/web/config.py`

WebConfig dataclass fields:

| Field | Purpose |
|-------|---------|
| `host` | Bind address |
| `port` | Bind port |
| `max_sessions` | Concurrent session limit |
| `auth_required` | Enable token authentication |
| `ollama_url` | Ollama LLM endpoint |
| `ollama_model` | Ollama model name |
| `default_lang` | Default language (en/ca/es) |
| `default_tileset` | Default tileset |
| `reset` | Reset state on startup |
| `shape_variety` | Room shape variety level |
| `god_mode` | Enable god mode features |
| `data_dir` | Persistent data directory |
| `hatch_distance` | Hatching extent from perimeter |

## 14. Entry Points

### Development

```bash
./server              # Runs nhc_web.py with Flask debug mode
```

### Production

```bash
gunicorn --worker-class gevent nhc.web.app:app_factory()
```

### Command-Line Flags

| Flag | Purpose |
|------|---------|
| `--host` | Bind address |
| `--port` | Bind port |
| `--max-sessions` | Concurrent session limit |
| `--auth` | Require authentication |
| `--token` | Set admin token |
| `--reset` | Reset state on startup |
| `--god` | Enable god mode |
| `--shape-variety` | Room shape variety |
| `--ollama-url` | Ollama endpoint URL |
| `--ollama-model` | Ollama model name |
| `--data-dir` | Persistent data directory |
