"""Tests for the Knave character generator."""

from nhc.rules.chargen import CharacterSheet, generate_character


class TestGenerateCharacter:
    def test_returns_character_sheet(self):
        char = generate_character(seed=42)
        assert isinstance(char, CharacterSheet)

    def test_has_name(self):
        char = generate_character(seed=42)
        assert len(char.name) > 0
        assert " " in char.name  # first + surname

    def test_ability_scores_in_range(self):
        """Knave 3d6-take-lowest produces bonuses 1–6."""
        for seed in range(100):
            char = generate_character(seed=seed)
            for attr in ("strength", "dexterity", "constitution",
                         "intelligence", "wisdom", "charisma"):
                val = getattr(char, attr)
                assert 1 <= val <= 6, f"{attr}={val} out of range (seed={seed})"

    def test_hp_in_range(self):
        """HP is 1d8."""
        for seed in range(100):
            char = generate_character(seed=seed)
            assert 1 <= char.hp <= 8, f"hp={char.hp} (seed={seed})"

    def test_gold_positive(self):
        """Starting gold is 3d6*20/10 = 6–36."""
        for seed in range(100):
            char = generate_character(seed=seed)
            assert 6 <= char.gold <= 36, f"gold={char.gold} (seed={seed})"

    def test_all_traits_filled(self):
        char = generate_character(seed=42)
        for trait in ("physique", "face", "skin", "hair", "clothing",
                      "virtue", "vice", "speech", "background",
                      "misfortune", "alignment"):
            assert len(getattr(char, trait)) > 0, f"{trait} is empty"

    def test_alignment_valid(self):
        for seed in range(100):
            char = generate_character(seed=seed)
            assert char.alignment in ("lawful", "neutral", "chaotic")

    def test_deterministic_with_seed(self):
        a = generate_character(seed=123)
        b = generate_character(seed=123)
        assert a.name == b.name
        assert a.strength == b.strength
        assert a.hp == b.hp
        assert a.background == b.background

    def test_different_seeds_different_characters(self):
        a = generate_character(seed=1)
        b = generate_character(seed=2)
        # Very unlikely to be identical
        assert a.name != b.name or a.strength != b.strength
