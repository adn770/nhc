"""Input dispatch: translate player intents into Action objects.

These functions were extracted from Game to reduce game.py size.
Each takes the Game instance as first argument for access to
world, player_id, level, and renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.core.actions import (
    CloseDoorAction,
    DigAction,
    DigFloorAction,
    DigFloorMissAction,
    DismissAction,
    DropAction,
    EquipAction,
    ForceDoorAction,
    GiveItemAction,
    PickLockAction,
    PickupItemAction,
    ThrowAction,
    UnequipAction,
    UseItemAction,
    ZapAction,
    get_hired_henchmen,
)
from nhc.dungeon.model import Terrain
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

    # Check own tile and 4 cardinal directions for a locked door
    door_dir = None
    for dx, dy in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
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


def find_close_door_action(game: Game) -> Action | None:
    """Find an adjacent open door and return a CloseDoorAction.

    Checks own tile and the four cardinal neighbours. If no open door
    is found, shows a user message and returns None.
    """
    pos = game.world.get_component(game.player_id, "Position")
    if not pos or not game.level:
        return None

    for dx, dy in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
        tile = game.level.tile_at(pos.x + dx, pos.y + dy)
        if not tile or tile.feature != "door_open":
            continue
        action = CloseDoorAction(
            actor=game.player_id, dx=dx, dy=dy,
        )
        # Skip doors blocked by creatures; keep looking.
        tx, ty = pos.x + dx, pos.y + dy
        blocked = False
        for eid, other in game.world.query("Position"):
            if other is None or eid == game.player_id:
                continue
            if other.x == tx and other.y == ty and (
                game.world.has_component(eid, "AI")
                or game.world.has_component(eid, "BlocksMovement")
            ):
                blocked = True
                break
        if not blocked:
            return action

    game.renderer.add_message(t("explore.no_open_door"))
    return None


_DIRECTIONS = {
    "North": (0, -1),
    "South": (0, 1),
    "West": (-1, 0),
    "East": (1, 0),
}


def find_dig_action(
    game: Game, data: object = None,
) -> Action | None:
    """Find an adjacent wall (or void) to dig through.

    *data* may be a ``[dx, dy]`` pair sent by the client — used by
    autodig so the player can walk into a wall/void and the client
    picks the exact direction.  Without *data*, the classic flow
    scans cardinals and prompts when multiple walls are adjacent.
    """
    pos = game.world.get_component(game.player_id, "Position")
    if not pos or not game.level:
        return None

    # Check the player has a DiggingTool equipped as weapon
    equip = game.world.get_component(game.player_id, "Equipment")
    if not equip or equip.weapon is None:
        game.renderer.add_message(t("explore.dig_no_tool"))
        return None
    if not game.world.has_component(equip.weapon, "DiggingTool"):
        game.renderer.add_message(t("explore.dig_no_tool"))
        return None

    _DIGGABLE = (Terrain.WALL, Terrain.VOID)

    # Directed dispatch (autodig): the client already picked the
    # exact adjacent tile.  Honour it without showing a menu.
    # Autodig never triggers floor digging.
    if (isinstance(data, (list, tuple)) and len(data) == 2
            and all(isinstance(v, (int, float)) for v in data)):
        dx, dy = int(data[0]), int(data[1])
        target = game.level.tile_at(pos.x + dx, pos.y + dy)
        if target is None or target.terrain not in _DIGGABLE:
            return None
        return DigAction(actor=game.player_id, dx=dx, dy=dy)

    # Scan cardinal directions for adjacent diggable walls
    diggable: list[tuple[str, tuple[int, int]]] = []
    for label, (dx, dy) in _DIRECTIONS.items():
        tile = game.level.tile_at(pos.x + dx, pos.y + dy)
        if tile and tile.terrain == Terrain.WALL:
            diggable.append((label, (dx, dy)))

    # No adjacent walls → dig the floor instead (shovel only).
    # With a pick/mattock the player swings at the stone floor and
    # risks hurting themselves on the rebound.
    if not diggable:
        tile_here = game.level.tile_at(pos.x, pos.y)
        tool = game.world.get_component(equip.weapon, "DiggingTool")
        on_floor = (
            tile_here is not None
            and tile_here.terrain == Terrain.FLOOR
        )
        if on_floor and tool is not None and tool.can_dig_floor:
            return DigFloorAction(actor=game.player_id)
        if on_floor and tool is not None:
            return DigFloorMissAction(actor=game.player_id)
        game.renderer.add_message(t("explore.dig_no_wall"))
        return None

    if len(diggable) == 1:
        dx, dy = diggable[0][1]
        return DigAction(actor=game.player_id, dx=dx, dy=dy)

    # Multiple walls: ask the player for a direction
    options = [(i, label) for i, (label, _) in enumerate(diggable)]
    selected = game.renderer.show_selection_menu(
        t("explore.dig_which"), options,
    )
    if selected is None:
        return None
    dx, dy = diggable[selected][1]
    return DigAction(actor=game.player_id, dx=dx, dy=dy)


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

    if action == "give":
        henchmen = get_hired_henchmen(game.world, game.player_id)
        if not henchmen:
            return None
        hench_items = []
        for hid in henchmen:
            desc = game.world.get_component(hid, "Description")
            name = desc.name if desc else "Henchman"
            hench_items.append((hid, name))
        if len(hench_items) == 1:
            hid = hench_items[0][0]
        else:
            hid = game.renderer.show_selection_menu(
                t("henchman.give_prompt"), hench_items,
            )
        if hid is None:
            return None
        return GiveItemAction(
            actor=game.player_id, henchman_id=hid, item_id=item_id,
        )

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


def find_give_action(game: "Game") -> "Action | None":
    """Show menus to give an item from inventory to a henchman."""
    henchmen = get_hired_henchmen(game.world, game.player_id)
    if not henchmen:
        game.renderer.add_message("No henchmen in your party.")
        return None

    # Select henchman
    hench_items = []
    for hid in henchmen:
        desc = game.world.get_component(hid, "Description")
        name = desc.name if desc else "Henchman"
        hench_items.append((hid, name))

    if len(hench_items) == 1:
        hid = hench_items[0][0]
    else:
        hid = game.renderer.show_selection_menu(
            t("henchman.give_prompt"), hench_items,
        )
    if hid is None:
        return None

    # Select item from player inventory
    item_id = game.renderer.show_inventory_menu(
        game.world, game.player_id,
    )
    if item_id is None:
        return None

    return GiveItemAction(
        actor=game.player_id, henchman_id=hid, item_id=item_id,
    )


def find_dismiss_action(game: "Game") -> "Action | None":
    """Show menu to dismiss a hired henchman."""
    henchmen = get_hired_henchmen(game.world, game.player_id)
    if not henchmen:
        game.renderer.add_message("No henchmen in your party.")
        return None

    hench_items = []
    for hid in henchmen:
        desc = game.world.get_component(hid, "Description")
        name = desc.name if desc else "Henchman"
        hench_items.append((hid, name))

    if len(hench_items) == 1:
        hid = hench_items[0][0]
    else:
        hid = game.renderer.show_selection_menu(
            t("henchman.dismiss_prompt"), hench_items,
        )
    if hid is None:
        return None

    return DismissAction(
        actor=game.player_id, henchman_id=hid,
    )
