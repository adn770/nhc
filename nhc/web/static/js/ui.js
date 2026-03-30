/**
 * UI management: status bar, history log, menus.
 */
const UI = {
  init() {
    this.historyLog = document.getElementById("history-log");
    this.statusLine1 = document.getElementById("status-line1");
    this.statusLine2 = document.getElementById("status-line2");
    this.statusLine3 = document.getElementById("status-line3");
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

  updateStatus(s) {
    if (!s.hp_max) return;

    // ── Line 1: Location, depth, turn, level, gold, HP bar ──
    const hp = s.hp || 0;
    const hpMax = s.hp_max || 1;
    const hpPct = hp / hpMax;
    const barW = 12;
    const filled = Math.max(0, Math.round(barW * hpPct));
    const hpBar = "█".repeat(filled) + "░".repeat(barW - filled);
    let hpColor = "#44FF44";  // green
    if (hpPct <= 0.25) hpColor = "#FF4444";  // red
    else if (hpPct <= 0.5) hpColor = "#FFFF44";  // yellow

    const sep = " │ ";
    this.statusLine1.innerHTML =
      ` 📍 <b>${s.level_name || "?"}</b>` +
      `${sep}⬇ ${s.depth}` +
      `${sep}⏳ ${s.turn}` +
      `${sep}Lv ${s.plevel} (${s.xp}/${s.xp_next} XP)` +
      `${sep}💰 <span style="color:#FFFF44">${s.gold}</span>` +
      `${sep}❤️  <span style="color:${hpColor}">${hpBar} ${hp}/${hpMax}</span>`;

    // ── Line 2: Name, stats, equipment ──
    const name = s.char_name || "?";
    const bg = s.char_bg ? ` (${s.char_bg})` : "";
    const equip = [
      `⚔️  ${s.weapon}`,
      s.armor_name, s.shield_name, s.helmet_name,
      `${s.ac_label} ${s.ac}`,
    ].filter(Boolean).join(sep);

    this.statusLine2.innerHTML =
      ` <b>${name}</b>${bg}` +
      `${sep}STR:${this._signed(s.str)}` +
      ` DEX:${this._signed(s.dex)}` +
      ` CON:${this._signed(s.con)}` +
      ` INT:${this._signed(s.int)}` +
      ` WIS:${this._signed(s.wis)}` +
      ` CHA:${this._signed(s.cha)}` +
      `${sep}${equip}`;

    // ── Line 3: Inventory ──
    const items = (s.items || []).join(" · ") ||
      '<span style="color:#808080">empty</span>';
    this.statusLine3.innerHTML =
      ` 🎒 ${s.slots_used}/${s.slots_max}  ${items}`;
  },

  _signed(n) {
    return n >= 0 ? `+${n}` : `${n}`;
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
    const title = msg.won ? "⚔️ VICTORY! ⚔️" : "💀 YOU DIED 💀";
    const cause = msg.killed_by
      ? `<p>Killed by ${msg.killed_by}.</p>` : "";
    box.innerHTML = `<h3>${title}</h3>
      ${cause}
      <p>Survived ${msg.turn} turns.</p>
      <br>
      <div class="option">Press any key or click to continue</div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    const dismiss = () => {
      // Send ack so server can clean up
      WS.send({ type: "game_over_ack" });
      // Return to welcome screen
      document.getElementById("game-screen").classList.add("hidden");
      document.getElementById("login-screen").classList.remove("hidden");
      overlay.remove();
    };

    box.addEventListener("click", dismiss, { once: true });
    document.addEventListener("keydown", dismiss, { once: true });
  },
};
