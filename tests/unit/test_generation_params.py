"""Tests for GenerationParams serialization and storage."""

import pytest

from nhc.dungeon.generator import GenerationParams, Range
from nhc.utils.rng import set_seed


class TestGenerationParamsToDict:
    def test_default_params_roundtrip(self):
        params = GenerationParams()
        d = params.to_dict()
        restored = GenerationParams.from_dict(d)
        assert restored.width == params.width
        assert restored.height == params.height
        assert restored.depth == params.depth
        assert restored.room_count.min == params.room_count.min
        assert restored.room_count.max == params.room_count.max
        assert restored.room_size.min == params.room_size.min
        assert restored.room_size.max == params.room_size.max
        assert restored.corridor_style == params.corridor_style
        assert restored.density == params.density
        assert restored.connectivity == params.connectivity
        assert restored.theme == params.theme
        assert restored.seed == params.seed
        assert restored.dead_ends == params.dead_ends
        assert restored.secret_doors == params.secret_doors
        assert restored.water_features == params.water_features
        assert restored.multiple_stairs == params.multiple_stairs
        assert restored.shape_variety == params.shape_variety

    def test_custom_params_roundtrip(self):
        params = GenerationParams(
            width=80, height=30, depth=5,
            room_count=Range(3, 8), room_size=Range(5, 15),
            corridor_style="bent", density=0.6,
            connectivity=0.5, theme="cave", seed=12345,
            dead_ends=False, secret_doors=0.2,
            water_features=True, multiple_stairs=True,
            shape_variety=0.7,
        )
        d = params.to_dict()
        restored = GenerationParams.from_dict(d)
        assert restored.width == 80
        assert restored.depth == 5
        assert restored.room_count.min == 3
        assert restored.room_count.max == 8
        assert restored.corridor_style == "bent"
        assert restored.seed == 12345
        assert restored.water_features is True
        assert restored.shape_variety == 0.7

    def test_to_dict_range_format(self):
        params = GenerationParams(
            room_count=Range(2, 10), room_size=Range(3, 8),
        )
        d = params.to_dict()
        assert d["room_count"] == {"min": 2, "max": 10}
        assert d["room_size"] == {"min": 3, "max": 8}

    def test_template_roundtrip(self):
        params = GenerationParams(template="procedural:tower")
        d = params.to_dict()
        assert d["template"] == "procedural:tower"
        restored = GenerationParams.from_dict(d)
        assert restored.template == "procedural:tower"

    def test_template_default_none(self):
        params = GenerationParams()
        assert params.template is None
        d = params.to_dict()
        assert d["template"] is None

    def test_to_dict_contains_all_fields(self):
        d = GenerationParams().to_dict()
        expected = {
            "width", "height", "depth", "room_count", "room_size",
            "corridor_style", "density", "connectivity", "theme",
            "seed", "dead_ends", "secret_doors", "water_features",
            "multiple_stairs", "shape_variety", "template",
            "preferred_shapes",
        }
        assert set(d.keys()) == expected


class TestGenerationParamsFromDict:
    def test_from_dict_partial(self):
        """Subset of fields uses defaults for the rest."""
        params = GenerationParams.from_dict({"depth": 10, "theme": "abyss"})
        assert params.depth == 10
        assert params.theme == "abyss"
        assert params.width == 120  # default
        assert params.height == 40  # default

    def test_from_dict_ignores_unknown_keys(self):
        params = GenerationParams.from_dict({
            "depth": 3, "unknown_field": "whatever",
        })
        assert params.depth == 3
        assert not hasattr(params, "unknown_field")

    def test_from_dict_empty(self):
        """Empty dict produces defaults."""
        params = GenerationParams.from_dict({})
        default = GenerationParams()
        assert params.width == default.width
        assert params.depth == default.depth

    def test_from_dict_seed_none(self):
        params = GenerationParams.from_dict({"seed": None})
        assert params.seed is None

    def test_from_dict_seed_integer(self):
        params = GenerationParams.from_dict({"seed": 42})
        assert params.seed == 42


class TestGameStoresGenerationParams:
    @pytest.fixture
    def game(self, tmp_path):
        from nhc.rendering.web_client import WebClient
        from nhc.core.game import Game
        client = WebClient(game_mode="classic", lang="en")
        return Game(
            client=client, game_mode="classic", seed=42,
            reset=True, save_dir=tmp_path,
        )

    def test_params_stored_after_initialize(self, game):
        set_seed(42)
        game.initialize(generate=True, depth=1)
        assert game.generation_params is not None
        assert game.generation_params.depth == 1
        assert game.generation_params.theme == "dungeon"
        assert game.generation_params.seed == 42

    def test_params_reflect_depth(self, game):
        set_seed(99)
        game.initialize(generate=True, depth=10)
        assert game.generation_params is not None
        assert game.generation_params.depth == 10
        assert game.generation_params.theme == "cave"
