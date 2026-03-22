"""Game state summarizer for LLM context window.

Produces a structured dict of the current game state suitable for
inclusion in LLM prompts.  Only information the player character can
perceive is included — no secret doors, hidden traps, or rooms the
player hasn't entered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nhc.dungeon.model import Terrain

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

# Feature names for context (only visible/known ones)
_FEATURE_NAMES = {
    "door_closed": "closed door",
    "door_open": "open door",
    "door_locked": "locked door",
    "stairs_up": "stairs leading up",
    "stairs_down": "stairs leading down",
}


class ContextBuilder:
    """Builds a structured game-state snapshot for the GM pipeline.

    Only includes information the player character can actually
    perceive: visible tiles, explored rooms they've visited, and
    entities on visible tiles.  Secret doors and hidden traps are
    excluded.
    """

    def __init__(self) -> None:
        self.recent_events: list[str] = []
        self._max_events = 20
        self._visited_rooms: set[str] = set()

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

        # Current location (room or corridor) + surroundings
        location = self._describe_location(level, pos)
        self._visited_rooms.add(location.get("id", ""))

        # Visible features (doors, stairs, water — NOT secret doors/hidden traps)
        visible_features = self._visible_features(level, pos)

        # Entities split into seen (identified) and perceived (vague)
        seen, perceived = self._categorize_entities(
            world, level, player_id, location,
        )

        return {
            "turn": turn,
            "player": player_data,
            "location": location,
            "surroundings": visible_features,
            "seen_entities": seen,
            "perceived_entities": perceived,
            "recent_events": self.recent_events[-10:],
            "level": {
                "name": level.name,
                "depth": level.depth,
                "theme": level.metadata.theme,
                "ambient": level.metadata.ambient,
            },
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

    def _describe_location(
        self, level: "Level", pos,
    ) -> dict[str, Any]:
        """Describe the player's current location."""
        if not pos:
            return {"id": "unknown", "type": "unknown", "description": ""}

        # Check if in a room
        for room in level.rooms:
            r = room.rect
            if (r.x <= pos.x < r.x + r.width
                    and r.y <= pos.y < r.y + r.height):
                return {
                    "id": room.id,
                    "type": "room",
                    "description": room.description,
                    "tags": [t for t in room.tags
                             if t not in ("hidden", "secret")],
                }

        # In a corridor
        tile = level.tile_at(pos.x, pos.y)
        if tile and tile.is_corridor:
            return {
                "id": "corridor",
                "type": "corridor",
                "description": "A narrow dungeon corridor.",
            }

        return {
            "id": "open_area",
            "type": "area",
            "description": "An open area.",
        }

    def _visible_features(
        self, level: "Level", pos,
    ) -> list[dict[str, str]]:
        """List visible features in a 5-tile radius (doors, stairs, water).

        Excludes secret doors and hidden traps — only things the player
        can actually see.
        """
        if not pos:
            return []

        features: list[dict[str, str]] = []
        seen: set[str] = set()
        radius = 5

        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                tx, ty = pos.x + dx, pos.y + dy
                tile = level.tile_at(tx, ty)
                if not tile or not tile.visible:
                    continue

                # Tile features (doors, stairs)
                if tile.feature and tile.feature in _FEATURE_NAMES:
                    key = f"{tile.feature}@{tx},{ty}"
                    if key not in seen:
                        seen.add(key)
                        direction = self._relative_direction(
                            pos.x, pos.y, tx, ty,
                        )
                        features.append({
                            "feature": _FEATURE_NAMES[tile.feature],
                            "direction": direction,
                        })

                # Water/lava terrain
                if tile.terrain == Terrain.WATER:
                    key = f"water@{tx},{ty}"
                    if key not in seen:
                        seen.add(key)
                        direction = self._relative_direction(
                            pos.x, pos.y, tx, ty,
                        )
                        features.append({
                            "feature": "water",
                            "direction": direction,
                        })

        return features

    def _relative_direction(
        self, px: int, py: int, tx: int, ty: int,
    ) -> str:
        """Describe direction from player to target."""
        dx = tx - px
        dy = ty - py
        if dx == 0 and dy == 0:
            return "here"
        parts = []
        if dy < 0:
            parts.append("north")
        elif dy > 0:
            parts.append("south")
        if dx > 0:
            parts.append("east")
        elif dx < 0:
            parts.append("west")
        return " ".join(parts) if parts else "here"

    def _categorize_entities(
        self,
        world: "World",
        level: "Level",
        player_id: int,
        location: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split entities into *seen* (identified) and *perceived* (vague).

        **Seen** — in the same room as the player, or within 3 tiles in
        a corridor.  Full name, type, and direction.  The LLM can
        describe these freely.

        **Perceived** — on a visible tile but in a different room or
        beyond close range.  No name or type — only a vague sensory
        hint ("something", direction).  The LLM may hint at sounds or
        movement but must NOT reveal what the entity is.
        """
        pos = world.get_component(player_id, "Position")
        if not pos:
            return [], []

        player_room = location.get("id", "")
        close_range = 3

        seen: list[dict[str, Any]] = []
        perceived: list[dict[str, Any]] = []

        for eid, desc, epos in world.query("Description", "Position"):
            if eid == player_id or epos is None:
                continue

            tile = level.tile_at(epos.x, epos.y)
            if not tile or not tile.visible:
                continue

            # Skip hidden traps
            trap = world.get_component(eid, "Trap")
            if trap and trap.hidden:
                continue

            dist = abs(epos.x - pos.x) + abs(epos.y - pos.y)
            direction = self._relative_direction(
                pos.x, pos.y, epos.x, epos.y,
            )

            entity_type = "item"
            if world.has_component(eid, "AI"):
                entity_type = "creature"
            elif trap:
                entity_type = "trap"

            # Determine if entity is in the same room as the player
            same_room = False
            if player_room and player_room != "corridor":
                entity_room = self._room_at(level, epos.x, epos.y)
                same_room = (entity_room == player_room)

            # Close range OR same room → fully seen
            if same_room or dist <= close_range:
                seen.append({
                    "id": eid,
                    "type": entity_type,
                    "name": desc.name,
                    "direction": direction,
                })
            else:
                # Perceived but not identified
                perceived.append({
                    "hint": "something" if entity_type == "creature"
                            else "an object",
                    "direction": direction,
                })

        return seen, perceived

    def _room_at(self, level: "Level", x: int, y: int) -> str:
        """Return the room ID at a position, or empty string."""
        for room in level.rooms:
            r = room.rect
            if (r.x <= x < r.x + r.width
                    and r.y <= y < r.y + r.height):
                return room.id
        return ""
