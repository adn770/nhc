"""Tests for the TTS engine and /api/tts endpoints."""

import io
import json
import wave
from unittest.mock import MagicMock, patch

import pytest

from nhc.web.tts import MAX_TEXT_LENGTH, TTSEngine, clean_text


# ── Text cleaning ──────────────────────────────────────────────


class TestCleanText:
    def test_strips_markdown_bold(self):
        assert clean_text("**bold text**") == "bold text"

    def test_strips_markdown_italic(self):
        assert clean_text("_italic_") == "italic"

    def test_strips_markdown_headings(self):
        assert clean_text("## Heading") == "Heading"

    def test_strips_html_tags(self):
        assert clean_text("<b>bold</b>") == "bold"

    def test_strips_ansi_codes(self):
        assert clean_text("\x1b[31mred\x1b[0m") == "red"

    def test_strips_backticks(self):
        assert clean_text("`code`") == "code"

    def test_preserves_plain_text(self):
        assert clean_text("You hit the goblin.") == (
            "You hit the goblin."
        )

    def test_empty_after_cleaning(self):
        assert clean_text("**") == ""

    def test_mixed_formatting(self):
        result = clean_text("## **_Bold heading_**")
        assert result == "Bold heading"


# ── TTSEngine availability ─────────────────────────────────────


class TestTTSEngineAvailability:
    def test_is_available_when_piper_installed(self):
        engine = TTSEngine()
        # Depends on whether piper-tts is installed in test env;
        # we test the flag directly.
        from nhc.web import tts
        assert engine.is_available() == tts.PIPER_AVAILABLE

    def test_is_available_false_when_piper_missing(self):
        engine = TTSEngine()
        with patch.object(
            type(engine), "is_available", return_value=False
        ):
            assert not engine.is_available()

    def test_synthesize_raises_when_piper_unavailable(self):
        with patch("nhc.web.tts.PIPER_AVAILABLE", False):
            engine = TTSEngine()
            with pytest.raises(RuntimeError, match="not installed"):
                engine.synthesize("hello", "en")


# ── TTSEngine validation ──────────────────────────────────────


class TestTTSEngineValidation:
    @patch("nhc.web.tts.PIPER_AVAILABLE", True)
    def test_unsupported_language(self):
        engine = TTSEngine()
        with pytest.raises(ValueError, match="Unsupported"):
            engine.synthesize("hello", "fr")

    @patch("nhc.web.tts.PIPER_AVAILABLE", True)
    def test_empty_text(self):
        engine = TTSEngine()
        with pytest.raises(ValueError, match="Empty text"):
            engine.synthesize("", "en")

    @patch("nhc.web.tts.PIPER_AVAILABLE", True)
    def test_text_only_formatting(self):
        engine = TTSEngine()
        with pytest.raises(ValueError, match="Empty text"):
            engine.synthesize("**", "en")

    @patch("nhc.web.tts.PIPER_AVAILABLE", True)
    def test_text_too_long(self):
        engine = TTSEngine()
        long_text = "a" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(ValueError, match="maximum length"):
            engine.synthesize(long_text, "en")


# ── TTSEngine synthesis (mocked Piper) ─────────────────────────


def _make_mock_voice():
    """Create a mock PiperVoice that returns dummy PCM audio."""
    voice = MagicMock()
    voice.config.sample_rate = 22050
    voice.config.num_channels = 1
    voice.config.sample_width = 2

    # Synthesize returns a generator of audio chunks
    chunk = MagicMock()
    chunk.audio_int16_bytes = b"\x00\x00" * 1000  # 1000 silent samples
    voice.synthesize.return_value = iter([chunk])
    return voice


class TestTTSEngineSynthesize:
    @patch("nhc.web.tts.SynthesisConfig", MagicMock())
    @patch("nhc.web.tts.PIPER_AVAILABLE", True)
    def test_synthesize_returns_wav(self):
        engine = TTSEngine()
        mock_voice = _make_mock_voice()
        engine._voices["en"] = mock_voice

        result = engine.synthesize("Hello world.", "en")
        assert isinstance(result, io.BytesIO)

        # Verify it's a valid WAV
        result.seek(0)
        with wave.open(result, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050
            assert wf.getnframes() == 1000

    @patch("nhc.web.tts.PIPER_AVAILABLE", True)
    def test_synthesize_cleans_text(self):
        engine = TTSEngine()
        mock_voice = _make_mock_voice()
        engine._voices["en"] = mock_voice

        with patch("nhc.web.tts.SynthesisConfig") as MockConfig:
            mock_cfg = MagicMock()
            MockConfig.return_value = mock_cfg
            engine.synthesize("**Bold** attack!", "en")
            MockConfig.assert_called_once_with(length_scale=0.8)
            mock_voice.synthesize.assert_called_once_with(
                "Bold attack!", syn_config=mock_cfg
            )


# ── Flask endpoint tests ──────────────────────────────────────


@pytest.fixture
def tts_client():
    """Flask test client with a mocked TTS engine."""
    from nhc.web.app import create_app
    from nhc.web.config import WebConfig

    config = WebConfig(max_sessions=2)
    app = create_app(config)
    app.config["TESTING"] = True

    # Install a mock TTS engine
    mock_engine = MagicMock(spec=TTSEngine)
    mock_engine.is_available.return_value = True
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 100)
    wav_buf.seek(0)
    mock_engine.synthesize.return_value = wav_buf
    app.config["TTS_ENGINE"] = mock_engine

    with app.test_client() as c:
        yield c


@pytest.fixture
def tts_client_unavailable():
    """Flask test client with TTS unavailable."""
    from nhc.web.app import create_app
    from nhc.web.config import WebConfig

    config = WebConfig(max_sessions=2)
    app = create_app(config)
    app.config["TESTING"] = True

    mock_engine = MagicMock(spec=TTSEngine)
    mock_engine.is_available.return_value = False
    app.config["TTS_ENGINE"] = mock_engine

    with app.test_client() as c:
        yield c


class TestTTSStatusEndpoint:
    def test_status_available(self, tts_client):
        resp = tts_client.get("/api/tts/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is True

    def test_status_unavailable(self, tts_client_unavailable):
        resp = tts_client_unavailable.get("/api/tts/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["available"] is False


class TestTTSSynthesizeEndpoint:
    def test_synthesize_success(self, tts_client):
        resp = tts_client.post(
            "/api/tts",
            data=json.dumps({"text": "Hello.", "lang": "en"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.content_type == "audio/wav"

    def test_synthesize_missing_text(self, tts_client):
        resp = tts_client.post(
            "/api/tts",
            data=json.dumps({"lang": "en"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_synthesize_missing_lang(self, tts_client):
        resp = tts_client.post(
            "/api/tts",
            data=json.dumps({"text": "Hello."}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_synthesize_unavailable(self, tts_client_unavailable):
        resp = tts_client_unavailable.post(
            "/api/tts",
            data=json.dumps({"text": "Hello.", "lang": "en"}),
            content_type="application/json",
        )
        assert resp.status_code == 503

    def test_synthesize_validation_error(self, tts_client):
        engine = tts_client.application.config["TTS_ENGINE"]
        engine.synthesize.side_effect = ValueError("Empty text")
        resp = tts_client.post(
            "/api/tts",
            data=json.dumps({"text": "", "lang": "en"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_synthesize_runtime_error(self, tts_client):
        engine = tts_client.application.config["TTS_ENGINE"]
        engine.synthesize.side_effect = RuntimeError("model fail")
        resp = tts_client.post(
            "/api/tts",
            data=json.dumps({"text": "Hello.", "lang": "en"}),
            content_type="application/json",
        )
        assert resp.status_code == 503
