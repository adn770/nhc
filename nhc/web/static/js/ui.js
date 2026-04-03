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

  /**
   * Store static stats (char_name, abilities, etc.) that only
   * change on level-up or floor transitions.
   */
  setStaticStats(s) {
    this._staticStats = s;
  },

  updateStatus(s) {
    // Merge static + dynamic stats
    s = Object.assign({}, this._staticStats || {}, s);
    if (!s.hp_max) return;
    this._currentStats = s;

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

    // ── Line 2: Name, stats, equipment (interactive) ──
    const name = s.char_name || "?";
    const bg = s.char_bg ? ` (${s.char_bg})` : "";
    this.statusLine2.innerHTML =
      ` <b>${name}</b>${bg}` +
      `${sep}STR:${this._signed(s.str)}` +
      ` DEX:${this._signed(s.dex)}` +
      ` CON:${this._signed(s.con)}` +
      ` INT:${this._signed(s.int)}` +
      ` WIS:${this._signed(s.wis)}` +
      ` CHA:${this._signed(s.cha)}` +
      sep;

    // Build interactive equipment spans from equipped_items
    const eqItems = s.equipped_items || this.equippedItems || [];
    const eqLabels = [];
    eqItems.forEach(it => {
      const icon = this._typeIcon(it.types || []);
      eqLabels.push({ label: `${icon} ${it.name}`, item: it });
    });
    eqLabels.push({ label: `${s.ac_label} ${s.ac}`, item: null });

    eqLabels.forEach((entry, idx) => {
      if (idx > 0) {
        this.statusLine2.appendChild(document.createTextNode(sep));
      }
      const span = document.createElement("span");
      span.textContent = entry.label;
      if (entry.item) {
        span.className = "inv-item";
        span.addEventListener("click", (e) => {
          e.stopPropagation();
          this._itemPrimaryAction(entry.item);
        });
        span.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          e.stopPropagation();
          this._showItemContextMenu(e.clientX, e.clientY, entry.item);
        });
      }
      this.statusLine2.appendChild(span);
    });

    // ── Line 3: Inventory (interactive) ──
    if (s.items) this.currentItems = s.items;
    if (s.equipped_items) this.equippedItems = s.equipped_items;
    const rawItems = this.currentItems || [];
    this.statusLine3.textContent = "";

    const prefix = document.createElement("span");
    prefix.textContent = ` 🎒 ${s.slots_used}/${s.slots_max}  `;
    this.statusLine3.appendChild(prefix);

    if (rawItems.length === 0) {
      const empty = document.createElement("span");
      empty.style.color = "#808080";
      empty.textContent = "empty";
      this.statusLine3.appendChild(empty);
    } else {
      rawItems.forEach((it, idx) => {
        if (idx > 0) {
          const sep = document.createTextNode(" · ");
          this.statusLine3.appendChild(sep);
        }
        const isObj = typeof it === "object";
        const span = document.createElement("span");
        span.className = "inv-item";
        span.textContent = isObj ? it.name : it;
        if (isObj) {
          span.dataset.itemId = it.id;
          span.dataset.types = JSON.stringify(it.types);
          span.dataset.equipped = it.equipped;
          span.addEventListener("click", (e) => {
            e.stopPropagation();
            this._itemPrimaryAction(it);
          });
          span.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            e.stopPropagation();
            this._showItemContextMenu(e.clientX, e.clientY, it);
          });
        }
        this.statusLine3.appendChild(span);
      });
    }
  },

  _itemPrimaryAction(item) {
    const types = item.types || [];
    let action;
    if (types.includes("consumable")) action = "quaff";
    else if (types.includes("wand")) action = "zap";
    else if (types.includes("weapon") || types.includes("armor") ||
             types.includes("shield") || types.includes("helmet") ||
             types.includes("ring")) {
      action = item.equipped ? "unequip" : "equip";
    } else {
      action = "use";
    }
    WS.send({ type: "item_action", action, item_id: item.id });
  },

  _itemContextActions(item) {
    const types = item.types || [];
    const L = this._actionLabels || {};
    const actions = [];
    if (types.includes("consumable")) {
      actions.push({ action: "use", label: L.use || "Use" });
      actions.push({ action: "quaff", label: L.quaff || "Quaff" });
    }
    if (types.includes("wand")) {
      actions.push({ action: "zap", label: L.zap || "Zap" });
    }
    if (types.includes("weapon") || types.includes("armor") ||
        types.includes("shield") || types.includes("helmet") ||
        types.includes("ring")) {
      const act = item.equipped ? "unequip" : "equip";
      actions.push({
        action: act,
        label: L[act] || (item.equipped ? "Unequip" : "Equip"),
      });
    }
    if (types.includes("throwable")) {
      actions.push({ action: "throw", label: L.throw || "Throw" });
    }
    actions.push({ action: "drop", label: L.drop || "Drop" });
    return actions;
  },

  _showItemContextMenu(x, y, item) {
    this._dismissContextMenu();
    const actions = this._itemContextActions(item);
    const menu = document.createElement("div");
    menu.id = "context-menu";
    menu.style.left = x + "px";
    menu.style.top = y + "px";

    actions.forEach(({ action, label }) => {
      const div = document.createElement("div");
      div.className = "ctx-option";
      div.textContent = label;
      div.addEventListener("click", (e) => {
        e.stopPropagation();
        WS.send({ type: "item_action", action, item_id: item.id });
        this._dismissContextMenu();
      });
      menu.appendChild(div);
    });

    document.body.appendChild(menu);
    // Dismiss on outside click or ESC
    const dismiss = (e) => {
      if (!menu.contains(e.target)) {
        this._dismissContextMenu();
        document.removeEventListener("click", dismiss);
        document.removeEventListener("keydown", onKey);
      }
    };
    const onKey = (e) => {
      if (e.key === "Escape") {
        this._dismissContextMenu();
        document.removeEventListener("click", dismiss);
        document.removeEventListener("keydown", onKey);
      }
    };
    setTimeout(() => {
      document.addEventListener("click", dismiss);
      document.addEventListener("keydown", onKey);
    }, 0);
  },

  _dismissContextMenu() {
    const existing = document.getElementById("context-menu");
    if (existing) existing.remove();
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

  _typeIcon(types) {
    if (types.includes("weapon")) return "⚔️";
    if (types.includes("armor")) return "🛡️";
    if (types.includes("shield")) return "🛡️";
    if (types.includes("helmet")) return "🪖";
    if (types.includes("ring")) return "💍";
    if (types.includes("wand")) return "✨";
    if (types.includes("consumable")) return "🧪";
    return "📦";
  },

  showInventoryPanel() {
    const equipped = this.equippedItems || [];
    const backpack = (this.currentItems || []).filter(
      it => typeof it === "object"
    );

    const overlay = document.createElement("div");
    overlay.id = "menu-overlay";

    const box = document.createElement("div");
    box.className = "menu-box inv-panel";

    const h3 = document.createElement("h3");
    h3.textContent = "Inventory";
    box.appendChild(h3);

    // Equipment section
    if (equipped.length > 0) {
      const eqHead = document.createElement("div");
      eqHead.className = "inv-section-header";
      eqHead.textContent = "Equipment:";
      box.appendChild(eqHead);

      equipped.forEach(it => {
        const row = this._createInvRow(it, overlay);
        box.appendChild(row);
      });
    }

    // Backpack section
    const bpHead = document.createElement("div");
    bpHead.className = "inv-section-header";
    bpHead.textContent = `Backpack (${backpack.length} items):`;
    box.appendChild(bpHead);

    if (backpack.length === 0) {
      const empty = document.createElement("div");
      empty.className = "inv-row";
      empty.style.color = "#808080";
      empty.textContent = "  (empty)";
      box.appendChild(empty);
    } else {
      backpack.forEach(it => {
        const row = this._createInvRow(it, overlay);
        box.appendChild(row);
      });
    }

    // Close button
    const closeBtn = document.createElement("div");
    closeBtn.className = "option";
    closeBtn.style.textAlign = "center";
    closeBtn.style.marginTop = "12px";
    closeBtn.textContent = "[Close]";
    closeBtn.addEventListener("click", () => overlay.remove());
    box.appendChild(closeBtn);

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    const onKey = (e) => {
      if (e.key === "Escape" || e.key === "i") {
        overlay.remove();
        document.removeEventListener("keydown", onKey);
      }
    };
    document.addEventListener("keydown", onKey);
  },

  _createInvRow(item, overlay) {
    const row = document.createElement("div");
    row.className = "inv-row";
    const icon = this._typeIcon(item.types || []);
    let label = `${icon} ${item.name}`;
    if (item.charges) {
      label += ` (${item.charges[0]}/${item.charges[1]})`;
    }
    const nameSpan = document.createElement("span");
    nameSpan.className = "inv-item-name";
    nameSpan.textContent = label;
    row.appendChild(nameSpan);

    // Left-click: primary action
    row.addEventListener("click", (e) => {
      e.stopPropagation();
      this._itemPrimaryAction(item);
      overlay.remove();
    });
    // Right-click: context menu
    row.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this._showItemContextMenu(e.clientX, e.clientY, item);
    });
    return row;
  },

  showHelp() {
    const overlay = document.createElement("div");
    overlay.id = "menu-overlay";
    const box = document.createElement("div");
    box.className = "menu-box help-box";
    box.innerHTML = `<h3>Help</h3><pre id="help-content">Loading...</pre>
      <div class="option" style="margin-top:12px;text-align:center">
        Press ESC or click to close
      </div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // Fetch help from the server
    const lang = document.getElementById("lang-select")?.value || "en";
    fetch(`/api/help/${lang}`)
      .then(r => r.text())
      .then(text => {
        document.getElementById("help-content").textContent = text;
      })
      .catch(() => {
        document.getElementById("help-content").textContent =
          "Help not available.";
      });

    const dismiss = () => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (e) => {
      if (e.key === "Escape" || e.key === "?") dismiss();
    };
    overlay.addEventListener("click", dismiss);
    document.addEventListener("keydown", onKey);
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
