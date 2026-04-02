"""Melee combat and special attack actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.core.actions._base import Action, _closed_door_blocks
from nhc.core.actions._helpers import _entity_name, _get_armor_magic, _msg
from nhc.core.events import (
    CreatureAttacked,
    CreatureDied,
    Event,
    MessageEvent,
)
from nhc.utils.spatial import chebyshev
from nhc.entities.components import (
    Cursed,
    Description,
    MummyRot,
    Poison,
    Position,
    Renderable,
    StatusEffect,
)
from nhc.i18n import t
from nhc.rules.combat import apply_damage, heal, is_dead, resolve_melee_attack
from nhc.rules.loot import generate_loot
from nhc.utils.rng import d20, roll_dice
from nhc.utils.spatial import adjacent

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)


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
        if not adjacent(apos.x, apos.y, tpos.x, tpos.y):
            return False
        if _closed_door_blocks(level, apos.x, apos.y, tpos.x, tpos.y):
            return False
        return True

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
                    text=_msg("combat.petrified", world,
                              target=self.actor),
                ))
                return events
            events.append(MessageEvent(
                text=_msg("combat.petrify_saved", world,
                          target=self.actor),
            ))

        # Invisible target: attacker misses automatically
        t_status_pre = world.get_component(self.target, "StatusEffect")
        if t_status_pre and t_status_pre.invisible > 0:
            events.append(MessageEvent(
                text=_msg("combat.miss_invisible", world,
                          target=self.target),
            ))
            return events

        # Get weapon damage: inline Weapon (creatures) > equipped Weapon (player)
        weapon_damage = "1d4"  # Unarmed fallback
        weapon_magic = 0
        inline_wpn = world.get_component(self.actor, "Weapon")
        if inline_wpn:
            weapon_damage = inline_wpn.damage
            weapon_magic = inline_wpn.magic_bonus
        else:
            equip = world.get_component(self.actor, "Equipment")
            if equip and equip.weapon is not None:
                wpn = world.get_component(equip.weapon, "Weapon")
                if wpn:
                    weapon_damage = wpn.damage
                    weapon_magic = wpn.magic_bonus

        # Target armor magic bonus
        armor_magic = _get_armor_magic(world, self.target)

        hit, damage = resolve_melee_attack(
            a_stats, t_stats, weapon_damage,
            attack_bonus=weapon_magic, damage_bonus=weapon_magic,
            armor_bonus=armor_magic,
        )
        logger.debug(
            "Melee: %s->%s wpn=%s hit=%s dmg=%d",
            attacker_name, target_name, weapon_damage, hit, damage,
        )

        # RequiresMagicWeapon: non-enchanted weapons deal 0 damage
        if hit and world.has_component(self.target, "RequiresMagicWeapon"):
            weapon_is_magic = False
            if inline_wpn:
                weapon_is_magic = world.has_component(self.actor, "Enchanted")
            else:
                equip = world.get_component(self.actor, "Equipment")
                if equip and equip.weapon is not None:
                    weapon_is_magic = world.has_component(
                        equip.weapon, "Enchanted",
                    )
            if not weapon_is_magic:
                events.append(MessageEvent(
                    text=_msg("combat.magic_weapon_needed", world,
                              target=self.target),
                ))
                hit = False
                damage = 0

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
                text=_msg("combat.mirror_absorbed", world,
                          target=self.target,
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
                text=_msg("combat.hit", world,
                          actor=self.actor, target=self.target,
                          damage=actual),
            ))

            # Attacking while invisible breaks the effect
            if a_status and a_status.invisible > 0:
                a_status.invisible = 0

            # DrainTouch: drain XP and reduce max HP on player
            if world.has_component(self.actor, "DrainTouch"):
                player = world.get_component(self.target, "Player")
                if player and t_health.maximum > 1:
                    t_health.maximum = max(1, t_health.maximum - 1)
                    t_health.current = min(
                        t_health.current, t_health.maximum,
                    )
                    player.xp = max(0, player.xp - 5)
                    events.append(MessageEvent(
                        text=_msg("combat.drained", world,
                                  actor=self.actor, target=self.target),
                    ))

            # VenomousStrike: apply poison on hit
            if world.has_component(self.actor, "VenomousStrike"):
                if not world.has_component(self.target, "Poison"):
                    world.add_component(
                        self.target, "Poison",
                        Poison(damage_per_turn=1, turns_remaining=3),
                    )
                    events.append(MessageEvent(
                        text=_msg("combat.poisoned", world,
                                  target=self.target),
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
                    text=_msg("combat.blood_drain", world,
                              actor=self.actor, target=self.target,
                              damage=drain_actual),
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
                        text=_msg("combat.petrify_touch", world,
                                  target=self.target),
                    ))

            # FrostBreath: extra cold damage on hit
            fb = world.get_component(self.actor, "FrostBreath")
            if fb:
                cold = roll_dice(fb.dice)
                cold_actual = apply_damage(t_health, cold)
                events.append(MessageEvent(
                    text=_msg("combat.frost_breath", world,
                              actor=self.actor, target=self.target,
                              damage=cold_actual),
                ))

            # CharmTouch: charm the target (like dryad)
            if world.has_component(self.actor, "CharmTouch"):
                if not world.has_component(self.target, "Undead"):
                    if t_status is None:
                        world.add_component(
                            self.target, "StatusEffect",
                            StatusEffect(charmed=9),
                        )
                    else:
                        t_status.charmed = 9
                    events.append(MessageEvent(
                        text=_msg("combat.charm_touch", world,
                                  target=self.target),
                    ))

            # MummyRot: curse the target with a slow HP-draining rot
            if world.has_component(self.actor, "MummyRot"):
                if not world.has_component(self.target, "Cursed"):
                    world.add_component(
                        self.target, "Cursed",
                        Cursed(ticks_until_drain=2),
                    )
                    events.append(MessageEvent(
                        text=_msg("combat.mummy_rot", world,
                                  target=self.target),
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
                        chosen = magic_items[0]
                        c_desc = world.get_component(chosen, "Description")
                        c_name = c_desc.name if c_desc else "item"
                        t_inv.slots.remove(chosen)
                        world.destroy_entity(chosen)
                        events.append(MessageEvent(
                            text=_msg("combat.disenchant", world,
                                      actor=self.actor, target=self.target,
                                      item=c_name),
                        ))

            if is_dead(t_health):
                # Player death is handled by the game loop (god mode
                # restores HP there).  Skip corpse/loot/destroy for
                # the player entirely.
                is_player = world.has_component(self.target, "Player")

                if not is_player:
                    logger.info(
                        "%s killed %s (actor=%d, target=%d)",
                        attacker_name, target_name,
                        self.actor, self.target,
                    )
                    events.append(CreatureDied(
                        entity=self.target, killer=self.actor,
                        max_hp=t_health.maximum,
                    ))
                    events.append(MessageEvent(
                        text=_msg("combat.slain", world,
                                  actor=self.actor, target=self.target),
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
                                    text=_msg("combat.drops", world,
                                              target=self.target,
                                              items=", ".join(names)),
                                ))

                    # Leave a corpse marker, then destroy
                    if tpos:
                        corpse_name = t("combat.corpse", name=target_name)
                        world.create_entity({
                            "Position": Position(
                                x=tpos.x, y=tpos.y,
                                level_id=tpos.level_id,
                            ),
                            "Renderable": Renderable(
                                glyph="%", color="bright_red",
                                render_order=0,
                            ),
                            "Description": Description(
                                name=corpse_name,
                                short=corpse_name,
                            ),
                        })

                    world.destroy_entity(self.target)
        else:
            events.append(CreatureAttacked(
                attacker=self.actor, target=self.target,
                damage=0, hit=False,
            ))
            events.append(MessageEvent(
                text=_msg("combat.miss", world,
                          actor=self.actor, target=self.target),
            ))

        return events


class BansheeWailAction(Action):
    """Banshee wail: every humanoid in range must save CON or die."""

    def __init__(self, actor: int, player_id: int) -> None:
        super().__init__(actor)
        self.player_id = player_id

    async def validate(self, world: "World", level: "Level") -> bool:
        return True

    async def execute(self, world: "World", level: "Level") -> list[Event]:
        events: list[Event] = []
        attacker_name = _entity_name(world, self.actor)
        events.append(MessageEvent(
            text=t("combat.banshee_wail", creature=attacker_name),
        ))

        wail = world.get_component(self.actor, "DeathWail")
        if not wail:
            return events

        a_pos = world.get_component(self.actor, "Position")
        if not a_pos:
            return events

        p_pos = world.get_component(self.player_id, "Position")
        p_stats = world.get_component(self.player_id, "Stats")
        p_health = world.get_component(self.player_id, "Health")
        if p_pos and p_stats and p_health:
            dist = chebyshev(a_pos.x, a_pos.y, p_pos.x, p_pos.y)
            if dist <= wail.radius:
                if d20() + p_stats.constitution < wail.save_dc:
                    p_health.current = 0
                    events.append(MessageEvent(
                        text=_msg("combat.banshee_kills", world,
                                  target=self.player_id),
                    ))
                    events.append(CreatureDied(
                        entity=self.player_id, killer=self.actor,
                        max_hp=p_health.maximum,
                    ))
                else:
                    events.append(MessageEvent(
                        text=_msg("combat.banshee_saved", world,
                                  target=self.player_id),
                    ))
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
