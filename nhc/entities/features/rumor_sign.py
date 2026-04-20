"""Rumor sign — wayside signpost that dispenses overland rumours.

The :class:`SignReadAction` keys off the ``RumorSign`` marker
component. BumpAction routes a bump into the sign through this
marker so the player hears a rumour without needing a menu.
"""

from nhc.entities.components import BlocksMovement, Renderable
from nhc.entities.registry import EntityRegistry
from nhc.i18n import t


def _description():
    """Build the rumor-sign description lazily so i18n init has run
    before ``t()`` is consulted."""
    from nhc.entities.components import Description

    return Description(
        name=t("feature.rumor_sign.name"),
        short=t("feature.rumor_sign.short"),
    )


@EntityRegistry.register_feature("rumor_sign")
def create_rumor_sign() -> dict:
    return {
        "Renderable": Renderable(
            glyph="p", color="yellow", render_order=1,
        ),
        "Description": _description(),
        "BlocksMovement": BlocksMovement(),
        "RumorSign": True,
    }
