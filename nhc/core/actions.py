"""Action resolution pipeline."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from nhc.core.events import (
    CreatureAttacked,
    CreatureDied,
    DoorOpened,
    Event,
    GameWon,
    ItemPickedUp,
    ItemUsed,
    MessageEvent,
    TrapTriggered,
)
from nhc.entities.components import (
    AI,
    BloodDrain,
    BlocksMovement,
    Consumable,
    Description,
    DisenchantTouch,
    Equipment,
    FrostBreath,
    Health,
    Inventory,
    LootTable,
    PetrifyingTouch,
    Poison,
    Position,
    Renderable,
    Stats,
    StatusEffect,
    Trap,
    Undead,
    Weapon,
)
from nhc.i18n import t
from nhc.rules.combat import apply_damage, heal, is_dead, resolve_melee_attack
from nhc.rules.loot import generate_loot
from nhc.utils.rng import d20, roll_dice
from nhc.utils.spatial import adjacent

if TYPE_CHECKING:
    from nhc.core.ecs import EntityId, World
    from nhc.dungeon.model import Level


class Action(abc.ABC):
    """Base action. All player/creature actions inherit from this."""

    def __init__(self, actor: int) -> None:
        self.actor = actor

    @abc.abstractmethod
    async def validate(self, world: "World", level: "Level") -> bool:
        """Check if this action is valid in the current state."""

    @abc.abstractmethod
    async def execute(self, world: "World", level: "Level") -> list[Event]:
        """Perform the action, returning resulting events."""


class WaitAction(Action):
    """Do nothing, pass the turn."""

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        return []


class MoveAction(Action):
    """Move in a direction."""

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)
        if not tile:
            return False
        if tile.feature == "door_closed":
            return True
        return tile.walkable

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        nx, ny = pos.x + self.dx, pos.y + self.dy
        tile = level.tile_at(nx, ny)

        # Auto-open closed doors
        if tile.feature == "door_closed":
            tile.feature = "door_open"
            events.append(DoorOpened(entity=self.actor, x=nx, y=ny))
            actor_desc = _entity_name(world, self.actor)
            events.append(MessageEvent(
                text=t("explore.open_door", actor=actor_desc),
            ))
            return events

        # Check for blocking creatures at target
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                return []

        # Move
        pos.x = nx
        pos.y = ny

        # Check for traps
        events += _check_traps(world, level, self.actor, nx, ny)

        # Announce items on ground (player only)
        if world.has_component(self.actor, "Player"):
            events += _announce_ground_items(world, nx, ny, self.actor)

        return events


class MeleeAttackAction(Action):
    """Melee attack against a target."""

    def __init__(self, actor: int, target: int) -> None:
        super().__init__(actor)
        self.target = target

    async def validate(self, world: "World", level: "Level") -> bool:
        apos = world.get_component(self.actor, "Position")
        tpos = world.get_component(self.target, "Position")
        if not apos or not tpos:
            return False
        return adjacent(apos.x, apos.y, tpos.x, tpos.y)

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []

        a_stats = world.get_component(self.actor, "Stats")
        t_stats = world.get_component(self.target, "Stats")
        t_health = world.get_component(self.target, "Health")

        if not a_stats or not t_stats or not t_health:
            return events

        attacker_name = _entity_name(world, self.actor)
        target_name = _entity_name(world, self.target)

        # PetrifyingGaze: attacker must save DEX 12 or be paralyzed
        if world.has_component(self.target, "PetrifyingGaze"):
            if d20() + a_stats.dexterity < 12:
                a_status = world.get_component(self.actor, "StatusEffect")
                if a_status is None:
                    world.add_component(
                        self.actor, "StatusEffect",
                        StatusEffect(paralyzed=9),
                    )
                else:
                    a_status.paralyzed = 9
                events.append(MessageEvent(
                    text=t("combat.petrified", target=attacker_name),
                ))
                return events
            events.append(MessageEvent(
                text=t("combat.petrify_saved", target=attacker_name),
            ))

        # Invisible target: attacker misses automatically
        t_status_pre = world.get_component(self.target, "StatusEffect")
        if t_status_pre and t_status_pre.invisible > 0:
            events.append(MessageEvent(
                text=t("combat.miss_invisible", target=target_name),
            ))
            return events

        # Get weapon damage: inline Weapon (creatures) > equipped Weapon (player)
        weapon_damage = "1d4"  # Unarmed fallback
        inline_wpn = world.get_component(self.actor, "Weapon")
        if inline_wpn:
            weapon_damage = inline_wpn.damage
        else:
            equip = world.get_component(self.actor, "Equipment")
            if equip and equip.weapon is not None:
                wpn = world.get_component(equip.weapon, "Weapon")
                if wpn:
                    weapon_damage = wpn.damage

        hit, damage = resolve_melee_attack(a_stats, t_stats, weapon_damage)

        # Blessed attacker: +1 damage on a hit
        a_status = world.get_component(self.actor, "StatusEffect")
        if hit and a_status and a_status.blessed > 0:
            damage += 1

        # Sleeping targets are auto-hit and wake on damage
        t_status = world.get_component(self.target, "StatusEffect")
        if t_status and t_status.sleeping > 0:
            t_status.sleeping = 0
            hit = True

        # Mirror images absorb hits before real damage
        if hit and t_status and t_status.mirror_images > 0:
            t_status.mirror_images -= 1
            events.append(MessageEvent(
                text=t("combat.mirror_absorbed", target=target_name,
                       remaining=t_status.mirror_images),
            ))
            return events

        if hit:
            actual = apply_damage(t_health, damage)
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=actual, hit=True,
            ))
            events.append(MessageEvent(
                text=t("combat.hit", attacker=attacker_name,
                       target=target_name, damage=actual),
            ))

            # Attacking while invisible breaks the effect
            if a_status and a_status.invisible > 0:
                a_status.invisible = 0

            # DrainTouch: drain XP and reduce max HP on player
            if world.has_component(self.actor, "DrainTouch"):
                player = world.get_component(self.target, "Player")
                if player and t_health.maximum > 1:
                    t_health.maximum = max(1, t_health.maximum - 1)
                    t_health.current = min(t_health.current, t_health.maximum)
                    player.xp = max(0, player.xp - 5)
                    events.append(MessageEvent(
                        text=t("combat.drained", attacker=attacker_name,
                               target=target_name),
                    ))

            # VenomousStrike: apply poison on hit
            if world.has_component(self.actor, "VenomousStrike"):
                if not world.has_component(self.target, "Poison"):
                    world.add_component(
                        self.target, "Poison",
                        Poison(damage_per_turn=1, turns_remaining=3),
                    )
                    events.append(MessageEvent(
                        text=t("combat.poisoned", target=target_name),
                    ))

            # BloodDrain: drain HP and heal self
            bd = world.get_component(self.actor, "BloodDrain")
            if bd:
                drain = bd.drain_per_hit
                drain_actual = apply_damage(t_health, drain)
                a_health = world.get_component(self.actor, "Health")
                if a_health:
                    heal(a_health, drain)
                events.append(MessageEvent(
                    text=t("combat.blood_drain", attacker=attacker_name,
                           target=target_name, damage=drain_actual),
                ))

            # PetrifyingTouch: target saves DEX 12 or paralyzed
            if world.has_component(self.actor, "PetrifyingTouch"):
                if d20() + t_stats.dexterity < 12:
                    if t_status is None:
                        world.add_component(
                            self.target, "StatusEffect",
                            StatusEffect(paralyzed=9),
                        )
                    else:
                        t_status.paralyzed = 9
                    events.append(MessageEvent(
                        text=t("combat.petrify_touch", target=target_name),
                    ))

            # FrostBreath: extra cold damage on hit
            fb = world.get_component(self.actor, "FrostBreath")
            if fb:
                cold = roll_dice(fb.dice)
                cold_actual = apply_damage(t_health, cold)
                events.append(MessageEvent(
                    text=t("combat.frost_breath", attacker=attacker_name,
                           target=target_name, damage=cold_actual),
                ))

            # DisenchantTouch: destroy one consumable in target's inventory
            if world.has_component(self.actor, "DisenchantTouch"):
                t_inv = world.get_component(self.target, "Inventory")
                if t_inv:
                    magic_items = [
                        eid for eid in t_inv.slots
                        if world.has_component(eid, "Consumable")
                    ]
                    if magic_items:
                        from nhc.utils.rng import roll_dice as _rd
                        chosen = magic_items[0]
                        c_desc = world.get_component(chosen, "Description")
                        c_name = c_desc.name if c_desc else "item"
                        t_inv.slots.remove(chosen)
                        world.destroy_entity(chosen)
                        events.append(MessageEvent(
                            text=t("combat.disenchant", attacker=attacker_name,
                                   target=target_name, item=c_name),
                        ))

            if is_dead(t_health):
                events.append(CreatureDied(
                    entity=self.target, killer=self.actor,
                ))
                events.append(MessageEvent(
                    text=t("combat.slain", target=target_name),
                ))

                # Drop loot before destroying
                tpos = world.get_component(self.target, "Position")
                loot = world.get_component(self.target, "LootTable")
                if loot and tpos:
                    dropped = generate_loot(
                        world, loot, tpos.x, tpos.y, tpos.level_id,
                    )
                    if dropped:
                        names = []
                        for did in dropped:
                            d = world.get_component(did, "Description")
                            if d:
                                names.append(d.name)
                        if names:
                            events.append(MessageEvent(
                                text=t("combat.drops", target=target_name,
                                       items=", ".join(names)),
                            ))

                # Leave a corpse marker, then destroy
                if tpos:
                    corpse_name = f"{target_name} corpse"
                    world.create_entity({
                        "Position": Position(
                            x=tpos.x, y=tpos.y, level_id=tpos.level_id,
                        ),
                        "Renderable": Renderable(
                            glyph="%", color="bright_red", render_order=0,
                        ),
                        "Description": Description(name=corpse_name),
                    })

                world.destroy_entity(self.target)
        else:
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=0, hit=False,
            ))
            events.append(MessageEvent(
                text=t("combat.miss", attacker=attacker_name,
                       target=target_name),
            ))

        return events


class PickupItemAction(Action):
    """Pick up an item from the ground."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item
        self.full = False

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv:
            return False
        if len(inv.slots) >= inv.max_slots:
            self.full = True
            return False
        item_pos = world.get_component(self.item, "Position")
        actor_pos = world.get_component(self.actor, "Position")
        if not item_pos or not actor_pos:
            return False
        return item_pos.x == actor_pos.x and item_pos.y == actor_pos.y

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")

        inv.slots.append(self.item)
        # Remove position so it's no longer on the map
        world.add_component(self.item, "Position", None)

        item_name = _entity_name(world, self.item)
        events.append(ItemPickedUp(entity=self.actor, item=self.item))
        events.append(MessageEvent(
            text=t("item.picked_up", item=item_name),
        ))

        # Auto-equip weapon if nothing equipped
        wpn = world.get_component(self.item, "Weapon")
        equip = world.get_component(self.actor, "Equipment")
        if wpn and equip and equip.weapon is None:
            equip.weapon = self.item
            events.append(MessageEvent(
                text=t("item.equipped", item=item_name),
            ))

        return events


class UseItemAction(Action):
    """Use a consumable item from inventory."""

    def __init__(self, actor: int, item: int) -> None:
        super().__init__(actor)
        self.item = item

    async def validate(self, world: "World", level: "Level") -> bool:
        inv = world.get_component(self.actor, "Inventory")
        if not inv or self.item not in inv.slots:
            return False
        consumable = world.get_component(self.item, "Consumable")
        return consumable is not None

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        inv = world.get_component(self.actor, "Inventory")
        consumable = world.get_component(self.item, "Consumable")
        item_name = _entity_name(world, self.item)

        consumed = True

        if consumable.effect == "heal":
            health = world.get_component(self.actor, "Health")
            if health:
                if health.current >= health.maximum:
                    events.append(MessageEvent(
                        text=t("item.full_health"),
                    ))
                    return events
                amount = roll_dice(consumable.dice)
                actual = heal(health, amount)
                events.append(ItemUsed(
                    entity=self.actor, item=self.item, effect="heal",
                ))
                events.append(MessageEvent(
                    text=t("item.quaff_heal", item=item_name,
                           amount=actual),
                ))

        elif consumable.effect == "damage_nearest":
            events += _use_damage_nearest(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "sleep":
            events += _use_sleep(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "magic_missile":
            events += _use_magic_missile(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "hold_person":
            events += _use_hold_person(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "fireball":
            events += _use_fireball(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "web":
            events += _use_web(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "charm_person":
            events += _use_charm_person(
                world, level, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "bless":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "blessed",
                t("item.bless_cast"), t("item.bless_active"),
            )

        elif consumable.effect == "mirror_image":
            events += _use_mirror_image(
                world, self.actor, self.item, consumable, item_name,
            )

        elif consumable.effect == "invisibility":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "invisible",
                t("item.invis_cast"), t("item.invis_active"),
            )

        elif consumable.effect == "haste":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "hasted",
                t("item.haste_cast"), t("item.haste_active"),
            )

        elif consumable.effect == "protection_evil":
            events += _use_self_buff(
                world, self.actor, self.item, consumable, "protected",
                t("item.protect_cast"), t("item.protect_active"),
            )

        else:
            events.append(MessageEvent(
                text=t("item.nothing_happens"),
            ))
            consumed = False

        if not consumed:
            return events

        # Remove item from inventory and world
        if self.item in inv.slots:
            inv.slots.remove(self.item)
        # Unequip if it was equipped
        equip = world.get_component(self.actor, "Equipment")
        if equip and equip.weapon == self.item:
            equip.weapon = None
        world.destroy_entity(self.item)

        return events


class DescendStairsAction(Action):
    """Descend to the next dungeon level."""

    async def validate(self, world: "World", level: "Level") -> bool:
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return False
        tile = level.tile_at(pos.x, pos.y)
        return tile is not None and tile.feature == "stairs_down"

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        from nhc.core.events import LevelEntered
        return [
            LevelEntered(
                entity=self.actor,
                level_id=level.id,
                depth=level.depth + 1,
            ),
            MessageEvent(text=t("explore.descend")),
        ]


class LookAction(Action):
    """Examine the current tile and surroundings."""

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        pos = world.get_component(self.actor, "Position")
        if not pos:
            return events

        tile = level.tile_at(pos.x, pos.y)

        # Describe tile feature
        if tile and tile.feature:
            fname = t(f"feature.{tile.feature}")
            # Fallback to raw feature name if no translation
            if fname == f"feature.{tile.feature}":
                fname = tile.feature
            events.append(MessageEvent(
                text=t("explore.see_feature", feature=fname),
            ))

        # Describe items on tile
        items = _items_at(world, pos.x, pos.y, self.actor)
        for eid in items:
            desc = world.get_component(eid, "Description")
            if desc and desc.long:
                events.append(MessageEvent(text=desc.long))
            elif desc:
                events.append(MessageEvent(
                    text=t("explore.see_item", item=desc.short),
                ))

        # Describe visible creatures
        for eid, _, cpos in world.query("AI", "Position"):
            if cpos is None:
                continue
            ctile = level.tile_at(cpos.x, cpos.y)
            if ctile and ctile.visible:
                desc = world.get_component(eid, "Description")
                health = world.get_component(eid, "Health")
                if desc:
                    hp_desc = ""
                    if health:
                        pct = health.current / health.maximum
                        if pct >= 1.0:
                            hp_desc = t("health_status.uninjured")
                        elif pct > 0.5:
                            hp_desc = t("health_status.lightly_wounded")
                        elif pct > 0.25:
                            hp_desc = t("health_status.badly_wounded")
                        else:
                            hp_desc = t("health_status.near_death")
                    events.append(MessageEvent(
                        text=t("explore.see_creature",
                               creature=desc.short, status=hp_desc),
                    ))

        if not events:
            events.append(MessageEvent(text=t("explore.nothing_special")))

        return events


class BumpAction(Action):
    """Smart directional action: attack, open door, or move."""

    def __init__(self, actor: int, dx: int, dy: int) -> None:
        super().__init__(actor)
        self.dx = dx
        self.dy = dy

    def resolve(self, world: "World", level: "Level") -> Action:
        """Convert bump into a concrete action."""
        pos = world.get_component(self.actor, "Position")
        nx, ny = pos.x + self.dx, pos.y + self.dy

        # Check for creature at target: attack
        for eid, _, bpos in world.query("BlocksMovement", "Position"):
            if bpos.x == nx and bpos.y == ny and eid != self.actor:
                return MeleeAttackAction(actor=self.actor, target=eid)

        # Otherwise: move (handles doors internally)
        return MoveAction(actor=self.actor, dx=self.dx, dy=self.dy)

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        resolved = self.resolve(world, level)
        if await resolved.validate(world, level):
            return await resolved.execute(world, level)
        return []


# ── Helpers ──────────────────────────────────────────────────────────


def _entity_name(world: "World", eid: int) -> str:
    """Get display name for an entity."""
    desc = world.get_component(eid, "Description")
    if desc and desc.name:
        return desc.name
    player = world.get_component(eid, "Player")
    if player is not None:
        return t("game.player_name")
    return "something"


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
        name = desc.short if desc else "something"
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


def _check_traps(
    world: "World", level: "Level", entity_id: int, x: int, y: int,
) -> list[Event]:
    """Check if stepping on a tile triggers a trap entity."""
    events: list[Event] = []

    for eid, trap, tpos in world.query("Trap", "Position"):
        if tpos is None or tpos.x != x or tpos.y != y:
            continue
        if trap.triggered:
            continue

        # DEX save vs trap DC
        stats = world.get_component(entity_id, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        save_roll = d20()

        entity_name = _entity_name(world, entity_id)
        trap_desc = world.get_component(eid, "Description")
        trap_name = trap_desc.name if trap_desc else "a trap"

        if save_roll + dex_bonus >= trap.dc:
            events.append(MessageEvent(
                text=t("trap.avoided", entity=entity_name,
                       trap=trap_name),
            ))
        else:
            damage = roll_dice(trap.damage)
            health = world.get_component(entity_id, "Health")
            if health:
                actual = apply_damage(health, damage)
                events.append(TrapTriggered(
                    entity=entity_id, damage=actual, trap_name=trap_name,
                ))
                events.append(MessageEvent(
                    text=t("trap.triggered", entity=entity_name,
                           trap=trap_name, damage=actual),
                ))

        trap.triggered = True
        trap.hidden = False

    return events


def _use_sleep(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Put visible creatures to sleep (2d8 total HD, weakest first)."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.sleep_cast")))

    total_hd = roll_dice(consumable.dice)

    # Gather visible AI creatures, sorted by HP ascending (weakest first)
    candidates: list[tuple[int, int]] = []
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        health = world.get_component(eid, "Health")
        if health:
            candidates.append((health.current, eid))
    candidates.sort()

    hd_spent = 0
    affected = 0
    for hp, eid in candidates:
        if hd_spent >= total_hd:
            break
        health = world.get_component(eid, "Health")
        hd = max(1, health.maximum // 4)
        if hd_spent + hd > total_hd:
            break
        hd_spent += hd
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect", StatusEffect(sleeping=9))
        else:
            status.sleeping = 9
        name = _entity_name(world, eid)
        events.append(MessageEvent(text=t("item.sleep_affects", target=name)))
        affected += 1

    if affected == 0:
        events.append(MessageEvent(text=t("item.sleep_none")))

    events.append(ItemUsed(entity=actor, item=item, effect="sleep"))
    return events


def _use_magic_missile(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Auto-hit the nearest visible creature for 1d6+1."""
    from nhc.utils.spatial import chebyshev
    events: list[Event] = []

    apos = world.get_component(actor, "Position")
    if not apos:
        return events

    best_eid = None
    best_dist = 999
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if tile and tile.visible:
            dist = chebyshev(apos.x, apos.y, cpos.x, cpos.y)
            if dist < best_dist:
                best_dist = dist
                best_eid = eid

    if best_eid is None:
        events.append(MessageEvent(text=t("item.no_target")))
        return events

    damage = roll_dice(consumable.dice)
    target_health = world.get_component(best_eid, "Health")
    target_name = _entity_name(world, best_eid)

    if target_health:
        actual = apply_damage(target_health, damage)
        events.append(ItemUsed(entity=actor, item=item, effect="magic_missile"))
        events.append(MessageEvent(
            text=t("item.missile_hits", target=target_name, damage=actual),
        ))
        if is_dead(target_health):
            events.append(CreatureDied(entity=best_eid, killer=actor))
            events.append(MessageEvent(
                text=t("combat.slain", target=target_name),
            ))
            world.destroy_entity(best_eid)

    return events


def _use_hold_person(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Paralyze 1d4 visible humanoids for consumable.dice turns."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.hold_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = 9

    humanoids = []
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        humanoids.append(eid)

    if not humanoids:
        events.append(MessageEvent(text=t("item.hold_no_humanoids")))
        return events

    count = min(roll_dice("1d4"), len(humanoids))
    from nhc.utils.rng import get_rng
    targets = get_rng().sample(humanoids, count)

    for eid in targets:
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(
                eid, "StatusEffect", StatusEffect(paralyzed=duration),
            )
        else:
            status.paralyzed = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(text=t("item.hold_affects", target=name)))

    events.append(ItemUsed(entity=actor, item=item, effect="hold_person"))
    return events


def _use_fireball(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Hit all visible creatures for 3d6 (DEX save for half)."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.fireball_cast")))

    targets = []
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if tile and tile.visible:
            targets.append(eid)

    if not targets:
        events.append(MessageEvent(text=t("item.no_target")))
        return events

    base_damage = roll_dice(consumable.dice)
    dead_eids = []

    for eid in targets:
        health = world.get_component(eid, "Health")
        if not health:
            continue
        stats = world.get_component(eid, "Stats")
        dex_bonus = stats.dexterity if stats else 0
        dmg = max(1, base_damage // 2) if d20() + dex_bonus >= 12 else base_damage
        actual = apply_damage(health, dmg)
        name = _entity_name(world, eid)
        events.append(MessageEvent(
            text=t("item.fireball_hits", target=name, damage=actual),
        ))
        if is_dead(health):
            dead_eids.append(eid)

    events.append(ItemUsed(entity=actor, item=item, effect="fireball"))

    for eid in dead_eids:
        name = _entity_name(world, eid)
        events.append(CreatureDied(entity=eid, killer=actor))
        events.append(MessageEvent(text=t("combat.slain", target=name)))
        world.destroy_entity(eid)

    return events


def _use_damage_nearest(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Damage the nearest visible creature."""
    from nhc.utils.spatial import chebyshev
    events: list[Event] = []

    apos = world.get_component(actor, "Position")
    if not apos:
        return events

    # Find nearest creature with AI
    best_eid = None
    best_dist = 999
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if tile and tile.visible:
            dist = chebyshev(apos.x, apos.y, cpos.x, cpos.y)
            if dist < best_dist:
                best_dist = dist
                best_eid = eid

    if best_eid is None:
        events.append(MessageEvent(text=t("item.no_target")))
        return events

    damage = roll_dice(consumable.dice)
    target_health = world.get_component(best_eid, "Health")
    target_name = _entity_name(world, best_eid)

    if target_health:
        actual = apply_damage(target_health, damage)
        events.append(ItemUsed(
            entity=actor, item=item, effect="damage_nearest",
        ))
        events.append(MessageEvent(
            text=t("item.lightning_strike", item=item_name,
                   target=target_name, damage=actual),
        ))

        if is_dead(target_health):
            events.append(CreatureDied(entity=best_eid, killer=actor))
            events.append(MessageEvent(
                text=t("combat.destroyed", target=target_name),
            ))
            world.destroy_entity(best_eid)

    return events


def _use_web(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Entangle all visible creatures for consumable.dice turns."""
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.web_cast")))

    duration = roll_dice(consumable.dice)
    affected = 0

    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        status = world.get_component(eid, "StatusEffect")
        if status is None:
            world.add_component(eid, "StatusEffect", StatusEffect(webbed=duration))
        else:
            status.webbed = duration
        name = _entity_name(world, eid)
        events.append(MessageEvent(text=t("item.web_caught", target=name)))
        affected += 1

    if affected == 0:
        events.append(MessageEvent(text=t("item.no_target")))

    events.append(ItemUsed(entity=actor, item=item, effect="web"))
    return events


def _use_charm_person(
    world: "World",
    level: "Level",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Charm the nearest visible non-undead humanoid for consumable.dice turns."""
    from nhc.utils.spatial import chebyshev
    events: list[Event] = []
    events.append(MessageEvent(text=t("item.charm_cast")))

    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = 9

    apos = world.get_component(actor, "Position")
    if not apos:
        return events

    best_eid = None
    best_dist = 999
    for eid, _, cpos in world.query("AI", "Position"):
        if cpos is None:
            continue
        tile = level.tile_at(cpos.x, cpos.y)
        if not tile or not tile.visible:
            continue
        if world.has_component(eid, "Undead"):
            continue
        dist = chebyshev(apos.x, apos.y, cpos.x, cpos.y)
        if dist < best_dist:
            best_dist = dist
            best_eid = eid

    if best_eid is None:
        events.append(MessageEvent(text=t("item.charm_no_target")))
        return events

    status = world.get_component(best_eid, "StatusEffect")
    if status is None:
        world.add_component(best_eid, "StatusEffect", StatusEffect(charmed=duration))
    else:
        status.charmed = duration

    name = _entity_name(world, best_eid)
    events.append(MessageEvent(text=t("item.charm_affects", target=name)))
    events.append(ItemUsed(entity=actor, item=item, effect="charm_person"))
    return events


def _use_self_buff(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
    field: str,
    cast_msg: str,
    active_msg: str,
) -> list[Event]:
    """Apply a self-targeted buff (blessed/invisible/hasted/protected)."""
    events: list[Event] = []
    try:
        duration = int(consumable.dice)
    except ValueError:
        duration = roll_dice(consumable.dice)

    status = world.get_component(actor, "StatusEffect")
    if status is None:
        world.add_component(actor, "StatusEffect", StatusEffect(**{field: duration}))
    else:
        setattr(status, field, duration)

    events.append(MessageEvent(text=cast_msg))
    events.append(MessageEvent(text=active_msg))
    events.append(ItemUsed(entity=actor, item=item, effect=consumable.effect))
    return events


def _use_mirror_image(
    world: "World",
    actor: int,
    item: int,
    consumable: "Consumable",
    item_name: str,
) -> list[Event]:
    """Create 1d4 illusory duplicates; each absorbs one incoming hit."""
    events: list[Event] = []
    count = roll_dice(consumable.dice)

    status = world.get_component(actor, "StatusEffect")
    if status is None:
        world.add_component(actor, "StatusEffect",
                            StatusEffect(mirror_images=count))
    else:
        status.mirror_images = count

    events.append(MessageEvent(text=t("item.mirror_cast")))
    events.append(MessageEvent(text=t("item.mirror_images", count=count)))
    events.append(ItemUsed(entity=actor, item=item, effect="mirror_image"))
    return events


class ShriekAction(Action):
    """Shrieker emits a piercing shriek that wakes all sleeping creatures."""

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        attacker_name = _entity_name(world, self.actor)
        events.append(MessageEvent(
            text=t("combat.shrieker_shriek", creature=attacker_name),
        ))
        # Wake all sleeping creatures on this level
        for eid, status, _ in world.query("StatusEffect", "Position"):
            if status and status.sleeping > 0:
                status.sleeping = 0
                name = _entity_name(world, eid)
                events.append(MessageEvent(
                    text=t("combat.shriek_wakes", creature=name),
                ))
        return events
