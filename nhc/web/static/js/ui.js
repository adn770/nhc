/**
 * UI management: status bar, history log, menus.
 */
const UI = {
  init() {
    this.historyLog = document.getElementById("history-log");
    this.statusLine1 = document.getElementById("status-line1");
    this.statusLine2 = document.getElementById("status-line2");
  },

  addMessage(text, cssClass) {
    const div = document.createElement("div");
    div.className = cssClass || "msg";
    div.textContent = text;
    this.historyLog.appendChild(div);
    // Auto-scroll to bottom
    const zone = document.getElementById("history-zone");
    zone.scrollTop = zone.scrollHeight;
  },

  addNarrative(text) {
    this.addMessage(text, "narrative");
  },

  updateStatus(stats) {
    if (stats.line1) this.statusLine1.textContent = stats.line1;
    if (stats.line2) this.statusLine2.textContent = stats.line2;
  },

  /**
   * Show a selection menu overlay. Returns a Promise that resolves
   * with the selected option ID, or null if cancelled.
   */
  showMenu(title, options) {
    return new Promise((resolve) => {
      // Create overlay
      const overlay = document.createElement("div");
      overlay.id = "menu-overlay";

      const box = document.createElement("div");
      box.className = "menu-box";

      const h3 = document.createElement("h3");
      h3.textContent = title;
      box.appendChild(h3);

      options.forEach((opt, i) => {
        const div = document.createElement("div");
        div.className = "option";
        const key = String.fromCharCode(97 + i); // a, b, c...
        div.innerHTML = `<span class="key">${key})</span> ${opt.name}`;
        div.addEventListener("click", () => {
          overlay.remove();
          resolve(opt.id);
        });
        box.appendChild(div);
      });

      overlay.appendChild(box);
      document.body.appendChild(overlay);

      // Keyboard handling
      const onKey = (e) => {
        if (e.key === "Escape") {
          overlay.remove();
          document.removeEventListener("keydown", onKey);
          resolve(null);
        }
        const idx = e.key.charCodeAt(0) - 97;
        if (idx >= 0 && idx < options.length) {
          overlay.remove();
          document.removeEventListener("keydown", onKey);
          resolve(options[idx].id);
        }
      };
      document.addEventListener("keydown", onKey);
    });
  },

  showGameOver(msg) {
    const overlay = document.createElement("div");
    overlay.id = "menu-overlay";
    const box = document.createElement("div");
    box.className = "menu-box";
    box.innerHTML = `<h3>${msg.won ? "VICTORY!" : "YOU DIED"}</h3>
      <p>${msg.killed_by ? "Killed by " + msg.killed_by : ""}</p>
      <p>Survived ${msg.turn} turns.</p>
      <div class="option" onclick="location.reload()">
        Press any key or click to restart
      </div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    document.addEventListener("keydown", () => location.reload(),
                              { once: true });
  },
};
