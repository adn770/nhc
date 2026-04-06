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
    "potion_speed",
    "potion_confusion",
    "potion_blindness",
    "potion_acid",
    "potion_sickness",
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
    ("cloudy_grey", "white"),
    ("swirling_orange", "bright_red"),
    ("milky_white", "bright_white"),
    ("pungent_green", "bright_green"),
    ("pale_pink", "magenta"),
]

# ── Scroll IDs and appearances ──────────────────────────────────────

SCROLL_IDS = [
    "scroll_bless", "scroll_charm_person", "scroll_charm_snakes",
    "scroll_clairvoyance", "scroll_continual_light", "scroll_cure_wounds",
    "scroll_detect_evil", "scroll_detect_food",
    "scroll_detect_gold", "scroll_detect_invisibility",
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
    "scroll_identify",
    "scroll_enchant_weapon",
    "scroll_enchant_armor",
    "scroll_charging",
    "scroll_teleportation",
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
    ("kwango_ull", "bright_magenta"),
    ("venzar_plansen", "cyan"),
    ("morke_dansen", "bright_green"),
    ("ulgoth_sansen", "white"),
    ("thakk_ansen", "bright_yellow"),
    ("druul_fansen", "bright_green"),
]

# ── Ring IDs and appearances ─────────────────────────────────────────

RING_IDS = [
    "ring_mending", "ring_haste", "ring_detection", "ring_elements",
    "ring_accuracy", "ring_evasion", "ring_shadows", "ring_protection",
]

RING_APPEARANCES = [
    ("diamond", "bright_white"),
    ("ruby", "bright_red"),
    ("emerald", "bright_green"),
    ("sapphire", "bright_blue"),
    ("opal", "bright_cyan"),
    ("amethyst", "magenta"),
    ("topaz", "bright_yellow"),
    ("onyx", "bright_black"),
]

# ── Wand IDs and appearances ────────────────────────────────────────

WAND_IDS = [
    "wand_firebolt", "wand_lightning", "wand_teleport", "wand_poison",
    "wand_slowness", "wand_disintegrate", "wand_magic_missile",
    "wand_amok",
    "wand_opening",
    "wand_locking",
    "wand_cold",
    "wand_death",
    "wand_cancellation",
    "wand_digging",
]

WAND_APPEARANCES = [
    ("holly", "green"),
    ("yew", "yellow"),
    ("ebony", "bright_black"),
    ("cherry", "bright_red"),
    ("teak", "yellow"),
    ("rowan", "bright_green"),
    ("willow", "bright_cyan"),
    ("oak", "bright_yellow"),
    ("birch", "bright_white"),
    ("maple", "bright_red"),
    ("ash", "white"),
    ("cedar", "yellow"),
    ("elm", "green"),
    ("pine", "bright_green"),
]

# All identifiable item IDs
ALL_IDS = POTION_IDS + SCROLL_IDS + RING_IDS + WAND_IDS


class ItemKnowledge:
    """Tracks which item types have been identified this game."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.identified: set[str] = set()

        r = rng or random.Random()

        self._appearance: dict[str, tuple[str, str]] = {}

        # Shuffle and assign each category
        for ids, appearances in [
            (POTION_IDS, POTION_APPEARANCES),
            (SCROLL_IDS, SCROLL_APPEARANCES),
            (RING_IDS, RING_APPEARANCES),
            (WAND_IDS, WAND_APPEARANCES),
        ]:
            pool = list(appearances)
            r.shuffle(pool)
            for i, item_id in enumerate(ids):
                self._appearance[item_id] = pool[i % len(pool)]

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
        prefix = self._appearance_prefix(item_id)
        return t(f"{prefix}.{key_suffix}")

    def display_short(self, item_id: str) -> str:
        if item_id in self.identified:
            return t(f"items.{item_id}.short")
        key_suffix, _ = self.appearance(item_id)
        prefix = self._appearance_prefix(item_id)
        return t(f"{prefix}.{key_suffix}_short")

    def glyph_color(self, item_id: str) -> str:
        _, color = self.appearance(item_id)
        return color

    @staticmethod
    def _appearance_prefix(item_id: str) -> str:
        if item_id.startswith("ring_"):
            return "ring_appearance"
        if item_id.startswith("wand_"):
            return "wand_appearance"
        if item_id.startswith("scroll_"):
            return "scroll_appearance"
        return "potion_appearance"
