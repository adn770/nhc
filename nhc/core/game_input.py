"""Input dispatch: translate player intents into Action objects.

These functions were extracted from Game to reduce game.py size.
Each takes the Game instance as first argument for access to
world, player_id, level, and renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions import (
    DropAction,
    EquipAction,
    ForceDoorAction,
    PickLockAction,
    PickupItemAction,
    ThrowAction,
    UnequipAction,
    UseItemAction,
    ZapAction,
)
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.actions import Action
    from nhc.core.game import Game


def find_pickup_action(game: Game) -> Action | None:
    """Find an item at the player's position to pick up.

    If multiple items are on the ground, show a selection menu.
    """
    pos = game.world.get_component(game.player_id, "Position")
    if not pos:
        return None

    # Gather all pickable items at player's feet
    ground_items: list[tuple[int, str]] = []
    for eid, _, ipos in game.world.query("Description", "Position"):
        if ipos is None:
            continue
        if ipos.x == pos.x and ipos.y == pos.y and eid != game.player_id:
            if (not game.world.has_component(eid, "AI")
                    and not game.world.has_component(eid, "BlocksMovement")
                    and not game.world.has_component(eid, "Trap")):
                desc = game.world.get_component(eid, "Description")
                name = desc.short or desc.name if desc else "???"
                ground_items.append((eid, name))

    if not ground_items:
        game.renderer.add_message(t("item.nothing_to_pickup"))
        return None

    # Single item: pick up directly
    if len(ground_items) == 1:
        return PickupItemAction(
            actor=game.player_id, item=ground_items[0][0],
        )

    # Multiple items: show selection menu
    selected = game.renderer.show_ground_menu(ground_items)
    if selected is None:
        return None
    return PickupItemAction(
        actor=game.player_id, item=selected,
    )


def find_use_action(game: Game) -> Action | None:
    """Show inventory menu and return a use action."""
    item_id = game.renderer.show_inventory_menu(
        game.world, game.player_id,
    )
    if item_id is None:
        return None
    return UseItemAction(actor=game.player_id, item=item_id)


def find_quaff_action(game: Game) -> Action | None:
    """Show potions only and quaff one."""
    item_id = game.renderer.show_filtered_inventory(
        game.world, game.player_id,
        title=t("ui.quaff_which"),
        filter_component="Consumable",
    )
    if item_id is None:
        return None
    return UseItemAction(actor=game.player_id, item=item_id)


def find_throw_action(game: Game) -> Action | None:
    """Pick a potion, then a visible target to throw it at."""
    # Step 1: pick a throwable item
    item_id = game.renderer.show_filtered_inventory(
        game.world, game.player_id,
        title=t("ui.throw_which"),
        filter_component="Throwable",
    )
    if item_id is None:
        return None

    # Step 2: pick a visible target
    target_id = game.renderer.show_target_menu(
        game.world, game.level, game.player_id,
        title=t("ui.throw_target"),
    )
    if target_id is None:
        return None

    return ThrowAction(
        actor=game.player_id, item=item_id, target=target_id,
    )


def find_zap_action(game: Game) -> Action | None:
    """Pick a wand, then a visible target to zap."""
    inv = game.world.get_component(game.player_id, "Inventory")
    if not inv:
        return None

    items: list[tuple[int, str]] = []
    for item_id in inv.slots:
        wand = game.world.get_component(item_id, "Wand")
        if not wand:
            continue
        desc = game.world.get_component(item_id, "Description")
        name = desc.name if desc else "???"
        name += f" ({wand.charges}/{wand.max_charges})"
        items.append((item_id, name))

    if not items:
        return None

    selected = game.renderer.show_selection_menu(
        t("ui.zap_which"), items,
    )
    if selected is None:
        return None

    wand = game.world.get_component(selected, "Wand")
    if not wand or wand.charges <= 0:
        game.renderer.add_message(t("item.wand_fizzle"))
        return None

    target_id = game.renderer.show_target_menu(
        game.world, game.level, game.player_id,
        title=t("ui.throw_target"),
    )
    if target_id is None:
        return None

    return ZapAction(
        actor=game.player_id, item=selected, target=target_id,
    )


def find_equip_action(game: Game) -> Action | None:
    """Show equippable items and equip/unequip one."""
    inv = game.world.get_component(game.player_id, "Inventory")
    if not inv or not inv.slots:
        return None

    equip = game.world.get_component(game.player_id, "Equipment")
    equipped_ids = set()
    if equip:
        for attr in ("weapon", "armor", "shield", "helmet",
                      "ring_left", "ring_right"):
            eid = getattr(equip, attr)
            if eid is not None:
                equipped_ids.add(eid)

    items: list[tuple[int, str]] = []
    for item_id in inv.slots:
        if not (game.world.has_component(item_id, "Weapon")
                or game.world.has_component(item_id, "Armor")
                or game.world.has_component(item_id, "Ring")):
            continue
        desc = game.world.get_component(item_id, "Description")
        name = desc.name if desc else "???"
        if item_id in equipped_ids:
            name += " [E]"
        items.append((item_id, name))

    if not items:
        return None

    selected = game.renderer.show_selection_menu(
        t("ui.equip_which"), items,
    )
    if selected is None:
        return None

    # Toggle: if already equipped, unequip; otherwise equip
    if selected in equipped_ids:
        return UnequipAction(actor=game.player_id, item=selected)
    return EquipAction(actor=game.player_id, item=selected)


def find_drop_action(game: Game) -> Action | None:
    """Show full inventory and drop selected item."""
    item_id = game.renderer.show_inventory_menu(
        game.world, game.player_id,
        prompt=t("ui.drop_which"),
    )
    if item_id is None:
        return None
    return DropAction(actor=game.player_id, item=item_id)


def find_lock_action(game: Game, mode: str) -> Action | None:
    """Find an adjacent locked door and return pick/force action."""
    pos = game.world.get_component(game.player_id, "Position")
    if not pos or not game.level:
        return None

    # Check all 4 cardinal directions for a locked door
    door_dir = None
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        tile = game.level.tile_at(pos.x + dx, pos.y + dy)
        if tile and tile.feature == "door_locked":
            door_dir = (dx, dy)
            break

    if not door_dir:
        game.renderer.add_message(t("explore.no_locked_door"))
        return None

    if mode == "pick":
        return PickLockAction(
            actor=game.player_id, dx=door_dir[0], dy=door_dir[1],
        )

    # Force mode: check inventory for tools/weapons that help
    inv = game.world.get_component(game.player_id, "Inventory")
    tool_id = None
    if inv:
        tools: list[tuple[int, str]] = []
        for eid in inv.slots:
            if game.world.has_component(eid, "ForceTool"):
                desc = game.world.get_component(eid, "Description")
                name = desc.name if desc else "???"
                tools.append((eid, name))
            elif game.world.has_component(eid, "Weapon"):
                weapon = game.world.get_component(eid, "Weapon")
                if weapon.type == "melee":
                    desc = game.world.get_component(eid, "Description")
                    name = desc.name if desc else "???"
                    tools.append((eid, name))

        if tools:
            # Add bare hands option
            tools.append((-1, t("explore.bare_hands")))
            selected = game.renderer.show_selection_menu(
                t("explore.force_with"), tools,
            )
            if selected is None:
                return None
            if selected != -1:
                tool_id = selected

    return ForceDoorAction(
        actor=game.player_id, dx=door_dir[0], dy=door_dir[1],
        tool=tool_id,
    )


def resolve_item_action(game: Game, data: dict) -> Action | None:
    """Convert a direct item_action message to an Action.

    Bypasses the menu flow — the client already selected the item.
    For throw/zap, a target menu is still shown.
    """
    action = data.get("action")
    item_id = data.get("item_id")
    if item_id is None:
        return None

    if action in ("quaff", "use"):
        return UseItemAction(actor=game.player_id, item=item_id)

    if action == "equip":
        return EquipAction(actor=game.player_id, item=item_id)

    if action == "unequip":
        return UnequipAction(actor=game.player_id, item=item_id)

    if action == "drop":
        return DropAction(actor=game.player_id, item=item_id)

    if action == "throw":
        target_id = game.renderer.show_target_menu(
            game.world, game.level, game.player_id,
            title=t("ui.throw_target"),
        )
        if target_id is None:
            return None
        return ThrowAction(
            actor=game.player_id, item=item_id, target=target_id,
        )

    if action == "zap":
        target_id = game.renderer.show_target_menu(
            game.world, game.level, game.player_id,
            title=t("ui.throw_target"),
        )
        if target_id is None:
            return None
        return ZapAction(
            actor=game.player_id, item=item_id, target=target_id,
        )

    return None
