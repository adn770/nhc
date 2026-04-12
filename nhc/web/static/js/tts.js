/**
 * Client-side TTS manager.
 *
 * Queues game messages, fetches WAV audio from /api/tts,
 * and plays them sequentially.  The enabled/volume preference
 * is persisted in localStorage and exposed on the welcome
 * screen via a checkbox.
 */
const TTS = {
  available: false,
  enabled: false,
  volume: 0.8,
  lang: "en",

  /** @type {string[]} */
  queue: [],
  speaking: false,
  /** @type {HTMLAudioElement|null} */
  currentAudio: null,

  /**
   * Restore preferences and sync the welcome-screen checkbox.
   * Called once on page load (before any game starts).
   */
  async initWelcome() {
    // Restore enabled preference
    const stored = localStorage.getItem("nhc_tts_enabled");
    if (stored !== null) this.enabled = stored === "true";

    // Restore volume
    const vol = localStorage.getItem("nhc_tts_volume");
    if (vol !== null) this.volume = parseFloat(vol);

    // Check server-side availability
    try {
      const resp = await fetch("/api/tts/status");
      const data = await resp.json();
      this.available = data.available;
    } catch {
      this.available = false;
    }

    // Sync checkbox
    const cb = document.getElementById("tts-check");
    if (cb) {
      if (!this.available) {
        cb.disabled = true;
        cb.closest("label").classList.add("hidden");
      } else {
        cb.checked = this.enabled;
        cb.addEventListener("change", () => {
          this.enabled = cb.checked;
          localStorage.setItem("nhc_tts_enabled", this.enabled);
        });
      }
    }
  },

  /**
   * Initialize for a game session: read the current checkbox
   * state, reset queue, and update toolbar.
   */
  init(lang) {
    this.lang = lang || "en";
    this.queue = [];
    this.speaking = false;
    this.currentAudio = null;

    // Read preference from checkbox (authoritative at game start)
    const cb = document.getElementById("tts-check");
    if (cb) {
      this.enabled = cb.checked;
      localStorage.setItem("nhc_tts_enabled", this.enabled);
    }

    this._updateUI();
  },

  /** Toggle TTS on/off. */
  toggle() {
    if (!this.available) return;
    this.enabled = !this.enabled;
    localStorage.setItem("nhc_tts_enabled", this.enabled);
    if (!this.enabled) this.skip();
    this._updateUI();
  },

  /** Set volume (0.0–1.0). */
  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
    localStorage.setItem("nhc_tts_volume", this.volume);
    if (this.currentAudio) this.currentAudio.volume = this.volume;
  },

  /** Add a message to the speech queue. */
  enqueue(text) {
    if (!this.available || !this.enabled) return;
    if (!text || !text.trim()) return;
    this.queue.push(text.trim());
    if (!this.speaking) this._playNext();
  },

  /** Stop current audio and clear the queue. */
  skip() {
    this.queue = [];
    this.speaking = false;
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
  },

  /** Play the next message in the queue. */
  async _playNext() {
    if (this.queue.length === 0) {
      this.speaking = false;
      return;
    }

    this.speaking = true;
    const text = this.queue.shift();

    try {
      const blob = await this._fetchAudio(text);
      if (!blob) {
        this._playNext();
        return;
      }

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = this.volume;
      this.currentAudio = audio;

      audio.addEventListener("ended", () => {
        URL.revokeObjectURL(url);
        this.currentAudio = null;
        this._playNext();
      });

      audio.addEventListener("error", () => {
        URL.revokeObjectURL(url);
        this.currentAudio = null;
        this._playNext();
      });

      await audio.play();
    } catch {
      // Autoplay may be blocked; skip silently
      this.currentAudio = null;
      this._playNext();
    }
  },

  /**
   * Fetch WAV audio from the server for the given text.
   * @returns {Promise<Blob|null>}
   */
  async _fetchAudio(text) {
    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lang: this.lang }),
      });
      if (!resp.ok) return null;
      return await resp.blob();
    } catch {
      return null;
    }
  },

  /** Update toolbar button: visibility, icon, glow, volume slider. */
  _updateUI() {
    const btn = document.getElementById("tts-btn");
    if (!btn) return;

    if (!this.available) {
      btn.classList.add("hidden");
      return;
    }

    btn.classList.remove("hidden");
    btn.textContent = this.enabled ? "\u{1F50A}" : "\u{1F507}";
    btn.classList.toggle("tts-active", this.enabled);

    const slider = document.getElementById("tts-volume");
    if (slider) {
      if (this.enabled) {
        slider.classList.remove("hidden");
        slider.value = Math.round(this.volume * 100);
      } else {
        slider.classList.add("hidden");
      }
    }
  },
};
