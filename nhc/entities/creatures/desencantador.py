"""Desencantador (Disenchanter) — destroys magic items on touch. (BEB: Desencantador)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    DisenchantTouch,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("desencantador")
def create_desencantador() -> dict:
    return {
        "Renderable": Renderable(glyph="d", color="magenta", render_order=2),
        "Description": Description(
            name=t("creature.desencantador.name"),
            short=t("creature.desencantador.short"),
            long=t("creature.desencantador.long"),
        ),
        "Stats": Stats(strength=2, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d4"),
        "DisenchantTouch": DisenchantTouch(),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
    }
