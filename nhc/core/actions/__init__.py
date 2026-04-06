"""Action resolution pipeline.

This package re-exports all public and private names so that
``from nhc.core.actions import X`` continues to work everywhere.
"""

from __future__ import annotations

# -- Base classes and door helpers --
from nhc.core.actions._base import (
    Action,
    CustomAction,
    ImpossibleAction,
    WaitAction,
    _BLOCKING_DOOR_FEATURES,
    _closed_door_blocks,
    _crossing_door_edge,
)

# -- Shared helpers --
from nhc.core.actions._helpers import (
    _CATALAN_VOWELS,
    _announce_ground_items,
    _capitalize_first,
    _count_slots_used,
    _det_name,
    _entity_name,
    _get_armor_magic,
    _is_player,
    _item_slot_cost,
    _items_at,
    _msg,
)

# -- Trap functions --
from nhc.core.actions._traps import (
    _apply_trap_effect,
    _check_traps,
)

# -- Movement actions --
from nhc.core.actions._movement import (
    AscendStairsAction,
    BumpAction,
    DescendStairsAction,
    MoveAction,
)

# -- Combat actions --
from nhc.core.actions._combat import (
    BansheeWailAction,
    MeleeAttackAction,
    ShriekAction,
)

# -- Item actions --
from nhc.core.actions._items import (
    DropAction,
    EquipAction,
    PickupItemAction,
    UnequipAction,
    UseItemAction,
)

# -- Ranged actions --
from nhc.core.actions._ranged import (
    ThrowAction,
    ZapAction,
)

# -- Interaction actions --
from nhc.core.actions._interaction import (
    CloseDoorAction,
    DigAction,
    DigFloorAction,
    ForceDoorAction,
    LookAction,
    OpenChestAction,
    PickLockAction,
    SearchAction,
)

# -- Henchman actions --
from nhc.core.actions._henchman import (
    DismissAction,
    GiveItemAction,
    RecruitAction,
    get_hired_henchmen,
)

# -- Shop actions --
from nhc.core.actions._shop import (
    BuyAction,
    SellAction,
    ShopInteractAction,
)

# -- Spell helper functions --
from nhc.core.actions._spells import (
    _use_acid,
    _use_charm_person,
    _use_charm_snakes,
    _use_charging,
    _use_clairvoyance,
    _use_continual_light,
    _use_damage_nearest,
    _use_detect_evil,
    _use_detect_food,
    _use_detect_gold,
    _use_detect_magic,
    _use_dispel_magic,
    _use_enchant_armor,
    _use_enchant_weapon,
    _use_find_traps,
    _use_fireball,
    _use_hold_person,
    _use_magic_missile,
    _use_mirror_image,
    _use_phantasmal_force,
    _use_remove_fear,
    _use_self_buff,
    _use_sickness,
    _use_silence,
    _use_sleep,
    _use_teleport_self,
    _use_web,
)

__all__ = [
    # Base
    "Action",
    "CustomAction",
    "ImpossibleAction",
    "WaitAction",
    # Movement
    "AscendStairsAction",
    "BumpAction",
    "DescendStairsAction",
    "MoveAction",
    # Combat
    "BansheeWailAction",
    "MeleeAttackAction",
    "ShriekAction",
    # Items
    "DropAction",
    "EquipAction",
    "PickupItemAction",
    "UnequipAction",
    "UseItemAction",
    # Ranged
    "ThrowAction",
    "ZapAction",
    # Henchman
    "DismissAction",
    "GiveItemAction",
    "RecruitAction",
    # Shop
    "BuyAction",
    "SellAction",
    "ShopInteractAction",
    # Interaction
    "CloseDoorAction",
    "DigAction",
    "DigFloorAction",
    "ForceDoorAction",
    "LookAction",
    "OpenChestAction",
    "PickLockAction",
    "SearchAction",
]
