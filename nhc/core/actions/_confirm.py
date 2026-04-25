"""Player-initiated peaceful-attack confirmation.

A single helper that intercepts a ``BumpAction`` before it reaches
the main resolver. If the bump would melee-strike a peaceful NPC
that isn't yet engaged in combat with the player, the caller is
asked (via the ``prompt_fn`` hook) to confirm. The dialog now
offers two options:

* **Talk** (default, listed first) — rolls a flavor line from the
  ``combat.peaceful_chatter`` table and returns a :class:`HoldAction`
  that prints the line and ticks the turn so monsters move and
  clocks advance.
* **Attack** — tags the target :class:`CombatEngaged` and returns
  the original action untouched so the resolver's
  :class:`MeleeAttackAction` path runs as usual.

Exposing this as a free function (rather than inlining into the
game loop) keeps it unit-testable without spinning up a full
``Game`` instance.
"""

from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

from nhc.core.actions._base import Action, HoldAction
from nhc.core.actions._helpers import _entity_name
from nhc.core.actions._movement import BumpAction
from nhc.core.actions._combat import MeleeAttackAction
from nhc.entities.components import CombatEngaged
from nhc.i18n import t

if TYPE_CHECKING:
    from nhc.core.ecs import World
    from nhc.dungeon.model import Level

logger = logging.getLogger(__name__)


PromptFn = Callable[[str, list[tuple[int, str]]], "int | None"]


def _roll_peaceful_chatter() -> str | None:
    """Pull one ephemeral line from ``combat.peaceful_chatter``.

    Returns ``None`` when the table fails to load (missing locale,
    parse error, etc.) so the caller can degrade gracefully to a
    quiet HoldAction rather than crashing the turn.
    """
    try:
        from nhc.i18n import current_lang
        from nhc.tables import roll_ephemeral

        result = roll_ephemeral(
            "combat.peaceful_chatter", lang=current_lang(),
        )
        return result.text
    except Exception:  # noqa: BLE001 - chatter is best-effort flavor
        logger.debug(
            "combat.peaceful_chatter roll failed; "
            "falling back to a silent HoldAction",
            exc_info=True,
        )
        return None


def confirm_peaceful_attack(
    world: "World",
    level: "Level",
    action: Action,
    prompt_fn: PromptFn | None,
) -> Action:
    """Return ``action`` (after confirming) or a HoldAction with chatter.

    Non-``BumpAction`` inputs pass through untouched. A bump that
    pre-resolves to anything other than a melee strike (move, open
    door, shop interaction, etc.) also passes through. Only the
    narrow case *player-bump → melee → peaceful target → not
    engaged* triggers the prompt.
    """
    if not isinstance(action, BumpAction):
        return action

    resolved = action.resolve(world, level)
    if not isinstance(resolved, MeleeAttackAction):
        return action

    # Lazy import to avoid the import cycle between ai.behavior
    # (which pulls in core.actions via helpers) and the actions
    # package __init__ that re-exports this helper.
    from nhc.ai.behavior import PEACEFUL_BEHAVIORS

    target = resolved.target
    ai = world.get_component(target, "AI")
    if not ai or ai.behavior not in PEACEFUL_BEHAVIORS:
        return action

    if world.has_component(target, "CombatEngaged"):
        return action

    # Headless callers (tests, scripted runs) lack a prompt hook —
    # fall through to attack, matching the death-dialog pattern.
    if prompt_fn is None:
        world.add_component(target, "CombatEngaged", CombatEngaged())
        return action

    target_name = _entity_name(world, target)
    choice = prompt_fn(
        t("combat.confirm_prompt", name=target_name),
        [
            (0, t("combat.confirm_talk")),
            (1, t("combat.confirm_attack")),
        ],
    )
    if choice == 1:
        world.add_component(target, "CombatEngaged", CombatEngaged())
        return action

    # Talk (and fall-through for cancel / unknown choice): roll a
    # flavor line and return a HoldAction so the turn ticks while
    # the line is delivered through the standard message bus.
    chatter = _roll_peaceful_chatter() or ""
    return HoldAction(actor=action.actor, message_text=chatter)
