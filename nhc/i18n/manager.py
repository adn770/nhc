"""Translation manager — loads YAML locale files and resolves keys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

LOCALES_DIR = Path(__file__).parent / "locales"


class TranslationManager:
    """Loads and serves translations from YAML locale files."""

    def __init__(self) -> None:
        self.lang: str = "en"
        self._strings: dict[str, Any] = {}
        self._fallback: dict[str, Any] = {}

    def load(self, lang: str = "en") -> None:
        """Load a language. English is always loaded as fallback."""
        self.lang = lang

        # Always load English as fallback
        en_path = LOCALES_DIR / "en.yaml"
        if en_path.exists():
            with open(en_path) as f:
                self._fallback = yaml.safe_load(f) or {}

        if lang == "en":
            self._strings = self._fallback
        else:
            lang_path = LOCALES_DIR / f"{lang}.yaml"
            if lang_path.exists():
                with open(lang_path) as f:
                    self._strings = yaml.safe_load(f) or {}
            else:
                self._strings = self._fallback

    def get(self, key: str, **kwargs: object) -> str:
        """Resolve a dotted key, with optional string interpolation.

        Falls back to English if the key is missing in the current language.
        Falls back to the key itself if missing in both.
        """
        value = self._resolve(key, self._strings)
        if value is None:
            value = self._resolve(key, self._fallback)
        if value is None:
            return key

        if kwargs:
            try:
                return str(value).format(**kwargs)
            except (KeyError, IndexError):
                return str(value)
        return str(value)

    def _resolve(self, key: str, data: dict[str, Any]) -> str | None:
        """Walk a dotted key path through nested dicts."""
        parts = key.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        if isinstance(current, str):
            return current
        return None
