"""Effect handler registry with built-in reveal_hex.

Effects are applied by callers via apply_effect() so roll() stays
pure. register_effect_handler decorator lets future callers add
handlers without patching this module.
"""

from __future__ import annotations

from typing import Callable

from nhc.tables.types import TableEffect


class UnknownEffectError(Exception):
    """Raised when an effect kind has no registered handler."""


_HANDLERS: dict[str, Callable] = {}


def register_effect_handler(kind: str):
    """Decorator to register a handler for effect *kind*."""
    def decorator(fn: Callable) -> Callable:
        _HANDLERS[kind] = fn
        return fn
    return decorator


def apply_effect(
    effect: TableEffect | None,
    **ctx,
) -> None:
    """Dispatch *effect* to its registered handler.

    Returns None if effect is None (entry has no side-effect).
    Raises UnknownEffectError if the kind has no handler.
    """
    if effect is None:
        return None

    handler = _HANDLERS.get(effect.kind)
    if handler is None:
        raise UnknownEffectError(
            f"No handler registered for effect kind '{effect.kind}'"
        )

    handler(effect.payload, **ctx)


@register_effect_handler("reveal_hex")
def _reveal_hex(payload: dict, **ctx) -> None:
    """Reveal a hex on the fog-of-war map."""
    world = ctx["world"]
    if payload.get("source") == "context":
        q, r = ctx["q"], ctx["r"]
    else:
        q, r = payload["q"], payload["r"]
    world.reveal((q, r))
