"""Game state summarizer for LLM context window.

Produces a structured dict of the current game state suitable for
inclusion in LLM prompts.  Entity names, room descriptions, and
other player-facing text come from the i18n-aware Description
components so they match the active language.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level


class ContextBuilder:
    """Builds a structured game-state snapshot for the GM pipeline."""

    def __init__(self) -> None:
        self.recent_events: list[str] = []
        self._max_events = 20

    def add_event(self, summary: str) -> None:
        """Record a concise event summary string."""
        self.recent_events.append(summary)
        if len(self.recent_events) > self._max_events:
            self.recent_events = self.recent_events[-self._max_events:]

    def build(
        self,
        world: "World",
        level: "Level",
        player_id: int,
        turn: int,
    ) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the game state."""
        health = world.get_component(player_id, "Health")
        stats = world.get_component(player_id, "Stats")
        player = world.get_component(player_id, "Player")
        pdesc = world.get_component(player_id, "Description")
        pos = world.get_component(player_id, "Position")
        inv = world.get_component(player_id, "Inventory")
        status = world.get_component(player_id, "StatusEffect")

        # Player info
        player_data: dict[str, Any] = {
            "name": pdesc.name if pdesc else "Adventurer",
            "hp": f"{health.current}/{health.maximum}" if health else "?",
            "stats": {
                "str": stats.strength if stats else 0,
                "dex": stats.dexterity if stats else 0,
                "con": stats.constitution if stats else 0,
                "int": stats.intelligence if stats else 0,
                "wis": stats.wisdom if stats else 0,
                "cha": stats.charisma if stats else 0,
            },
            "position": [pos.x, pos.y] if pos else [0, 0],
            "gold": player.gold if player else 0,
            "conditions": self._conditions(status),
        }

        # Inventory items
        items: list[str] = []
        if inv:
            for eid in inv.slots:
                desc = world.get_component(eid, "Description")
                items.append(desc.name if desc else "???")
        player_data["inventory"] = items

        # Current room
        room_data = self._find_room(level, pos)

        # Visible entities (excluding player)
        visible = self._visible_entities(world, level, player_id)

        return {
            "turn": turn,
            "player": player_data,
            "current_room": room_data,
            "visible_entities": visible,
            "recent_events": self.recent_events[-10:],
            "level": {
                "name": level.name,
                "depth": level.depth,
                "theme": level.metadata.theme,
                "ambient": level.metadata.ambient,
            },
            "narrative_hooks": level.metadata.narrative_hooks,
        }

    def _conditions(self, status) -> list[str]:
        """Extract active status effects as a list of strings."""
        if not status:
            return []
        conditions = []
        for field in ("paralyzed", "sleeping", "hasted", "blessed",
                      "invisible", "protected", "webbed", "charmed",
                      "shielded", "levitating", "flying", "confused"):
            val = getattr(status, field, 0)
            if val > 0:
                conditions.append(f"{field}:{val}")
        if getattr(status, "mirror_images", 0) > 0:
            conditions.append(f"mirror_images:{status.mirror_images}")
        return conditions

    def _find_room(self, level: "Level", pos) -> dict[str, Any]:
        """Find which room the player is in."""
        if not pos:
            return {"id": "unknown", "description": "", "tags": []}
        for room in level.rooms:
            r = room.rect
            if (r.x <= pos.x < r.x + r.width
                    and r.y <= pos.y < r.y + r.height):
                return {
                    "id": room.id,
                    "description": room.description,
                    "tags": room.tags,
                }
        return {"id": "corridor", "description": "A dungeon corridor.",
                "tags": []}

    def _visible_entities(
        self, world: "World", level: "Level", player_id: int,
    ) -> list[dict[str, Any]]:
        """List visible non-player entities."""
        entities = []
        for eid, desc, epos in world.query("Description", "Position"):
            if eid == player_id or epos is None:
                continue
            tile = level.tile_at(epos.x, epos.y)
            if not tile or not tile.visible:
                continue

            entity_type = "item"
            if world.has_component(eid, "AI"):
                entity_type = "creature"
            elif world.has_component(eid, "Trap"):
                entity_type = "feature"

            entities.append({
                "id": eid,
                "type": entity_type,
                "name": desc.name,
                "pos": [epos.x, epos.y],
            })
        return entities
