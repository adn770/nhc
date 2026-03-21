"""Entity-Component-System foundation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Entity IDs are simple integers
EntityId = int


class World:
    """Central ECS store: entities and their components."""

    def __init__(self) -> None:
        self._next_id: EntityId = 0
        self._components: dict[str, dict[EntityId, Any]] = {}
        self._entities: set[EntityId] = set()

    def create_entity(self, components: dict[str, Any] | None = None) -> EntityId:
        """Create a new entity, optionally with initial components."""
        eid = self._next_id
        self._next_id += 1
        self._entities.add(eid)

        if components:
            for comp_type, comp_data in components.items():
                self.add_component(eid, comp_type, comp_data)

        return eid

    def destroy_entity(self, eid: EntityId) -> None:
        """Remove an entity and all its components."""
        self._entities.discard(eid)
        for store in self._components.values():
            store.pop(eid, None)

    def add_component(self, eid: EntityId, comp_type: str, comp: Any) -> None:
        """Attach a component to an entity."""
        if comp_type not in self._components:
            self._components[comp_type] = {}
        self._components[comp_type][eid] = comp

    def get_component(self, eid: EntityId, comp_type: str) -> Any | None:
        """Get a single component from an entity."""
        return self._components.get(comp_type, {}).get(eid)

    def has_component(self, eid: EntityId, comp_type: str) -> bool:
        return eid in self._components.get(comp_type, {})

    def query(self, *comp_types: str) -> list[tuple[EntityId, ...]]:
        """Query entities that have ALL specified component types.

        Returns list of (entity_id, comp1, comp2, ...) tuples.
        """
        if not comp_types:
            return []

        # Start with entities that have the first component type
        stores = [self._components.get(ct, {}) for ct in comp_types]
        if not all(stores):
            return []

        candidate_ids = set(stores[0].keys())
        for store in stores[1:]:
            candidate_ids &= set(store.keys())

        results = []
        for eid in candidate_ids:
            row = (eid,) + tuple(store[eid] for store in stores)
            results.append(row)

        return results

    @property
    def entity_count(self) -> int:
        return len(self._entities)
