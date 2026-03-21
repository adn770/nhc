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

from nhc.i18n.manager import TranslationManager

_manager = TranslationManager()


def init(lang: str = "en") -> None:
    """Initialize translations for the given language."""
    _manager.load(lang)


def t(key: str, **kwargs: object) -> str:
    """Translate a key, optionally interpolating named arguments."""
    return _manager.get(key, **kwargs)


def current_lang() -> str:
    """Return the currently loaded language code."""
    return _manager.lang
