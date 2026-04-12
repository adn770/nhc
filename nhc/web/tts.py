"""
Server-side text-to-speech engine using Piper TTS.

Synthesizes game messages to WAV audio buffers for streaming to
the web client. Models are downloaded on first use and cached
locally. Each language gets a lazy-loaded PiperVoice singleton
with a threading lock for safe concurrent access.
"""

import io
import logging
import os
import re
import threading
import time
import wave

log = logging.getLogger("nhc.tts")

# Gracefully handle optional TTS dependencies
try:
    import requests as _requests_module
    from piper import PiperVoice
    from piper.config import SynthesisConfig

    PIPER_AVAILABLE = True
except ImportError:
    _requests_module = None  # type: ignore[assignment]
    SynthesisConfig = None  # type: ignore[assignment,misc]
    PIPER_AVAILABLE = False

# Voice model configuration — same models as ppdf
_MODELS = {
    "en": {
        "model": "en_US-lessac-medium.onnx",
        "url_base": (
            "https://huggingface.co/rhasspy/piper-voices"
            "/resolve/main/en/en_US/lessac/medium/"
        ),
    },
    "es": {
        "model": "es_ES-sharvard-medium.onnx",
        "url_base": (
            "https://huggingface.co/rhasspy/piper-voices"
            "/resolve/main/es/es_ES/sharvard/medium/"
        ),
    },
    "ca": {
        "model": "ca_ES-upc_ona-medium.onnx",
        "url_base": (
            "https://huggingface.co/rhasspy/piper-voices"
            "/resolve/main/ca/ca_ES/upc_ona/medium/"
        ),
    },
}

SUPPORTED_LANGUAGES = list(_MODELS.keys())

# Maximum text length accepted by the /api/tts endpoint
MAX_TEXT_LENGTH = 500

# Idle timeout: unload voice models after this many seconds
_IDLE_TIMEOUT = 300  # 5 minutes

# Regex to strip markdown/ANSI artifacts from game messages
_CLEAN_RE = re.compile(r"#+\s*|[*_`]|<[^>]+>|\x1b\[[0-9;]*m")


def clean_text(text: str) -> str:
    """Strip markdown, HTML tags, and ANSI codes from text."""
    return _CLEAN_RE.sub("", text).strip()


class TTSEngine:
    """
    Thread-safe TTS engine that synthesizes text to WAV buffers.

    Voice models are loaded lazily on first request per language
    and unloaded after an idle period to conserve memory.
    """

    def __init__(self) -> None:
        self._voices: dict[str, "PiperVoice"] = {}
        self._locks: dict[str, threading.Lock] = {
            lang: threading.Lock() for lang in _MODELS
        }
        self._last_used: dict[str, float] = {}
        self._idle_timer: threading.Timer | None = None

    def is_available(self) -> bool:
        """Return True if piper-tts is installed."""
        return PIPER_AVAILABLE

    def synthesize(self, text: str, lang: str) -> io.BytesIO:
        """
        Synthesize text to a WAV audio buffer.

        Args:
            text: The text to synthesize (will be cleaned).
            lang: Language code ('en', 'es', 'ca').

        Returns:
            BytesIO containing a valid WAV file.

        Raises:
            RuntimeError: If Piper is not available or language
                is unsupported.
            ValueError: If text is empty or too long.
        """
        if not PIPER_AVAILABLE:
            raise RuntimeError("piper-tts is not installed")

        if lang not in _MODELS:
            raise ValueError(f"Unsupported language: {lang}")

        cleaned = clean_text(text)
        if not cleaned:
            raise ValueError("Empty text after cleaning")
        if len(cleaned) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Text exceeds maximum length of {MAX_TEXT_LENGTH}"
            )

        lock = self._locks[lang]
        with lock:
            voice = self._get_voice(lang)
            self._last_used[lang] = time.monotonic()
            self._schedule_idle_check()
            return self._synthesize_wav(voice, cleaned)

    def _get_voice(self, lang: str) -> "PiperVoice":
        """Load or return cached voice model for a language."""
        if lang in self._voices:
            return self._voices[lang]

        config = _MODELS[lang]
        cache_dir = os.path.expanduser("~/.cache/nhc/models")
        os.makedirs(cache_dir, exist_ok=True)

        # Download model and config if not cached
        for suffix in [config["model"], f"{config['model']}.json"]:
            path = os.path.join(cache_dir, suffix)
            if not os.path.exists(path):
                log.info("Downloading TTS model: %s", suffix)
                try:
                    url = config["url_base"] + suffix
                    with _requests_module.get(
                        url, stream=True, timeout=60
                    ) as r:
                        r.raise_for_status()
                        with open(path, "wb") as f:
                            for chunk in r.iter_content(
                                chunk_size=8192
                            ):
                                f.write(chunk)
                    log.info("Downloaded %s", suffix)
                except _requests_module.RequestException as e:
                    log.error("Failed to download %s: %s", suffix, e)
                    if os.path.exists(path):
                        os.remove(path)
                    raise RuntimeError(
                        f"Failed to download voice model: {e}"
                    ) from e

        model_path = os.path.join(cache_dir, config["model"])
        log.info("Loading TTS voice model: %s", config["model"])
        voice = PiperVoice.load(model_path)
        self._voices[lang] = voice
        return voice

    def _synthesize_wav(
        self, voice: "PiperVoice", text: str
    ) -> io.BytesIO:
        """Synthesize text into a WAV BytesIO using Piper."""
        sample_rate = getattr(voice.config, "sample_rate", 22050)
        num_channels = getattr(voice.config, "num_channels", 1)
        sample_width = getattr(voice.config, "sample_width", 2)

        # Collect all PCM chunks
        pcm_data = bytearray()
        syn_config = SynthesisConfig(length_scale=0.8)
        for audio_chunk in voice.synthesize(text, syn_config=syn_config):
            pcm_data.extend(audio_chunk.audio_int16_bytes)

        # Write WAV to BytesIO
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(bytes(pcm_data))

        buf.seek(0)
        return buf

    def _schedule_idle_check(self) -> None:
        """Schedule an idle check to unload unused models."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(
            _IDLE_TIMEOUT, self._check_idle
        )
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _check_idle(self) -> None:
        """Unload voice models that have been idle too long."""
        now = time.monotonic()
        for lang in list(self._voices):
            last = self._last_used.get(lang, 0)
            if now - last >= _IDLE_TIMEOUT:
                lock = self._locks[lang]
                with lock:
                    if lang in self._voices:
                        log.info(
                            "Unloading idle TTS voice: %s", lang
                        )
                        del self._voices[lang]

    def unload_all(self) -> None:
        """Unload all voice models (for shutdown)."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        for lang in list(self._voices):
            with self._locks[lang]:
                if lang in self._voices:
                    del self._voices[lang]
        log.info("All TTS voices unloaded")
