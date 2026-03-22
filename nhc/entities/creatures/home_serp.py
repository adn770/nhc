"""Home Serp (Snakeman) — serpentine humanoid warrior. (BEB: Home Serp)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


@EntityRegistry.register_creature("home_serp")
def create_home_serp() -> dict:
    return {
        "Renderable": Renderable(glyph="n", color="green", render_order=2),
        "Description": Description(
            name=t("creature.home_serp.name"),
            short=t("creature.home_serp.short"),
            long=t("creature.home_serp.long"),
        ),
        "Stats": Stats(strength=2, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d8"),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
    }
