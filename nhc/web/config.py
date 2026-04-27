"""Web server configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WebConfig:
    """Configuration for the nhc web server."""

    host: str = "127.0.0.1"
    port: int = 5005
    max_sessions: int = 8
    auth_required: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:12b"
    default_lang: str = "en"
    default_tileset: str = "classic"
    reset: bool = False
    shape_variety: float = 0.3
    god_mode: bool = False
    data_dir: Path | None = None
    hatch_distance: float = 2.0
    # When False, the floor / site SVGs sent to the web client
    # skip every tree + bush decorator. The static SVG only ships
    # the structural floor; vegetation comes back via overlays or
    # the next render pass.
    vegetation: bool = True
    external_url: str = ""
    # CIDRs allowed to reach /admin.  Empty list → admin is
    # unreachable (fail closed).  Must NOT include loopback or
    # Docker bridge ranges, since every request behind a local
    # reverse proxy appears from one of those.
    admin_lan_cidrs: list[str] = field(default_factory=list)
    # When True, wrap the WSGI app in Werkzeug's ``ProxyFix`` so
    # ``request.remote_addr`` reflects the original client IP sent
    # in ``X-Forwarded-For`` by the single trusted upstream proxy
    # (e.g. Caddy on localhost).  Leave False for bare-metal dev.
    trust_proxy: bool = False
