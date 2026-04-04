"""Internationalization support for NHC.

Usage:
    from nhc.i18n import t

    # Simple lookup
    t("ui.game_saved")            # → "Game saved."

    # With interpolation
    t("combat.hit", attacker="You", target="Goblin", damage=4)
    # → "You hits Goblin for 4 damage."

    # Entity descriptions (name, short, long)
    t("creature.goblin.name")     # → "Goblin"
    t("creature.goblin.short")    # → "a snarling goblin"
"""

import threading

from nhc.i18n.manager import TranslationManager

_local = threading.local()


def _get_manager() -> TranslationManager:
    """Return the thread-local TranslationManager, creating if needed."""
    mgr = getattr(_local, "manager", None)
    if mgr is None:
        mgr = TranslationManager()
        _local.manager = mgr
    return mgr


def init(lang: str = "en") -> None:
    """Initialize translations for the given language.

    Each thread gets its own TranslationManager, so concurrent
    game sessions with different languages don't interfere.
    """
    _get_manager().load(lang)


def t(key: str, **kwargs: object) -> str:
    """Translate a key, optionally interpolating named arguments."""
    return _get_manager().get(key, **kwargs)


def current_lang() -> str:
    """Return the currently loaded language code."""
    return _get_manager().lang
