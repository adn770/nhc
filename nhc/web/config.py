"""Web server configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WebConfig:
    """Configuration for the nhc web server."""

    host: str = "127.0.0.1"
    port: int = 5000
    max_sessions: int = 8
    auth_required: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:12b"
    default_lang: str = "ca"
    default_tileset: str = "classic"
    reset: bool = False
