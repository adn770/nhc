"""Shared helper functions for action modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.events import Event, MessageEvent
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World


def _item_slot_cost(world: "World", eid: int) -> int:
    """Return the number of inventory slots an item uses."""
    wpn = world.get_component(eid, "Weapon")
    if wpn:
        return wpn.slots
    arm = world.get_component(eid, "Armor")
    if arm:
        return arm.slots
    return 1


def _count_slots_used(world: "World", inv) -> int:
    """Sum slot costs of all items in an inventory."""
    total = 0
    for item_id in inv.slots:
        total += _item_slot_cost(world, item_id)
    return total


def has_ring_effect(world: "World", entity_id: int, effect: str) -> bool:
    """Check if entity has a ring with the given effect equipped."""
    equip = world.get_component(entity_id, "Equipment")
    if not equip:
        return False
    for slot in ("ring_left", "ring_right"):
        ring_id = getattr(equip, slot)
        if ring_id is not None:
            ring = world.get_component(ring_id, "Ring")
            if ring and ring.effect == effect:
                return True
    return False


def _get_armor_magic(world: "World", entity_id: int) -> int:
    """Sum magic_bonus from all equipped armor pieces on an entity."""
    equip = world.get_component(entity_id, "Equipment")
    if not equip:
        return 0
    total = 0
    for slot in ("armor", "shield", "helmet"):
        eid = getattr(equip, slot)
        if eid is not None:
            armor = world.get_component(eid, "Armor")
            if armor:
                total += armor.magic_bonus
    return total


def _entity_name(world: "World", eid: int) -> str:
    """Get raw display name for an entity (no article)."""
    desc = world.get_component(eid, "Description")
    if desc and desc.name:
        return desc.name
    player = world.get_component(eid, "Player")
    if player is not None:
        return t("game.player_name")
    return "something"


def _is_player(world: "World", eid: int) -> bool:
    """Check if an entity is the player."""
    return world.has_component(eid, "Player")


_CATALAN_VOWELS = set("aeiouàèéíòóúh")


def _det_name(world: "World", eid: int) -> str:
    """Get display name with article for Romance languages.

    For Catalan/Spanish, prepends el/la/l' based on grammatical gender.
    For English or entities without gender, returns the raw name.
    """
    from nhc.i18n import current_lang

    desc = world.get_component(eid, "Description")
    if not desc or not desc.name:
        player = world.get_component(eid, "Player")
        if player is not None:
            return t("game.player_name")
        return "something"

    name = desc.name
    gender = desc.gender
    lang = current_lang()

    if not gender or lang == "en":
        return name

    lower = name.lower()
    if lang == "ca":
        if lower[0] in _CATALAN_VOWELS:
            return f"l'{lower}"
        return f"el {lower}" if gender == "m" else f"la {lower}"
    elif lang == "es":
        if gender == "m":
            return f"el {lower}"
        return f"la {lower}"

    return name


def _capitalize_first(s: str) -> str:
    """Capitalize the first character, handling elided articles like l'."""
    if not s:
        return s
    if len(s) >= 3 and s[1] == "'":
        # "l'esquelet" -> "L'esquelet"
        return s[0].upper() + s[1:]
    return s[0].upper() + s[1:]


def _msg(
    key: str,
    world: "World",
    *,
    actor: int | None = None,
    target: int | None = None,
    **kwargs: object,
) -> str:
    """Build a message, selecting player-aware variant if available.

    For Romance languages (Catalan, Spanish), combat messages need different
    verb conjugations when the player is involved. This helper selects:
      - "you_{leaf}" variant when the player is the actor
      - "{leaf}_you" variant when the player is the target
      - the base key as fallback (3rd person)

    Entity names are inserted with articles for Romance languages, and the
    first character of the result is capitalized.
    """
    section, leaf = key.rsplit(".", 1)
    actor_is_player = actor is not None and _is_player(world, actor)
    target_is_player = target is not None and _is_player(world, target)

    # Build kwargs with article-aware entity names
    kw = dict(**kwargs)
    if actor is not None:
        name = _det_name(world, actor)
        kw["attacker"] = name
        kw["actor"] = name
        kw["entity"] = name
    if target is not None:
        kw["target"] = _det_name(world, target)

    # Try player-specific variant first
    if actor_is_player:
        variant = f"{section}.you_{leaf}"
        result = t(variant, **kw)
        if result != variant:
            return _capitalize_first(result)
    elif target_is_player:
        variant = f"{section}.{leaf}_you"
        result = t(variant, **kw)
        if result != variant:
            return _capitalize_first(result)

    return _capitalize_first(t(key, **kw))


def _items_at(
    world: "World", x: int, y: int, exclude: int = -1,
) -> list[int]:
    """Find item entities at a given position."""
    items: list[int] = []
    for eid, _, ipos in world.query("Description", "Position"):
        if ipos is None or eid == exclude:
            continue
        if ipos.x == x and ipos.y == y:
            if (not world.has_component(eid, "AI")
                    and not world.has_component(eid, "BlocksMovement")
                    and not world.has_component(eid, "Trap")):
                items.append(eid)
    return items


def _announce_ground_items(
    world: "World", x: int, y: int, actor: int,
) -> list[Event]:
    """Generate messages for items lying on the ground at position."""
    items = _items_at(world, x, y, exclude=actor)
    if not items:
        return []

    events: list[Event] = []
    if len(items) == 1:
        desc = world.get_component(items[0], "Description")
        name = (desc.short or desc.name) if desc else "something"
        events.append(MessageEvent(
            text=t("explore.see_item", item=name),
        ))
    else:
        names = []
        for eid in items:
            desc = world.get_component(eid, "Description")
            names.append(desc.name if desc else "???")
        events.append(MessageEvent(
            text=t("explore.see_items", count=len(items),
                   items=", ".join(names)),
        ))
    return events
