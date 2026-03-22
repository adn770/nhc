"""Mummy — undead horror with rotting curse and fear aura. (BEB: Mòmia)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    FearAura,
    Health,
    MummyRot,
    Renderable,
    Stats,
    Undead,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("mummy")
def create_mummy() -> dict:
    return {
        "Renderable": Renderable(glyph="M", color="yellow", render_order=2),
        "Description": Description(
            name=t("creature.mummy.name"),
            short=t("creature.mummy.short"),
            long=t("creature.mummy.long"),
        ),
        "Stats": Stats(strength=4, dexterity=1),
        "Health": Health(current=25, maximum=25),
        "Weapon": Weapon(damage="1d8"),
        "MummyRot": MummyRot(),
        "FearAura": FearAura(radius=3, save_dc=12),
        "AI": AI(behavior="aggressive_melee", morale=12),
        "BlocksMovement": BlocksMovement(),
        "Undead": Undead(),
    }
