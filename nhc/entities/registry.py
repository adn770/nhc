"""Auto-discovery entity registry.

Entity modules in creatures/, items/, and features/ directories register
themselves via decorators. The registry discovers and imports them at startup.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable


class EntityRegistry:
    """Central registry for all entity factories."""

    _creatures: dict[str, Callable] = {}
    _items: dict[str, Callable] = {}
    _features: dict[str, Callable] = {}

    @classmethod
    def register_creature(cls, entity_id: str) -> Callable:
        """Decorator to register a creature factory."""
        def decorator(factory: Callable) -> Callable:
            cls._creatures[entity_id] = factory
            return factory
        return decorator

    @classmethod
    def register_item(cls, entity_id: str) -> Callable:
        """Decorator to register an item factory."""
        def decorator(factory: Callable) -> Callable:
            cls._items[entity_id] = factory
            return factory
        return decorator

    @classmethod
    def register_feature(cls, entity_id: str) -> Callable:
        """Decorator to register a feature factory."""
        def decorator(factory: Callable) -> Callable:
            cls._features[entity_id] = factory
            return factory
        return decorator

    @classmethod
    def discover_all(cls) -> None:
        """Auto-import all entity modules from standard directories."""
        base = Path(__file__).parent
        for subdir in ("creatures", "items", "features"):
            cls._discover_package(base / subdir, f"nhc.entities.{subdir}")

    @classmethod
    def _discover_package(cls, directory: Path, package: str) -> None:
        """Import all non-underscore .py modules in a directory."""
        if not directory.is_dir():
            return
        for module_file in sorted(directory.glob("*.py")):
            if module_file.name.startswith("_"):
                continue
            module_name = f"{package}.{module_file.stem}"
            importlib.import_module(module_name)

    @classmethod
    def get_creature(cls, entity_id: str) -> dict[str, Any]:
        """Create component dict for a creature by ID."""
        factory = cls._creatures.get(entity_id)
        if not factory:
            raise KeyError(f"Unknown creature: {entity_id}")
        return factory()

    @classmethod
    def get_item(cls, entity_id: str) -> dict[str, Any]:
        """Create component dict for an item by ID."""
        factory = cls._items.get(entity_id)
        if not factory:
            raise KeyError(f"Unknown item: {entity_id}")
        return factory()

    @classmethod
    def get_feature(cls, entity_id: str) -> dict[str, Any]:
        """Create component dict for a feature by ID."""
        factory = cls._features.get(entity_id)
        if not factory:
            raise KeyError(f"Unknown feature: {entity_id}")
        return factory()

    @classmethod
    def list_creatures(cls) -> list[str]:
        return sorted(cls._creatures.keys())

    @classmethod
    def list_items(cls) -> list[str]:
        return sorted(cls._items.keys())

    @classmethod
    def list_features(cls) -> list[str]:
        return sorted(cls._features.keys())
