"""Tests for the StructuralTemplate system."""

from nhc.dungeon.generator import GenerationParams, Range
from nhc.dungeon.templates import (
    TEMPLATES,
    StructuralTemplate,
    apply_template,
)


class TestStructuralTemplate:
    def test_template_dataclass(self):
        t = StructuralTemplate(
            name="test",
            base_generator="bsp",
            preferred_shapes=["rect", "circle"],
        )
        assert t.name == "test"
        assert t.base_generator == "bsp"
        assert t.layout_strategy == "default"
        assert t.transforms == []
        assert t.theme == "dungeon"

    def test_registry_has_known_templates(self):
        assert "procedural:tower" in TEMPLATES
        assert "procedural:crypt" in TEMPLATES
        assert "procedural:mine" in TEMPLATES

    def test_tower_template_properties(self):
        t = TEMPLATES["procedural:tower"]
        assert t.base_generator == "bsp"
        assert "circle" in t.preferred_shapes
        assert t.layout_strategy == "radial"
        assert t.room_size_override is not None
        assert t.room_size_override.max <= 7

    def test_crypt_template_properties(self):
        t = TEMPLATES["procedural:crypt"]
        assert t.forced_connectivity is not None
        assert t.forced_connectivity < 0.5
        # Crypt aesthetic: narrow winding passages
        assert "narrow_corridors" in t.transforms

    def test_mine_template_properties(self):
        t = TEMPLATES["procedural:mine"]
        assert t.layout_strategy == "linear"
        assert "add_cart_tracks" in t.transforms


class TestApplyTemplate:
    def test_apply_overrides_room_size(self):
        params = GenerationParams()
        tmpl = TEMPLATES["procedural:tower"]
        effective = apply_template(params, tmpl)
        assert effective.room_size.min == tmpl.room_size_override.min
        assert effective.room_size.max == tmpl.room_size_override.max

    def test_apply_overrides_theme(self):
        params = GenerationParams(theme="dungeon")
        tmpl = StructuralTemplate(
            name="test", base_generator="bsp",
            preferred_shapes=["rect"], theme="mine",
        )
        effective = apply_template(params, tmpl)
        assert effective.theme == "mine"

    def test_apply_overrides_connectivity(self):
        params = GenerationParams(connectivity=0.8)
        tmpl = TEMPLATES["procedural:crypt"]
        effective = apply_template(params, tmpl)
        assert effective.connectivity == tmpl.forced_connectivity

    def test_apply_sets_template_name(self):
        params = GenerationParams()
        tmpl = TEMPLATES["procedural:tower"]
        effective = apply_template(params, tmpl)
        assert effective.template == "procedural:tower"

    def test_apply_preserves_seed(self):
        params = GenerationParams(seed=42)
        tmpl = TEMPLATES["procedural:tower"]
        effective = apply_template(params, tmpl)
        assert effective.seed == 42

    def test_apply_preserves_depth(self):
        params = GenerationParams(depth=3)
        tmpl = TEMPLATES["procedural:tower"]
        effective = apply_template(params, tmpl)
        assert effective.depth == 3

    def test_apply_no_room_size_override(self):
        """Template without room_size_override preserves original."""
        params = GenerationParams(room_size=Range(3, 8))
        tmpl = StructuralTemplate(
            name="test", base_generator="bsp",
            preferred_shapes=["rect"],
        )
        effective = apply_template(params, tmpl)
        assert effective.room_size.min == 3
        assert effective.room_size.max == 8
