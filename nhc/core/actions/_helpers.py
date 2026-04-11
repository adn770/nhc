"""Shared helper functions for action modules."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nhc.core.events import Event, MessageEvent
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World


def _item_slot_cost(world: "World", eid: int) -> int:
    """Return the number of inventory slots an item uses."""
    if world.has_component(eid, "Gem"):
        return 0
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


def _stack_ground_items(
    world: "World", items: list[int],
) -> list[tuple[int, int, str]]:
    """Group identical items into stacks for display.

    Items are grouped by Description.name. Returns a list of
    (representative_entity_id, count, label) tuples in stable order.
    The label uses the localized plural form when count > 1 and a
    plural is available; otherwise the singular short/name string
    (or a generic "{count}× {name}" fallback).
    """
    order: list[str] = []
    groups: dict[str, list[int]] = {}
    for eid in items:
        desc = world.get_component(eid, "Description")
        # Gold piles already encode their amount in the name string,
        # so each pile remains a unique stack via its name.
        key = desc.name if desc and desc.name else f"__eid_{eid}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(eid)

    stacks: list[tuple[int, int, str]] = []
    for key in order:
        eids = groups[key]
        rep = eids[0]
        count = len(eids)
        desc = world.get_component(rep, "Description")
        gold_label = _gold_pile_label(world, rep)
        if count == 1:
            if gold_label is not None:
                label = gold_label
            elif desc:
                label = desc.short or desc.name or "something"
            else:
                label = "something"
        else:
            if desc and desc.plural:
                label = f"{count} {desc.plural}"
            elif desc and desc.name:
                label = f"{count}× {desc.name}"
            else:
                label = f"{count}× something"
        stacks.append((rep, count, label))
    return stacks


def _gold_pile_label(world: "World", item_id: int) -> str | None:
    """Return a localized "N gold coins" label for a gold pile.

    Gold quantity is encoded as a leading integer in Description.name
    (e.g. "47 Or").  Returns None for non-gold items or when the
    amount cannot be parsed.
    """
    if not world.has_component(item_id, "Gold"):
        return None
    desc = world.get_component(item_id, "Description")
    if not desc or not desc.name:
        return None
    match = re.match(r"(\d+)", desc.name)
    amount = int(match.group(1)) if match else 1
    key = "item.gold_pile_one" if amount == 1 else "item.gold_pile"
    return t(key, amount=amount)


def _announce_ground_items(
    world: "World", x: int, y: int, actor: int,
) -> list[Event]:
    """Generate messages for items lying on the ground at position.

    Identical items are grouped into stacks so that, e.g., three goblin
    corpses on the same tile become "3 goblin corpses" rather than
    three separate entries.
    """
    items = _items_at(world, x, y, exclude=actor)
    if not items:
        return []

    stacks = _stack_ground_items(world, items)
    events: list[Event] = []
    if len(stacks) == 1:
        events.append(MessageEvent(
            text=t("explore.see_item", item=stacks[0][2]),
        ))
    else:
        total = sum(count for _, count, _ in stacks)
        labels = ", ".join(label for _, _, label in stacks)
        events.append(MessageEvent(
            text=t("explore.see_items", count=total, items=labels),
        ))
    return events
