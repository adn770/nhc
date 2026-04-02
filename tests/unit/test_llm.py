"""Tests for LLM backend abstraction and provider selection."""

import platform
from unittest.mock import patch

import pytest

from nhc.utils.llm import (
    _DEFAULT_MLX_MODEL,
    _DEFAULT_OLLAMA_MODEL,
    auto_detect_provider,
    create_backend,
)


class TestDefaultModels:
    """Verify default model constants match expected values."""

    def test_default_mlx_model_is_gemma3_12b_qat(self):
        assert "gemma-3-12b" in _DEFAULT_MLX_MODEL
        assert "4bit" in _DEFAULT_MLX_MODEL

    def test_default_ollama_model_is_gemma3_12b(self):
        assert _DEFAULT_OLLAMA_MODEL == "gemma3:12b"


class TestAutoDetectProvider:
    """Verify provider auto-detection logic."""

    @patch("platform.system", return_value="Darwin")
    @patch("platform.machine", return_value="arm64")
    def test_auto_detect_prefers_mlx_on_apple_silicon(self, _m, _s):
        with patch.dict("sys.modules", {"mlx_lm": object()}):
            provider, model = auto_detect_provider()
        assert provider == "mlx"
        assert model == _DEFAULT_MLX_MODEL

    @patch("platform.system", return_value="Darwin")
    @patch("platform.machine", return_value="arm64")
    def test_auto_detect_falls_back_to_ollama_without_mlx(self, _m, _s):
        import sys
        # Temporarily remove mlx_lm from modules so the import fails
        saved = sys.modules.pop("mlx_lm", None)
        try:
            with patch.dict("sys.modules", {"mlx_lm": None}):
                provider, model = auto_detect_provider()
        finally:
            if saved is not None:
                sys.modules["mlx_lm"] = saved
        assert provider == "ollama"
        assert model == _DEFAULT_OLLAMA_MODEL

    @patch("platform.system", return_value="Linux")
    @patch("platform.machine", return_value="x86_64")
    def test_auto_detect_returns_ollama_on_linux(self, _m, _s):
        provider, model = auto_detect_provider()
        assert provider == "ollama"
        assert model == _DEFAULT_OLLAMA_MODEL


class TestCreateBackend:
    """Verify backend factory behaviour."""

    def test_provider_none_returns_none(self):
        backend = create_backend({"provider": "none"})
        assert backend is None

    def test_provider_auto_is_accepted(self):
        """auto provider should resolve without raising."""
        with patch("nhc.utils.llm.auto_detect_provider",
                   return_value=("ollama", "gemma3:12b")):
            with patch("nhc.utils.llm.OllamaBackend") as mock_cls:
                mock_cls.return_value = object()
                backend = create_backend({"provider": "auto"})
        assert backend is not None

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_backend({"provider": "bogus"})

    def test_anthropic_without_key_raises(self):
        with pytest.raises(ValueError, match="requires --api-key"):
            create_backend({"provider": "anthropic"})
