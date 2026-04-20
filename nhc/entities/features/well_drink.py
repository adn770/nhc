"""Well drink — wayside well that restores 1 HP and leaks rumours.

The :class:`WellInteractAction` keys off the ``WellDrink`` marker
component. BumpAction routes a bump into the well through this
marker.
"""

from nhc.entities.components import BlocksMovement, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


def _description():
    from nhc.entities.components import Description

    return Description(
        name=t("feature.well.name"),
        short=t("feature.well.short"),
    )


@EntityRegistry.register_feature("well_drink")
def create_well_drink() -> dict:
    return {
        "Renderable": Renderable(
            glyph="o", color="cyan", render_order=1,
        ),
        "Description": _description(),
        "BlocksMovement": BlocksMovement(),
        "WellDrink": True,
    }
