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

  clearLog() {
    this.historyLog.innerHTML = "";
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
    NHC.stats = s;

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
    // Hunger state
    const hVal = s.hunger != null ? s.hunger : 900;
    const HL = NHC.labels || {};
    let hungerLabel, hungerColor;
    if (hVal > 1000) {
      hungerLabel = HL.hunger_satiated || "Satiated";
      hungerColor = "#88FF88";
    } else if (hVal > 300) {
      hungerLabel = HL.hunger_normal || "Normal";
      hungerColor = "#AAAAAA";
    } else if (hVal > 100) {
      hungerLabel = HL.hunger_hungry || "Hungry";
      hungerColor = "#FFAA44";
    } else {
      hungerLabel = HL.hunger_starving || "Starving!";
      hungerColor = "#FF4444";
    }

    // Line 1 differs by mode: hex shows day + time-of-day;
    // dungeon shows depth + turn.
    let locationPart;
    if (s.hex_mode) {
      const dayLabel = (NHC.labels && NHC.labels.hex_day) || "Day";
      locationPart =
        ` 📍 <b>${s.level_name || "?"}</b>` +
        `${sep}📅 ${dayLabel} ${s.hex_day || 1}` +
        `${sep}🕐 ${s.hex_time || "?"}`;
    } else {
      locationPart =
        ` 📍 <b>${s.level_name || "?"}</b>` +
        `${sep}⬇ ${s.depth}` +
        `${sep}⏳ ${s.turn}`;
    }
    this.statusLine1.innerHTML = locationPart +
      `${sep}${(NHC.labels && NHC.labels.lv) || "Lv"} ${s.plevel} (${s.xp}/${s.xp_next} ${(NHC.labels && NHC.labels.xp) || "XP"})` +
      `${sep}💰 <span style="color:#FFFF44">${s.gold}</span>` +
      `${sep}❤️  <span style="color:${hpColor}">${hpBar} ${hp}/${hpMax}</span>` +
      `${sep}🍖 <span style="color:${hungerColor}">${hungerLabel}</span>`;

    // ── Line 2: Name, stats, equipment (interactive) ──
    const name = s.char_name || "?";
    const bg = s.char_bg ? ` (${s.char_bg})` : "";
    const L = NHC.labels || {};
    this.statusLine2.innerHTML =
      ` <b>${name}</b>${bg}` +
      `${sep}${L.stat_str || "STR"}:${this._signed(s.str)}` +
      ` ${L.stat_dex || "DEX"}:${this._signed(s.dex)}` +
      ` ${L.stat_con || "CON"}:${this._signed(s.con)}` +
      ` ${L.stat_int || "INT"}:${this._signed(s.int)}` +
      ` ${L.stat_wis || "WIS"}:${this._signed(s.wis)}` +
      ` ${L.stat_cha || "CHA"}:${this._signed(s.cha)}` +
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
      empty.textContent = (NHC.labels && NHC.labels.empty) || "empty";
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
    const L = NHC.labels || {};
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
    if (NHC.stats && NHC.stats.has_henchmen) {
      actions.push({ action: "give", label: L.give || "Give" });
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

    const L = NHC.labels || {};
    const h3 = document.createElement("h3");
    h3.textContent = L.inventory_title || "Inventory";
    box.appendChild(h3);

    // Equipment section
    if (equipped.length > 0) {
      const eqHead = document.createElement("div");
      eqHead.className = "inv-section-header";
      eqHead.textContent = L.equipment_section || "Equipment:";
      box.appendChild(eqHead);

      equipped.forEach(it => {
        const row = this._createInvRow(it, overlay);
        box.appendChild(row);
      });
    }

    // Backpack section
    const bpHead = document.createElement("div");
    bpHead.className = "inv-section-header";
    const bpTpl = L.backpack_section || "Backpack ({count} items):";
    bpHead.textContent = bpTpl.replace("{count}", backpack.length);
    box.appendChild(bpHead);

    if (backpack.length === 0) {
      const empty = document.createElement("div");
      empty.className = "inv-row";
      empty.style.color = "#808080";
      empty.textContent = "  " + (L.inventory_empty || "(empty)");
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
    closeBtn.textContent = L.close_button || "[Close]";
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

  /**
   * Minimal Markdown renderer for the help dialog. Supports the
   * subset our help_*.md files use: # / ## / ### headings, **bold**,
   * `inline code`, - and numbered lists (with indented continuation
   * lines), and blocks of 2+ space-indented lines rendered as <pre>
   * so the aligned keybinding tables keep their columns.
   */
  _renderMarkdown(md) {
    const esc = (s) =>
      s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const inline = (s) =>
      esc(s)
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");

    const lines = md.replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      if (h) {
        out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
        i++;
        continue;
      }
      // 2+ space indented → preformatted block (preserves table alignment)
      if (/^ {2,}\S/.test(line)) {
        const block = [];
        while (
          i < lines.length &&
          (/^ {2,}/.test(lines[i]) || lines[i] === "")
        ) {
          block.push(lines[i]);
          i++;
        }
        while (block.length && block[block.length - 1] === "") block.pop();
        out.push(`<pre>${block.map(esc).join("\n")}</pre>`);
        continue;
      }
      // Numbered list
      if (/^\d+\.\s/.test(line)) {
        const items = [];
        while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
          let content = lines[i].replace(/^\d+\.\s+/, "");
          i++;
          while (i < lines.length && /^ {3,}\S/.test(lines[i])) {
            content += " " + lines[i].trim();
            i++;
          }
          items.push(`<li>${inline(content)}</li>`);
        }
        out.push(`<ol>${items.join("")}</ol>`);
        continue;
      }
      // Bullet list
      if (/^-\s/.test(line)) {
        const items = [];
        while (i < lines.length && /^-\s/.test(lines[i])) {
          let content = lines[i].replace(/^-\s+/, "");
          i++;
          while (i < lines.length && /^ {2,}\S/.test(lines[i])) {
            content += " " + lines[i].trim();
            i++;
          }
          items.push(`<li>${inline(content)}</li>`);
        }
        out.push(`<ul>${items.join("")}</ul>`);
        continue;
      }
      if (line.trim() === "") {
        i++;
        continue;
      }
      // Plain paragraph — collect consecutive non-block lines
      const para = [];
      while (
        i < lines.length &&
        lines[i].trim() !== "" &&
        !/^(#{1,3}\s|-\s|\d+\.\s|\s{2,}\S)/.test(lines[i])
      ) {
        para.push(lines[i]);
        i++;
      }
      // Heuristic: if a line ends with a sentence terminator, the
      // author intended a line break (e.g. the "Bumping..." block);
      // otherwise treat as soft-wrapped prose and join with a space.
      let html = "";
      for (let k = 0; k < para.length; k++) {
        html += inline(para[k]);
        if (k < para.length - 1) {
          html += /[.!?]$/.test(para[k]) ? "<br>" : " ";
        }
      }
      out.push(`<p>${html}</p>`);
    }
    return out.join("\n");
  },

  showHelp() {
    const L = NHC.labels || {};
    const overlay = document.createElement("div");
    overlay.id = "menu-overlay";
    const box = document.createElement("div");
    box.className = "menu-box help-box";
    const hTitle = L.help_title || "Help";
    const hLoad = L.help_loading || "Loading...";
    const hHint = L.help_close_hint || "Press ESC or click to close";
    box.innerHTML = `<h3>${hTitle}</h3>
      <div id="help-content" class="help-content">${hLoad}</div>
      <div class="option" style="margin-top:12px;text-align:center">
        ${hHint}
      </div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // Fetch help from the server
    const lang = document.getElementById("lang-select")?.value || "en";
    fetch(`/api/help/${lang}`)
      .then(r => r.text())
      .then(text => {
        document.getElementById("help-content").innerHTML =
          this._renderMarkdown(text);
      })
      .catch(() => {
        document.getElementById("help-content").textContent =
          L.help_unavailable || "Help not available.";
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
    const L = NHC.labels || {};
    const overlay = document.createElement("div");
    overlay.id = "menu-overlay";
    const box = document.createElement("div");
    box.className = "menu-box menu-box-wide";
    const vicTitle = L.victory_title || "VICTORY!";
    const deathTitle = L.death_title || "YOU DIED";
    const title = msg.won ? `⚔️ ${vicTitle} ⚔️` : `💀 ${deathTitle} 💀`;
    const causeTpl = L.death_cause || "Killed by {cause}.";
    const cause = msg.killed_by
      ? `<p>${causeTpl.replace("{cause}", msg.killed_by)}</p>` : "";
    const footerTpl = L.end_footer || "Survived {turn} turns.";
    const footer = footerTpl.replace("{turn}", msg.turn);
    const cont = L.game_continue || "Press any key or click to continue";
    box.innerHTML = `<h3>${title}</h3>
      ${cause}
      <p>${footer}</p>
      <div id="game-over-ranking" class="ranking-block"></div>
      <br>
      <div class="option">${cont}</div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // Notify server we've seen the game-over screen so it can
    // record the score before the session is destroyed, then
    // fetch the refreshed ranking for display.
    WS.send({ type: "game_over_ack" });
    // Small delay so the server-side score submission has a chance
    // to hit the leaderboard before we query it (the WS handler
    // writes the entry on disconnect / teardown).
    setTimeout(() => {
      const host = document.getElementById("game-over-ranking");
      if (host) UI.renderRankingInto(host, 10);
    }, 150);

    const dismiss = () => {
      overlay.remove();
      NHC.returnToWelcome();
    };

    box.addEventListener("click", dismiss, { once: true });
    document.addEventListener("keydown", dismiss, { once: true });
  },

  /**
   * Fetch /api/ranking and render a table into *host*.  Uses
   * NHC.labels when populated (in-game) and falls back to
   * window.NHC_WELCOME_LABELS on the welcome screen.
   */
  async renderRankingInto(host, limit = 10) {
    const L = Object.assign(
      {},
      window.NHC_WELCOME_LABELS || {},
      NHC.labels || {},
    );
    host.innerHTML = `<p class="ranking-loading">...</p>`;
    try {
      const resp = await fetch(`/api/ranking?limit=${limit}`);
      if (!resp.ok) {
        host.innerHTML = `<p>HTTP ${resp.status}</p>`;
        return;
      }
      const data = await resp.json();
      const entries = data.entries || [];
      if (entries.length === 0) {
        host.innerHTML =
          `<p class="ranking-empty">${L.ranking_empty || "No scores yet."}</p>`;
        return;
      }
      const esc = (s) => String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
      const head = `<tr>
        <th>${L.ranking_col_rank || "#"}</th>
        <th>${L.ranking_col_name || "Name"}</th>
        <th>${L.ranking_col_score || "Score"}</th>
        <th>${L.ranking_col_depth || "Depth"}</th>
        <th>${L.ranking_col_turns || "Turns"}</th>
        <th>${L.ranking_col_fate || "Fate"}</th>
      </tr>`;
      const rows = entries.map((e) => {
        const fate = e.won
          ? `<span class="fate-won">${L.ranking_fate_won || "Escaped"}</span>`
          : `<span class="fate-died">${L.ranking_fate_died || "Slain"}${
              e.killed_by ? " — " + esc(e.killed_by) : ""}</span>`;
        return `<tr>
          <td>${e.rank}</td>
          <td>${esc(e.name)}</td>
          <td>${e.score}</td>
          <td>${e.depth}</td>
          <td>${e.turn}</td>
          <td>${fate}</td>
        </tr>`;
      }).join("");
      host.innerHTML =
        `<table class="ranking-table"><thead>${head}</thead>` +
        `<tbody>${rows}</tbody></table>`;
    } catch (err) {
      host.innerHTML = `<p class="ranking-error">${err}</p>`;
    }
  },

  showRanking() {
    const L = Object.assign(
      {},
      window.NHC_WELCOME_LABELS || {},
      NHC.labels || {},
    );
    const overlay = document.createElement("div");
    overlay.id = "menu-overlay";
    const box = document.createElement("div");
    box.className = "menu-box menu-box-wide";
    box.innerHTML = `
      <h3>🏆 ${L.ranking_title || "Top Adventurers"} 🏆</h3>
      <div id="ranking-host" class="ranking-block"></div>
      <br>
      <div class="option">${L.ranking_close || "Close"}</div>`;
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    UI.renderRankingInto(document.getElementById("ranking-host"), 10);

    const dismiss = () => overlay.remove();
    box.addEventListener("click", dismiss, { once: true });
    const onKey = (e) => {
      if (e.key === "Escape" || e.key === "Enter") {
        dismiss();
        document.removeEventListener("keydown", onKey);
      }
    };
    document.addEventListener("keydown", onKey);
  },

  applyLabels(labels) {
    // Update elements that exist before the game screen loads
    const helpBtn = document.getElementById("help-btn");
    if (helpBtn) helpBtn.title = labels.help_button || "Help (?)";
    const input = document.querySelector("#typed-input input");
    if (input) input.placeholder = labels.input_placeholder || "Type a command...";
  },
};
