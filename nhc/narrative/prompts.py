"""Multilingual prompt loader for the GM pipeline.

Loads prompt files from nhc/narrative/prompts/{lang}/, falling back
to English if a prompt doesn't exist for the active language.
"""

from __future__ import annotations

from pathlib import Path

from nhc.i18n import current_lang

_PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(prompt_name: str, **kwargs: object) -> str:
    """Load a prompt file for the active language.

    Falls back to English if the file doesn't exist for the active
    language.  Interpolates ``{placeholders}`` from *kwargs* using
    :meth:`str.format_map`.
    """
    lang = current_lang()
    path = _PROMPT_DIR / lang / f"{prompt_name}.txt"
    if not path.exists():
        path = _PROMPT_DIR / "en" / f"{prompt_name}.txt"
    text = path.read_text()
    if kwargs:
        text = text.format_map(kwargs)
    return text
