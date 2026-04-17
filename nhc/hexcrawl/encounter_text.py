"""Natural-language formatting for encounter creature lists.

Turns ``["goblin", "goblin", "kobold"]`` into:

* EN: "2 goblins and a kobold"
* CA: "2 gòblins i un cobold"
* ES: "2 goblins y un kobold"

Uses the creature locale entries (``creature.<id>.name``,
``creature.<id>.plural``, ``creature.<id>.gender``) plus the
``encounter.and`` conjunction key. Gender drives the indefinite
article in CA/ES (un/una, uns/unes, unos/unas). English uses
"a"/"an" for singular, bare count for plural.
"""

from __future__ import annotations

from collections import Counter

from nhc.i18n import current_lang, t


def _article_one(name: str, gender: str, lang: str) -> str:
    """Indefinite article + name for a single creature."""
    lower = name.lower()
    if lang == "en":
        return f"an {lower}" if lower[0] in "aeiou" else f"a {lower}"
    if lang == "ca":
        if gender == "f":
            if lower[0] in "aàeèiíoòuú":
                return f"una {lower}"
            return f"una {lower}"
        # masculine
        return f"un {lower}"
    if lang == "es":
        return f"una {lower}" if gender == "f" else f"un {lower}"
    return lower


def _count_plural(count: int, name: str, plural: str) -> str:
    """Count + plural form."""
    return f"{count} {plural.lower() if plural else name.lower()}"


def format_encounter_creatures(creature_ids: list[str]) -> str:
    """Build a natural-language creature list from raw IDs.

    Groups duplicates, looks up translated names/plurals/gender,
    joins with the localized conjunction, and prepends the right
    indefinite article per language.
    """
    if not creature_ids:
        return ""
    lang = current_lang()
    conjunction = t("encounter.and")

    counts = Counter(creature_ids)
    parts: list[str] = []
    for cid, n in counts.items():
        name = t(f"creature.{cid}.name")
        plural = t(f"creature.{cid}.plural")
        gender = t(f"creature.{cid}.gender")
        # t() returns the key itself if missing — detect that.
        if plural.startswith("creature."):
            plural = ""
        if gender.startswith("creature."):
            gender = ""
        if n == 1:
            parts.append(_article_one(name, gender, lang))
        else:
            parts.append(_count_plural(n, name, plural))

    if len(parts) == 1:
        return parts[0]
    # "A, B and C" / "A, B i C" / "A, B y C"
    return ", ".join(parts[:-1]) + f" {conjunction} " + parts[-1]
