"""Translation manager — loads YAML locale files and resolves keys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

LOCALES_DIR = Path(__file__).parent / "locales"

# Parsed YAML catalogues keyed by language. Populated lazily the
# first time a locale is requested; subsequent loads reuse the
# already-parsed dict so we don't re-read the ~2.4k-line file on
# every TranslationManager() in tests or every init() call during
# a language switch. Callers never mutate the returned dicts --
# TranslationManager.get() only reads them.
_CATALOGUE_CACHE: dict[str, dict[str, Any]] = {}


def _load_catalogue(lang: str) -> dict[str, Any]:
    cached = _CATALOGUE_CACHE.get(lang)
    if cached is not None:
        return cached
    path = LOCALES_DIR / f"{lang}.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        parsed = yaml.safe_load(f) or {}
    _CATALOGUE_CACHE[lang] = parsed
    return parsed


class TranslationManager:
    """Loads and serves translations from YAML locale files."""

    def __init__(self) -> None:
        self.lang: str = "en"
        self._strings: dict[str, Any] = {}
        self._fallback: dict[str, Any] = {}

    def load(self, lang: str = "en") -> None:
        """Load a language. English is always loaded as fallback."""
        self.lang = lang
        self._fallback = _load_catalogue("en")
        if lang == "en":
            self._strings = self._fallback
        else:
            strings = _load_catalogue(lang)
            self._strings = strings if strings else self._fallback

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
