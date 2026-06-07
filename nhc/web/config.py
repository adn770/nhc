"""Web server configuration."""

from __future__ import annotations

from dataclasses import dataclass
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
    external_url: str = ""
    # When True, wrap the WSGI app in Werkzeug's ``ProxyFix`` so
    # ``request.remote_addr`` reflects the original client IP sent
    # in ``X-Forwarded-For`` by the single trusted upstream proxy
    # (e.g. Caddy on localhost).  Leave False for bare-metal dev.
    trust_proxy: bool = False
