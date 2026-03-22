"""Configuration management.

Three-tier config hierarchy: hardcoded defaults → ~/.nhcrc file → CLI args.
"""

import configparser
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "none",
    "model": "",
    "url": "http://localhost:11434",
    "temp": 0.1,
    "ctx": 16384,
    "api_key": "",
    "lang": "en",
    "colors": "256",
    "mode": "classic",
}

CONFIG_PATH = Path.home() / ".nhcrc"


class ConfigManager:
    """Loads, merges, and persists configuration."""

    def __init__(self) -> None:
        self._config: dict[str, Any] = dict(DEFAULT_CONFIG)

    def load(self, path: Path | None = None) -> dict[str, Any]:
        """Load config from file, merging with defaults."""
        path = path or CONFIG_PATH
        if not path.exists():
            return dict(self._config)

        parser = configparser.ConfigParser()
        parser.read(path)

        if "nhc" in parser:
            for key, value in parser["nhc"].items():
                if key in self._config:
                    target_type = type(DEFAULT_CONFIG.get(key, ""))
                    if target_type is float:
                        self._config[key] = float(value)
                    elif target_type is int:
                        self._config[key] = int(value)
                    else:
                        self._config[key] = value

        return dict(self._config)

    def save(self, path: Path | None = None) -> None:
        """Persist current config to file."""
        path = path or CONFIG_PATH
        parser = configparser.ConfigParser()
        parser["nhc"] = {
            k: str(v) for k, v in self._config.items()
            if isinstance(v, (str, int, float, bool))
        }
        with open(path, "w") as f:
            parser.write(f)

    def merge(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Merge CLI overrides into loaded config and return result."""
        merged = dict(self._config)
        for key, value in overrides.items():
            if value is not None:
                merged[key] = value
        return merged

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)
