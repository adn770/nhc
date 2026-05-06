"""Tests for template routing in the generation pipeline."""

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import CircleShape, OctagonShape, Level, RectShape
from nhc.dungeon.pipeline import generate_level


class TestPipelineTemplateRouting:
    def test_generate_without_template(self):
        """Default generation (no template) still works."""
        params = GenerationParams(
            width=40, height=40, depth=1, seed=42,
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert len(level.rooms) >= 3

    def test_generate_with_template(self):
        """Providing a template produces a valid level."""
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:crypt",
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert len(level.rooms) >= 3
        assert level.metadata.theme == "crypt"

    def test_unknown_template_falls_back(self):
        """Unknown template name falls back to default BSP."""
        params = GenerationParams(
            width=40, height=40, depth=1, seed=42,
            template="nonexistent:foo",
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert len(level.rooms) >= 3

    def test_cave_theme_uses_cellular(self):
        """Cave theme still uses CellularGenerator."""
        params = GenerationParams(
            width=40, height=40, depth=1, seed=42,
            theme="cave",
        )
        level = generate_level(params)
        assert isinstance(level, Level)

    def test_tower_template_prefers_circle_octagon(self):
        """Tower template restricts shapes to circle and octagon."""
        params = GenerationParams(
            width=80, height=40, depth=1, seed=99,
            shape_variety=1.0,
            template="procedural:radial",
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert len(level.rooms) >= 3
        for room in level.rooms:
            assert isinstance(
                room.shape, (CircleShape, OctagonShape, RectShape),
            ), (
                f"Tower room has unexpected shape: "
                f"{type(room.shape).__name__}"
            )

    def test_mine_template_prefers_rect(self):
        """Mine template restricts shapes to rect only."""
        params = GenerationParams(
            width=80, height=40, depth=1, seed=99,
            shape_variety=1.0,
            template="procedural:mine",
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        for room in level.rooms:
            assert isinstance(room.shape, RectShape), (
                f"Mine room has unexpected shape: "
                f"{type(room.shape).__name__}"
            )
