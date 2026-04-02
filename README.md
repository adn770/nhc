# NHC -- Nethack-like Crawler

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-yellow.svg)](https://www.python.org/)

A roguelike dungeon crawler built on the
[Knave](https://www.drivethrurpg.com/product/250888/Knave) TTRPG ruleset,
featuring an Entity-Component-System architecture, BSP dungeon generation,
and an optional LLM-driven typed gameplay mode where you describe actions
in natural language and an AI Game Master interprets and narrates the results.

<!-- TODO: Add screenshot -->

## Features

- **ECS architecture** -- dataclass components, World store, entity queries
- **BSP dungeon generation** -- 5 room shapes (rect, circle, octagon, cross,
  hybrid), cellular automata terrain (water, grass), corridor loops
- **Knave combat rules** -- d20 attack vs armor defense, dice pool damage,
  morale system, status effects
- **Terminal TUI** -- blessed-based with 16/256 color, shadowcasting FOV,
  box-drawing walls, 4-zone layout
- **Web frontend** -- HTML5 Canvas with Dyson Logos style SVG rendering,
  WebSocket communication, point-and-click interaction
- **LLM Game Master** -- type natural language actions, LLM interprets and
  narrates outcomes (Ollama, MLX, Anthropic backends)
- **Multilingual** -- English, Catalan, Spanish (~2000 translation lines each)
- **78 creatures** -- full BEB bestiary with AI behaviors, factions, loot tables
- **193 items** -- scrolls, potions, wands, rings, weapons, armor, tools
- **13 trap types** -- pit, fire, poison, teleport, alarm, summoning, and more
- **Identification system** -- potion colors, scroll labels, ring gems, wand
  woods shuffled per game seed, revealed on use
- **Save system** -- JSON manual save/load + binary autosave (pickle+zlib)
- **Docker deployment** -- Caddy reverse proxy with automatic TLS via DuckDNS

## Quick Start

### Prerequisites

- Python 3.10 or newer
- (Optional) An LLM backend for typed gameplay mode:
  [Ollama](https://ollama.ai/), MLX, or an Anthropic API key

### Terminal Game

```bash
git clone https://github.com/adn770/nhc.git
cd nhc
./play -G
```

The `./play` launcher creates a virtual environment, installs dependencies,
and starts the game. The `-G` flag generates a new dungeon.

### Web Server

```bash
./server
```

Open `http://localhost:5000` in your browser. The `./server` launcher handles
venv setup and dependency installation automatically.

### Docker

```bash
cp .env.example .env   # edit with your DuckDNS token and settings
docker-compose up -d
```

## Usage

### Terminal

```bash
./play -G                         # Generate dungeon, play
./play --lang ca -G               # Catalan language
./play --lang es -G               # Spanish language
./play --god -G                   # God mode (invulnerable)
./play --mode typed --lang ca -G  # Typed mode with LLM Game Master
./play --seed 12345 -G            # Reproducible dungeon seed
./play --help                     # All options
```

### Web Server

```bash
./server                          # Local dev, no authentication
./server --auth                   # Generate token, require auth
./server --host 0.0.0.0 --auth   # Expose on network
./server --reset                  # Ignore autosave, start fresh
```

### Tests

```bash
.venv/bin/pytest                              # Run all tests
.venv/bin/pytest tests/unit/test_combat.py -v # Specific file
.venv/bin/pytest -k "test_name"               # By name
.venv/bin/pytest -m core                      # By marker
```

Available markers: `core`, `dungeon`, `entities`, `rules`, `narrative`.

## Architecture

The project follows an Entity-Component-System pattern with an async
game loop and event pub/sub. See the `design/` directory for detailed
design documents.

### Core Engine

ECS store with dataclass components, async turn-based game loop, event
bus for decoupled communication, and a 3-tier configuration system
(defaults, `~/.nhcrc`, CLI args).

### Dungeon Generation

BSP algorithm with configurable room sizes and spacing. Rooms are
specialized (treasure, guard, shrine) and painted with themed content.
Cellular automata generates water and grass terrain. Corridors connect
rooms with a main path plus extra loops. Hand-authored YAML levels are
also supported.

### Rendering

- **Terminal** -- blessed TUI with 4-zone layout, shadowcasting FOV,
  16/256 color themes, box-drawing wall characters
- **Web** -- Flask + WebSocket server, HTML5 Canvas with SVG tile
  rendering, inventory panel, action toolbar
- **SVG** -- static map export

### Narrative

LLM Game Master pipeline: player types intent, LLM interprets it into
an action plan, actions execute, LLM narrates the outcome. Includes
story compression for context window management, multilingual prompt
templates, and a keyword-based fallback parser when no LLM is available.

## Project Stats

| Category  | Count |
|-----------|-------|
| Creatures | 78    |
| Items     | 193   |
| Traps     | 13    |
| Languages | 3     |
| Tests     | 780   |

## Keyboard Shortcuts

| Key          | Action         | Key | Action        |
|--------------|----------------|-----|---------------|
| Arrows/hjkl  | Move           | g/, | Pickup        |
| a            | Use item       | q   | Quaff potion  |
| e            | Equip/unequip  | d   | Drop item     |
| t            | Throw potion   | z   | Zap wand      |
| s            | Search secrets | x   | Look around   |
| >            | Descend stairs | <   | Ascend stairs |
| i            | Inventory      | ?   | Help          |
| S            | Save           | L   | Load          |
| TAB          | Toggle mode    | Q   | Quit          |

## Deployment

The game server runs inside a Docker container managed by systemd.
An interactive setup script handles the full deployment:

```bash
sudo ./deploy/setup.sh            # first-time interactive setup
sudo ./deploy/setup.sh --update   # rebuild image + restart
```

The script:

1. Builds the Docker image (`nhc-web`: Python 3.12-slim, gunicorn + gevent)
2. Creates the data directory (`/var/nhc`) for persistent saves
3. Prompts for configuration (auth token, max sessions, optional DuckDNS)
4. Installs the systemd unit (`deploy/nhc.service`)
5. Writes secrets to a systemd override file (`override.conf`, mode 600)
6. Enables, starts, and health-checks the service

Secrets and tunables live in the systemd override, not in `.env`:

```
/etc/systemd/system/nhc.service.d/override.conf
  NHC_AUTH_TOKEN=<generated-or-provided>
  NHC_MAX_SESSIONS=8
  DUCKDNS_SUBDOMAIN=<optional>
  DUCKDNS_TOKEN=<optional>
```

For internet exposure, Caddy provides TLS reverse proxy and DuckDNS
handles dynamic DNS. Ports 80/443 must be forwarded to the host.

Useful commands after deployment:

```bash
journalctl -u nhc -f              # follow logs
systemctl status nhc              # service status
```

## Design Documents

- [`design/design.md`](design/design.md) -- overall system design
- [`design/dungeon_generator.md`](design/dungeon_generator.md) --
  BSP dungeon generation
- [`design/magic_items.md`](design/magic_items.md) --
  identification and magic item systems
- [`design/typed_gameplay.md`](design/typed_gameplay.md) --
  LLM-driven typed gameplay mode
- [`design/web_client.md`](design/web_client.md) --
  web frontend architecture

## License

MIT License. See [LICENSE](LICENSE) for details.
