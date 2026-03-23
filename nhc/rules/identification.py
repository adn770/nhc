"""Item identification system for potions and scrolls.

Each game session shuffles appearances so players can't memorize
mappings.  Items are identified by using them — once identified,
all items of that type show their real name.
"""

from __future__ import annotations

import random

from nhc.i18n import t

# ── Potion IDs and appearances ──────────────────────────────────────

POTION_IDS = [
    "healing_potion",
    "potion_strength",
    "potion_frost",
    "potion_invisibility",
    "potion_levitation",
    "potion_liquid_flame",
    "potion_mind_vision",
    "potion_paralytic_gas",
    "potion_purification",
]

# (i18n_key_suffix, glyph_color)
POTION_APPEARANCES = [
    ("bubbly_red", "red"),
    ("murky_green", "green"),
    ("shimmering_blue", "bright_blue"),
    ("thick_yellow", "yellow"),
    ("fizzy_violet", "magenta"),
    ("dark_brown", "yellow"),
    ("glowing_white", "bright_white"),
    ("oily_black", "bright_black"),
    ("sparkling_cyan", "bright_cyan"),
]

# ── Scroll IDs and appearances ──────────────────────────────────────

SCROLL_IDS = [
    "scroll_bless", "scroll_charm_person", "scroll_charm_snakes",
    "scroll_clairvoyance", "scroll_continual_light", "scroll_cure_wounds",
    "scroll_detect_evil", "scroll_detect_invisibility",
    "scroll_detect_magic", "scroll_dispel_magic", "scroll_find_traps",
    "scroll_fireball", "scroll_fly", "scroll_haste",
    "scroll_hold_person", "scroll_infravision", "scroll_invisibility",
    "scroll_levitate", "scroll_light", "scroll_lightning",
    "scroll_magic_missile", "scroll_mirror_image",
    "scroll_phantasmal_force", "scroll_protection_evil",
    "scroll_protection_missiles", "scroll_remove_fear",
    "scroll_resist_cold", "scroll_resist_fire", "scroll_shield",
    "scroll_silence", "scroll_sleep", "scroll_water_breathing",
    "scroll_web",
]

# Cryptic labels — shuffled and assigned to scroll types
# (i18n_key_suffix, glyph_color)
SCROLL_APPEARANCES = [
    ("zelgo_mer", "white"),
    ("juyed_awk", "bright_white"),
    ("nrk_phlod", "yellow"),
    ("xixaxa", "bright_cyan"),
    ("pratyavayah", "magenta"),
    ("daiyen_fansen", "bright_blue"),
    ("garven_dey", "green"),
    ("elam_eansen", "bright_yellow"),
    ("verr_ull", "cyan"),
    ("yoho_oh", "bright_red"),
    ("kernod_wel", "bright_green"),
    ("foobie_bletch", "bright_white"),
    ("temov", "white"),
    ("andova_begarin", "bright_magenta"),
    ("kirje", "yellow"),
    ("velox_neb", "bright_cyan"),
    ("zlorfik", "green"),
    ("gnusto_rezrov", "bright_blue"),
    ("exodia_mull", "magenta"),
    ("tatta_sull", "bright_yellow"),
    ("priqa_ull", "cyan"),
    ("nar_i_ull", "bright_red"),
    ("borch_sull", "bright_green"),
    ("vomica_abra", "white"),
    ("hackem_muche", "bright_white"),
    ("duam_xnaht", "yellow"),
    ("elbib_yloh", "bright_cyan"),
    ("lepmah_tansen", "magenta"),
    ("werdna_lull", "bright_blue"),
    ("balk_me_ansen", "green"),
    ("rok_ull", "bright_yellow"),
    ("gnik_sansen", "cyan"),
    ("ashpd_lansen", "bright_red"),
]

# All identifiable item IDs
ALL_IDS = POTION_IDS + SCROLL_IDS


class ItemKnowledge:
    """Tracks which item types have been identified this game."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.identified: set[str] = set()

        r = rng or random.Random()

        # Shuffle and assign potion appearances
        potions = list(POTION_APPEARANCES)
        r.shuffle(potions)
        self._appearance: dict[str, tuple[str, str]] = {}
        for i, pid in enumerate(POTION_IDS):
            self._appearance[pid] = potions[i % len(potions)]

        # Shuffle and assign scroll appearances
        scrolls = list(SCROLL_APPEARANCES)
        r.shuffle(scrolls)
        for i, sid in enumerate(SCROLL_IDS):
            self._appearance[sid] = scrolls[i % len(scrolls)]

    def is_identified(self, item_id: str) -> bool:
        return item_id in self.identified

    def is_identifiable(self, item_id: str) -> bool:
        return item_id in self._appearance

    def identify(self, item_id: str) -> None:
        self.identified.add(item_id)

    def appearance(self, item_id: str) -> tuple[str, str]:
        return self._appearance.get(item_id, ("bubbly_red", "red"))

    def display_name(self, item_id: str) -> str:
        if item_id in self.identified:
            return t(f"items.{item_id}.name")
        key_suffix, _ = self.appearance(item_id)
        if item_id in POTION_IDS:
            return t(f"potion_appearance.{key_suffix}")
        return t(f"scroll_appearance.{key_suffix}")

    def display_short(self, item_id: str) -> str:
        if item_id in self.identified:
            return t(f"items.{item_id}.short")
        key_suffix, _ = self.appearance(item_id)
        if item_id in POTION_IDS:
            return t(f"potion_appearance.{key_suffix}_short")
        return t(f"scroll_appearance.{key_suffix}_short")

    def glyph_color(self, item_id: str) -> str:
        _, color = self.appearance(item_id)
        return color
