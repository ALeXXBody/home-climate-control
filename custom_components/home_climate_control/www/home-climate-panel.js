/**
 * Home Climate — sidebar panel (custom element).
 * Properties set by HA: hass, narrow, panel
 */
class HomeClimatePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._status = null;
    this._tab = "home";
    this._loading = true;
    this._error = null;
    this._notice = null;
    this._addingRoom = false;
    this._editingZone = null;
    this._busy = {};
    this._poll = null;
    this._selectedBoardId = null;
    this._drafts = {};
  }

  set hass(hass) {
    const first = this._hass == null;
    this._hass = hass;
    if (first) {
      this._wireOnce();
      this._render();
      this._refresh();
      this._poll = setInterval(() => this._refresh(), 5000);
      this._otaFast = setInterval(() => {
        const active = (this._status?.devices || []).some((d) =>
          HomeClimatePanel.OTA_ACTIVE.has(d.ota_state)
        );
        if (active || this._tab === "devices") this._refresh();
      }, 2000);
    }
  }

  /* ── One-time delegated event wiring ──────────────────────────────
     All listeners live on the shadow ROOT, so they survive every
     innerHTML swap (polls, tab switches). No re-binding ever. */
  _wireOnce() {
    const root = this.shadowRoot;

    root.addEventListener("click", (ev) => {
      const t = ev.target;
      // Settings switches are controls, never navigation. Stop the click at
      // the panel root so HA or another delegated handler cannot interpret it
      // as a dashboard navigation gesture.
      if (t.closest && t.closest(".hcc-switch")) {
        ev.stopPropagation();
        return;
      }
      const fp = t.closest("[data-fp-zone]");
      if (fp) {
        this._fpFlashName = fp.getAttribute("data-fp-zone");
        this._tab = "rooms";
        this._render();
        return;
      }
      const tab = t.closest("[data-tab]");
      if (tab) {
        this._tab = tab.getAttribute("data-tab");
        if (this._tab !== "settings") this._soptMsg = null;
        this._render();
        return;
      }
      if (t.closest('[data-action="refresh"]')) {
        this._loading = true;
        this._render();
        this._refresh();
        return;
      }
      const za = t.closest("[data-zone-action]");
      if (za) {
        this._onZoneAction(za);
        return;
      }
      const fw = t.closest("[data-fw-action]");
      if (fw) {
        this._onFwAction(fw);
        return;
      }
      const otl = t.closest("[data-otlog]");
      if (otl) {
        this._fetchOtLog(otl.getAttribute("data-otlog") === "clear");
        return;
      }
      if (t.closest('[data-action="save-board"]')) {
        this._onSaveBoard();
        return;
      }
      if (t.closest('[data-action="save-failsafe"]')) {
        this._onSaveFailsafe();
        return;
      }
      if (t.closest('[data-action="save-boiler-info"]')) {
        this._onSaveBoilerInfo();
        return;
      }
      const sopt = t.closest("[data-sopt-save]");
      if (sopt) {
        this._onSoptSave(sopt.getAttribute("data-sopt-save"));
        return;
      }
      if (t.closest("[data-occ-add]")) {
        this._occAddTracker();
        return;
      }
      const occRm = t.closest("[data-occ-remove]");
      if (occRm) {
        this._occRemoveTracker(occRm.getAttribute("data-occ-remove"));
        return;
      }
      this._onBoardClick(ev); // board/WC controls (no-op when unmatched)
    });

    root.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      const t = ev.target;
      if (t.classList && t.classList.contains("temp-input")) {
        ev.preventDefault();
        const id = t.getAttribute("data-entity");
        const v = parseFloat(t.value);
        if (id && Number.isFinite(v)) this._setZone(id, { temperature: v });
      }
    });
    root.addEventListener("change", (ev) => {
      const t = ev.target;
      if (t.classList && t.classList.contains("sopt-live")) {
        this._setOptions({ [t.dataset.sopt]: t.checked });
        return;
      }
      if (t.classList && t.classList.contains("temp-input")) {
        // Typed + committed (blur/Enter) — send like the Set button.
        const id = t.getAttribute("data-entity");
        const v = parseFloat(t.value);
        if (id && Number.isFinite(v)) this._setZone(id, { temperature: v });
        return;
      }
      if (t.dataset && t.dataset.rangeLive != null) {
        this._sendCtl(t.dataset.ctlNode, t.dataset.ctlKey, Number(t.value));
        return;
      }
      if (t.matches("[data-zone-mode]")) {
        this._setZone(t.getAttribute("data-entity"), { hvac_mode: t.value });
      } else if (t.matches("[data-zone-preset]")) {
        this._setZone(t.getAttribute("data-entity"), { preset_mode: t.value });
      } else if (t.matches("[data-zone-floor]")) {
        const zoneName = t.getAttribute("data-zone-name");
        if (zoneName)
          this._adminZone("rename_zone", {
            zone: zoneName,
            floor: parseInt(t.value, 10),
          });
      } else if (t.id === "hcc-bi-make") {
        this._fillBoilerModels(this._boilerCat, null);
      } else if (t.id === "hcc-bs-device") {
        this._bsSel = t.value;
        this._bsDraft = null;
        this._render();
      } else if (t.id === "hcc-otlog-node") {
        this._otlogNodeId = t.value;
        this._otlogLines = null;
        this._fetchOtLog();
      } else if (t.id === "hcc-board-sel") {
        this._selectedBoardId = t.value;
        this._renderBoardPreview();
      }
    });

    root.addEventListener("input", (ev) => {
      this._boardDraftFromEvent(ev);
      const el = ev.target;
      if (el.getAttribute && el.getAttribute("data-bs-field")) {
        const node =
          this._bsSel || root.getElementById("hcc-bs-device")?.value;
        if (!node) return;
        const d =
          this._bsDraft && this._bsDraft.node === node
            ? this._bsDraft
            : (this._bsDraft = { node, v: {} });
        d.v[el.getAttribute("data-bs-field")] = el.value;
      }
    });
  }

  get hass() {
    return this._hass;
  }

  set narrow(v) {
    this._narrow = Boolean(v);
    this._render();
  }

  get narrow() {
    return this._narrow;
  }

  set panel(p) {
    this._panel = p;
  }

  disconnectedCallback() {
    if (this._poll) {
      clearInterval(this._poll);
      this._poll = null;
    }
    if (this._otaFast) {
      clearInterval(this._otaFast);
      this._otaFast = null;
    }
  }

  _boardDraftFromEvent(ev) {
    const t = ev.target;
    if (t.dataset.draftNode && t.dataset.draftKey) {
      this._drafts[`${t.dataset.draftNode}:${t.dataset.draftKey}`] = t.value;
      // keep paired range/number inputs in sync
      if (t.dataset.rangeFor) {
        const root = this.shadowRoot;
        root.querySelectorAll(
          `[data-draft-node="${t.dataset.draftNode}"][data-draft-key="${t.dataset.rangeFor}"]`
        ).forEach((el) => {
          if (el !== t) el.value = t.value;
        });
      }
    }
  }

  _ctlPayload(btn) {
    const node = btn.dataset.ctlNode;
    const key = btn.dataset.ctlKey;
    let value = btn.dataset.ctlValue;
    if (btn.dataset.ctlFromInput) {
      const root = this.shadowRoot;
      const inp = root.querySelector(
        `[data-draft-node="${node}"][data-draft-key="${key}"]`
      );
      value = inp ? inp.value : "";
      if (!value) return null;
    } else if (value === "true") value = true;
    else if (value === "false") value = false;
    else if (/^-?\d+(\.\d+)?$/.test(value ?? "")) value = Number(value);
    return { node, key, value };
  }

  async _sendCtl(node, key, value) {
    try {
      await this._hass.callWS({
        type: "home_climate_control/device_control",
        node_id: node,
        key,
        value,
      });
    } catch (err) {
      this._flashNotice(`Control failed (${key}): ${err.message || err}`);
    }
  }

  async _onBoardClick(ev) {
    const wcBtn = ev.target.closest("[data-wc-apply]");
    if (wcBtn) {
      const node = wcBtn.dataset.wcApply;
      const q = (k) =>
        this.shadowRoot.querySelector(
          `[data-draft-node="${node}"][data-draft-key="${k}"]`
        );
      const curve = {};
      for (const k of ["wc_ref", "wc_design", "wc_fmax", "wc_fmin"]) {
        const el = q(k);
        if (el && el.value !== "") curve[k] = Number(el.value);
      }
      try {
        await this._hass.callWS({
          type: "home_climate_control/device_control",
          node_id: node,
          key: "weather_comp_cfg",
          curve,
        });
      } catch (err) {
        this._flashNotice(`WC apply failed: ${err.message || err}`);
      }
      return;
    }
    const btn = ev.target.closest("[data-ctl-key]");
    if (!btn) return;
    const payload = this._ctlPayload(btn);
    if (!payload) return;
    btn.disabled = true;
    setTimeout(() => { btn.disabled = false; }, 800);
    await this._sendCtl(payload.node, payload.key, payload.value);
  }

  /** Skip re-render while the user is editing board controls. */
  static _boardEditing(root) {
    const a = root.activeElement;
    if (a && a.dataset && (a.dataset.draftKey != null || a.dataset.rangeLive != null))
      return true;
    return false;
  }

  async _onSaveBoard() {
    const node =
      this._bsSel || this.shadowRoot.getElementById("hcc-bs-device")?.value;
    if (!node || !this._hass) return;
    const fields = {};
    this.shadowRoot.querySelectorAll("[data-bs-field]").forEach((el) => {
      const k = el.getAttribute("data-bs-field");
      const v = el.value.trim();
      // password-type inputs: empty means "unchanged" — never send ""
      if (!v && el.type === "password") return;
      fields[k] = k === "mqtt_port" ? parseInt(v, 10) || 1883 : v;
    });
    if (!Object.keys(fields).length) {
      this._flashNotice("Nothing to save.");
      return;
    }
    try {
      await this._hass.callWS({
        type: "home_climate_control/set_device_settings",
        node_id: node,
        settings: fields,
      });
      this._flashNotice("Settings sent — board is saving and will reboot.");
      this._bsDraft = null;
    } catch (err) {
      this._showError(err?.message || String(err));
    }
    setTimeout(() => this._refresh(), 4000);
  }

  async _refresh() {
    if (!this._hass) return;
    // Avoid stacking renders while a flash/reboot is in flight.
    if (Object.keys(this._busy || {}).length) return;
    // Never wipe the DOM while the user is operating a form control
    // (open <select> popup, input being typed in, …) — otherwise the
    // interaction is cancelled by the rebuild.
    const ae = this.shadowRoot.activeElement;
    if (ae && /^(SELECT|INPUT|TEXTAREA)$/.test(ae.tagName)) return;
    try {
      this._status = await this._hass.callWS({
        type: "home_climate_control/get_status",
      });
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    const wasLoading = this._loading;
    this._loading = false;
    if (wasLoading || !this.shadowRoot.getElementById("hcc-ver")) {
      this._render(); // chrome not built yet (first load / Refresh click)
      return;
    }
    this._applyStatus();
  }

  /* True when a form control inside `scope` currently has focus — its
     region must not be swapped while the user is interacting with it. */
  _focusBlocked(scope) {
    const ae = this.shadowRoot.activeElement;
    return Boolean(ae && /^(SELECT|INPUT|TEXTAREA)$/.test(ae.tagName) &&
      (scope === this.shadowRoot || scope.contains(ae)));
  }

  /* Poll-time update: refresh only live regions, never forms.
     The static chrome (header/tabs/footer/forms) is left untouched. */
  _applyStatus() {
    const root = this.shadowRoot;
    const systems = this._systems();
    const sys = systems[0];

    // Chrome-level live bits
    const pill = root.getElementById("hcc-pill");
    if (pill) pill.innerHTML = this._boilerPillHtml(sys);
    const eBox = root.getElementById("hcc-error");
    if (eBox) { eBox.hidden = !this._error; eBox.textContent = this._error || ""; }
    if (!this._notice) {
      const nBox = root.getElementById("hcc-notice");
      if (nBox) { nBox.hidden = true; nBox.textContent = ""; }
    }
    const ver = root.getElementById("hcc-ver");
    if (ver && this._status?.version)
      ver.textContent = `Home Climate Control v${this._status.version}`;

    // Per-tab live region
    switch (this._tab) {
      case "rooms": {
        if (this._addingRoom || this._editingZone) return;
        const w = root.getElementById("hcc-zones-wrap");
        if (w && !this._focusBlocked(w)) {
          w.innerHTML = this._zonesHtml(sys);
          this._applyRoomFlash(root); // survive polls while animating
        }
        break;
      }
      case "devices": {
        this._otAutoTick_();
        const hd = root.getElementById("hcc-fw-head-wrap");
        if (hd && !this._focusBlocked(hd)) hd.innerHTML = this._fwHeadHtml();
        const fw = root.getElementById("hcc-fw-wrap");
        if (fw && !this._focusBlocked(fw)) fw.innerHTML = this._fwCardHtml();
        if (!HomeClimatePanel._boardEditing(root)) {
          const bw = root.getElementById("hcc-board-wrap");
          if (bw && !this._focusBlocked(bw)) {
            bw.innerHTML = this._boardHtml();
            if (this._selectedBoardId) {
              const bsel = root.getElementById("hcc-board-sel");
              if (bsel) bsel.value = this._selectedBoardId;
            }
            this._renderBoardPreview();
          }
        }
        break;
      }
      case "diagnostics": {
        const w = root.getElementById("hcc-diag-wrap");
        if (w && sys) w.innerHTML = this._settingsLiveHtml(sys);
        break;
      }
      default: { // home
        const w = root.getElementById("hcc-live");
        if (w && sys)
          w.innerHTML =
            this._homeHtml(sys);
        break;
      }
    }
  }

  async _setZone(entityId, patch) {
    if (!this._hass || !entityId) return;
    try {
      this._status = (
        await this._hass.callWS({
          type: "home_climate_control/set_zone",
          entity_id: entityId,
          ...patch,
        })
      ).status;
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._render();
  }

  _systems() {
    return this._status?.systems || [];
  }

  _render() {
    const root = this.shadowRoot;
    const systems = this._systems();
    const sys = systems[0];

    const savedRoom = (this._addingRoom || this._editingZone) ? this._saveAddRoomForm() : null;
    root.innerHTML = `
      <style>
        :host {
          /* Fill whatever container HA gives us and scroll internally.
             This isolates layout from HA ancestors whose transforms would
             otherwise break position:fixed/sticky on the footer. */
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          display: flex;
          flex-direction: column;
          overflow-y: auto;
          background: var(--primary-background-color, #111);
          color: var(--primary-text-color, #eee);
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
          box-sizing: border-box;
        }
        * { box-sizing: border-box; }
        .wrap {
          flex: 1 0 auto;
          display: flex;
          flex-direction: column;
          max-width: 1100px;
          width: 100%;
          margin: 0 auto;
          padding: 16px 20px 16px;
        }
        .bp-hero {
          display: flex; gap: 16px; align-items: stretch; margin-bottom: 12px;
        }
        .bp-hero-img {
          flex: 0 0 132px; display: flex; flex-direction: column;
          justify-content: center; text-align: center;
          background: var(--secondary-background-color, #16181c);
          border: 1px solid var(--divider-color, #2a2e33);
          border-radius: 10px; padding: 8px;
        }
        .bp-hero-img img {
          width: 100%; height: auto; max-height: 118px; object-fit: contain;
          filter: drop-shadow(0 3px 6px rgba(0, 0, 0, 0.5));
        }
        .bp-hero-img .bp-cap {
          font-size: 0.75rem; color: var(--secondary-text-color, #bbb);
          margin-top: 4px; line-height: 1.25;
        }
        .bp-hero-stats {
          flex: 1; min-width: 0; display: flex;
          flex-direction: column; justify-content: center; gap: 6px;
        }
        header {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }
        .hcc-logo {
          width: 34px;
          height: 34px;
          border-radius: 8px;
          flex: none;
        }
        h1 {
          font-size: 1.5rem;
          font-weight: 500;
          margin: 0;
          flex: 1;
        }
        .hdr-alert {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          max-width: 340px;
          overflow: hidden;
          padding: 4px 12px;
          border-radius: 14px;
          font-size: 0.82rem;
          color: #ffb4a9;
          background: rgba(207, 102, 90, 0.18);
          border: 1px solid rgba(207, 102, 90, 0.45);
          white-space: nowrap;
        }
        .hdr-alert-txt {
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .hdr-ok {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 12px;
          border-radius: 14px;
          font-size: 0.82rem;
          color: #9fdcb1;
          background: rgba(76, 175, 80, 0.14);
          border: 1px solid rgba(76, 175, 80, 0.40);
          white-space: nowrap;
        }
        .floor-head {
          font-size: 0.85rem;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          opacity: 0.65;
          margin: 14px 2px 8px;
        }
        .tabs {
          display: flex;
          gap: 4px;
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
          scrollbar-width: none;
          margin-bottom: 20px;
          border-bottom: 1px solid var(--divider-color, #333);
          padding-bottom: 8px;
        }
        .tabs::-webkit-scrollbar { display: none; }
        .tab {
          background: transparent;
          border: none;
          color: var(--secondary-text-color, #aaa);
          padding: 8px 14px;
          border-radius: 8px 8px 0 0;
          cursor: pointer;
          font-size: 0.95rem;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .tab.active {
          color: var(--primary-color, #03a9f4);
          background: var(--secondary-background-color, #1c1c1c);
          font-weight: 600;
        }
        @media (max-width: 480px) {
          .tabs { gap: 0; padding-bottom: 4px; }
          .tab { padding: 8px 10px; font-size: 0.85rem; }
        }
        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 12px;
          margin-bottom: 20px;
        }
        .card {
          background: var(--card-background-color, var(--secondary-background-color, #1c1c1c));
          border-radius: 12px;
          padding: 16px;
          box-shadow: var(--ha-card-box-shadow, none);
          border: 1px solid var(--divider-color, #2a2a2a);
        }
        .card h3 {
          margin: 0 0 8px;
          font-size: 0.85rem;
          font-weight: 500;
          color: var(--secondary-text-color, #aaa);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .metric {
          font-size: 1.75rem;
          font-weight: 400;
          line-height: 1.2;
        }
        .unit { font-size: 1rem; opacity: 0.7; margin-left: 2px; }
        .sub { font-size: 0.85rem; color: var(--secondary-text-color, #aaa); margin-top: 6px; }
        .settings-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
          gap: 14px;
          align-items: start;
        }
        .settings-grid > .card {
          min-width: 0;
          height: 100%;
          box-sizing: border-box;
        }
        .settings-grid > .card h3 {
          color: var(--primary-text-color, inherit);
          font-size: .92rem;
          letter-spacing: .02em;
          text-transform: none;
          padding-bottom: 9px;
          border-bottom: 1px solid var(--divider-color, #2a2a2a);
        }
        .settings-grid > .card > label:not(.hcc-switch) {
          display: block;
          font-size: .78rem;
          color: var(--secondary-text-color, #aaa);
          margin: 10px 0 5px;
        }
        .settings-grid input[type="number"],
        .settings-grid select {
          box-sizing: border-box;
          min-height: 38px;
        }
        .hcc-switch {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 12px 0;
          position: relative; /* anchors the hidden input inside the row */
          color: var(--primary-text-color, inherit);
          font-size: .9rem;
          cursor: pointer;
          white-space: nowrap;
          width: fit-content;
        }
        .hcc-switch input {
          position: absolute;
          opacity: 0;
          width: 1px;
          height: 1px;
        }
        .hcc-switch-track {
          /* MUST be non-inline: bare <span> ignores width/height, which
             collapsed the pill to zero width (the knob then floated free
             over the text). */
          display: inline-block;
          position: relative;
          width: 42px;
          height: 24px;
          flex: 0 0 auto;
          border-radius: 999px;
          background: var(--disabled-text-color, #777);
          transition: background .18s ease;
        }
        .hcc-switch-track::after {
          content: "";
          position: absolute;
          top: 3px;
          left: 3px;
          width: 18px;
          height: 18px;
          border-radius: 50%;
          background: #fff;
          box-shadow: 0 1px 3px #0006;
          transition: transform .18s ease, background .18s ease;
        }
        .hcc-switch input:checked + .hcc-switch-track {
          /* solid green — same Material green as the header status pill */
          background: #4caf50;
        }
        .hcc-switch input:checked + .hcc-switch-track::after {
          transform: translateX(18px);
          background: #fff;
        }
        .hcc-switch input:focus-visible + .hcc-switch-track {
          outline: 2px solid var(--primary-color, #03a9f4);
          outline-offset: 2px;
        }
        .settings-save {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 14px;
          padding-top: 10px;
          border-top: 1px solid var(--divider-color, #2a2a2a);
        }
        .settings-save button { margin-top: 0 !important; }
        .chips {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin: 6px 0;
        }
        .chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 6px 4px 12px;
          border-radius: 999px;
          background: var(--secondary-background-color, #1c1c1c);
          border: 1px solid var(--divider-color, #2a2a2a);
          font-size: .85rem;
          max-width: 100%;
        }
        .chip button {
          background: none;
          border: none;
          color: var(--secondary-text-color, #999);
          cursor: pointer;
          padding: 0 4px;
          font-size: .95rem;
          line-height: 1;
        }
        .chip button:hover { color: var(--primary-color, #03a9f4); }
        .occ-add-row {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .occ-add-row select { flex: 1; }
        .occ-add-row button {
          padding: 8px 14px;
          white-space: nowrap;
        }
        @media (max-width: 620px) {
          .settings-grid { grid-template-columns: 1fr; }
        }
        .badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 999px;
          font-size: 0.75rem;
          font-weight: 600;
          text-transform: uppercase;
        }
        .badge.on { background: #1b5e20; color: #c8e6c9; }
        .badge.off { background: #333; color: #bbb; }
        .badge.heat { background: #e65100; color: #ffe0b2; }
        .ota-wrap { margin-top: 10px; }
        .ota-label { font-size: 12px; color: #9fb3c8; margin-bottom: 4px; }
        .ota-bar {
          height: 8px; border-radius: 4px; overflow: hidden;
          background: #22303f; position: relative;
        }
        .ota-bar i {
          display: block; height: 100%; min-width: 6%;
          background: linear-gradient(90deg, #2196f3, #64b5f6);
          transition: width .6s ease;
        }
        .ota-bar.ind i {
          width: 35% !important;
          animation: ota-slide 1.1s ease-in-out infinite alternate;
        }
        @keyframes ota-slide {
          from { transform: translateX(-40%); }
          to   { transform: translateX(220%); }
        }
        .ota-fail {
          margin-top: 8px; padding: 8px 10px; border-radius: 8px;
          background: #3a1b1b; border: 1px solid #ef5350; color: #ffcdd2;
          font-size: 13px; display: flex; gap: 8px; align-items: flex-start;
        }
        .ota-done { color: #a5d6a7; font-size: 13px; margin-top: 8px; }
        .zones { display: flex; flex-direction: column; gap: 12px; }
        /* Rooms tab — compact cards */



        #hcc-zones-wrap .card.zone {
          display: block;
          position: relative;
          min-height: 118px;
          padding: 12px 14px;
        }

        /* mode pill — passive indicator, top-right */
        .mode-pill {
          position: absolute; top: 10px; right: 12px;
          font-size: .68rem; letter-spacing: .06em; text-transform: uppercase;
          padding: 3px 10px; border-radius: 999px;
          border: 1px solid var(--divider-color, #333);
          background: var(--secondary-background-color, #16181c);
          opacity: .9; pointer-events: none; z-index: 2;
        }
        .mode-pill.smart { color: #4fc3f7; border-color: #4fc3f755; }
        .mode-pill.manual { color: #ffb74d; border-color: #ffb74d55; }

        /* 3-col: info | centered tall thermostat | rail under pill */
        #hcc-zones-wrap .z-main {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          align-items: stretch;
          gap: 12px;
          min-height: 94px;
          min-width: 0;
        }
        #hcc-zones-wrap .z-info {
          justify-self: start;
          align-self: center;
          min-width: 0;
          max-width: 100%;
          padding-right: 8px;
        }
        #hcc-zones-wrap .z-left {
          justify-self: center;
          align-self: stretch;
          display: flex;
          align-items: stretch;
        }
        /* right rail: mode|edit / profile|delete — under pill, no overlap */
        #hcc-zones-wrap .z-rail {
          justify-self: end;
          align-self: center;
          width: 200px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding-top: 30px; /* clears mode-pill */
          box-sizing: border-box;
        }
        #hcc-zones-wrap .z-ddcol { display: flex; flex-direction: column; gap: 6px; }
        #hcc-zones-wrap .z-ddrow {
          display: grid;
          grid-template-columns: 1fr 72px;
          gap: 6px 8px;
          align-items: end;
        }
        #hcc-zones-wrap .z-ddrow > div {
          min-width: 0;
        }
        #hcc-zones-wrap .z-ddrow button {
          width: 72px;
          box-sizing: border-box;
          padding: 3px 6px; font-size: .78rem; height: 24px;
          white-space: nowrap;
          background: var(--secondary-background-color, #16181c);
        }
        #hcc-zones-wrap .z-ddrow select {
          width: 100%;
          max-width: 100%;
          box-sizing: border-box;
          height: 24px; padding-top: 0; padding-bottom: 0;
        }
        .z-lbl {
          font-size: .62rem; letter-spacing: .07em; text-transform: uppercase;
          color: var(--secondary-text-color, #999); margin-top: 0;
          display: block;
        }
        #hcc-zones-wrap .z-insights { max-width: 100%; }
        @media (max-width: 720px) {
          #hcc-zones-wrap .z-main {
            grid-template-columns: 1fr;
            min-height: 0;
          }
          #hcc-zones-wrap .z-left { justify-self: center; }
          #hcc-zones-wrap .z-rail {
            width: 100%;
            padding-top: 8px;
            align-self: stretch;
          }
        }

        /* thermostat-style 2-row button cluster — fills card height */
        #hcc-zones-wrap .temp-input,
        #hcc-zones-wrap input[type="number"].z-bigtemp {
          -moz-appearance: textfield;
          appearance: textfield;
        }
        #hcc-zones-wrap .temp-input::-webkit-outer-spin-button,
        #hcc-zones-wrap .temp-input::-webkit-inner-spin-button,
        #hcc-zones-wrap input[type="number"]::-webkit-outer-spin-button,
        #hcc-zones-wrap input[type="number"]::-webkit-inner-spin-button {
          -webkit-appearance: none; margin: 0;
        }
        .z-temp-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          grid-template-rows: 1fr 1fr;
          gap: 5px;
          align-items: stretch;
          height: 100%;
          min-height: 94px;
          width: fit-content;
        }
        #hcc-zones-wrap .z-temp-grid button {
          width: 100%;
          height: 100%;
          padding: 6px 12px;
          min-height: 0;
        }
        .z-temp-grid .z-bigtemp {
          grid-column: 2; grid-row: 1 / 3;
          width: 100%; min-width: 92px;
          height: 100%;
          font-size: 1.45rem; font-weight: 600;
          text-align: center; padding: 4px 8px;
        }
        .z-temp-grid .z-tg { padding: 6px 14px; }
        .z-row2 {
          display: flex; gap: 6px; align-items: center;
          margin-top: 8px; flex-wrap: wrap;
        }
        .z-row2 select { padding: 4px 8px; }


        #hcc-zones-wrap .zones { gap: 14px; }
        #hcc-zones-wrap .floor-head { margin-bottom: 6px; }
        #hcc-zones-wrap .card {
          padding: 10px 14px;
        }
        #hcc-zones-wrap .zone-title { font-size: 1rem; }
        #hcc-zones-wrap .zone-meta { margin-top: 2px; font-size: 0.8rem; }
        #hcc-zones-wrap .controls button,
        #hcc-zones-wrap .temp-row button { padding: 4px 10px; }
        #hcc-zones-wrap .controls select { padding: 4px 8px; }
        .z-insights { margin-top: 2px; font-size: .78rem; color: var(--secondary-text-color,#aaa); }
        .z-insights summary {
          cursor: pointer; opacity: .7; user-select: none;
          list-style: none;
        }
        .z-insights summary::before { content: "▸ "; }
        .z-insights[open] summary::before { content: "▾ "; }
        .z-insights[open] summary { opacity: 1; }

        .zone {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 12px;
          align-items: center;
        }
        @media (max-width: 640px) {
          .zone { grid-template-columns: 1fr; }
          .controls { flex-wrap: wrap; }
          .temp-row { flex-wrap: wrap; }
          .row { flex-wrap: wrap; }
          .row label { flex: 0 0 100%; margin-bottom: 4px; }
          header { gap: 8px; }
          h1 { font-size: 1.2rem; }
        }
        .zone-title { font-size: 1.1rem; font-weight: 500; }
        .zone-meta { font-size: 0.85rem; color: var(--secondary-text-color, #aaa); margin-top: 4px; }
        .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        button, select, input[type="number"] {
          font: inherit;
          border-radius: 8px;
          border: 1px solid var(--divider-color, #444);
          background: var(--primary-background-color, #111);
          color: inherit;
          padding: 8px 12px;
        }
        button {
          cursor: pointer;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          border: none;
          font-weight: 500;
        }
        button.ghost {
          background: transparent;
          color: var(--primary-color, #03a9f4);
          border: 1px solid var(--primary-color, #03a9f4);
        }
        button:disabled { opacity: 0.5; cursor: default; }
        .row { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
        .row label { flex: 0 0 130px; font-size: 0.9rem; }
        .row input, .row select {
          flex: 1; min-width: 0;
          font: inherit; border-radius: 8px;
          border: 1px solid var(--divider-color, #444);
          background: var(--primary-background-color, #111);
          color: inherit; padding: 8px 12px;
        }
        .temp-row { display: flex; align-items: center; gap: 6px; }
        .temp-row input { width: 72px; }
        .error {
          background: #b71c1c33;
          border: 1px solid #ef5350;
          color: #ffcdd2;
          padding: 12px 16px;
          border-radius: 8px;
          margin-bottom: 16px;
        }
        .notice {
          background: #1b5e2033;
          border: 1px solid #66bb6a;
          color: #c8e6c9;
          padding: 12px 16px;
          border-radius: 8px;
          margin-bottom: 16px;
        }
        .empty {
          text-align: center;
          padding: 48px 16px;
          color: var(--secondary-text-color, #aaa);
        }
        .placeholder {
          opacity: 0.85;
          line-height: 1.5;
        }
        .placeholder ul { text-align: left; max-width: 480px; margin: 16px auto; }
        footer {
          margin-top: auto;
          position: sticky;
          bottom: 0;
          padding: 14px 20px;
          background: var(--primary-background-color, #111);
          border-top: 1px solid var(--divider-color, #333);
          font-size: 0.85rem;
          color: var(--secondary-text-color, #aaa);
          display: flex;
          flex-wrap: wrap;
          gap: 12px 20px;
        }
        footer a { color: var(--primary-color, #03a9f4); }
        .refresh { margin-left: auto; }
        .fw-cat {
          display: grid;
          grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
          gap: 16px;
          align-items: start;
        }
        @media (max-width: 700px) {
          .fw-cat { grid-template-columns: 1fr; }
        }

        /* ── Floor plan ─────────────────────────────────────────── */
        .fp-floor-label {
          font-size: .8rem; letter-spacing: .08em; text-transform: uppercase;
          color: var(--secondary-text-color, #aaa); margin: 14px 0 4px;
        }
        .fp-svg { width: 100%; height: auto; display: block; }
        .fp-room { cursor: pointer; }
        .fp-room rect.r {
          rx: 10; ry: 10;
          stroke: var(--divider-color, #333); stroke-width: 1.5;
          transition: filter .15s;
        }
        .fp-room:hover rect.r { filter: brightness(1.35); }
        .fp-room.manual rect.r { stroke-dasharray: 6 4; }
        .fp-name { font-size: 13px; font-weight: 600; fill: #fff; }
        .fp-temp { font-size: 20px; font-weight: 700; fill: #fff; }
        .fp-sub  { font-size: 11px; fill: rgba(255,255,255,.75); }
        .fp-badge { font-size: 11px; }
        .fp-flash { animation: fpflash 1.6s ease-out 2; }
        @keyframes fpflash { 0%,100% { outline: none; } 40% { box-shadow: 0 0 0 3px var(--primary-color,#03a9f4) inset; } }

      </style>
      <div class="wrap">
        <header>
          <img class="hcc-logo" src="/home_climate_control_static/brand/icon.png" alt="Home Climate Control logo">
          <h1>Home Climate ${sys?.demo ? '<span class="badge heat" style="font-size:0.7rem;vertical-align:middle">DEMO</span>' : ""}</h1>
          <span id="hcc-pill">${this._boilerPillHtml(sys)}</span>
          <button class="ghost refresh" type="button" data-action="refresh">Refresh</button>
        </header>
        <nav class="tabs">
          ${this._tabBtn("home", "Home")}
          ${this._tabBtn("rooms", "Rooms")}
          ${this._tabBtn("devices", "Devices")}
          ${this._tabBtn("settings", "Settings")}
          ${this._tabBtn("diagnostics", "Diagnostics")}
        </nav>
        <div id="hcc-error" class="error" ${this._error ? "" : "hidden"}>${this._esc(this._error || "")}</div>
        <div id="hcc-notice" class="notice" ${this._notice ? "" : "hidden"}>${this._esc(this._notice || "")}</div>
        ${this._loading ? `<div class="empty">Loading…</div>` : this._body(sys, systems)}
        <footer>
          <span id="hcc-ver">Home Climate Control${this._status?.version ? ` v${this._status.version}` : ""}</span>
          <a href="https://github.com/ALeXXBody/home-climate-control" target="_blank" rel="noopener">Software</a>
          <a href="https://github.com/ALeXXBody/home-climate-system" target="_blank" rel="noopener">Hardware</a>
          <a href="https://buymeacoffee.com/alexxbody" target="_blank" rel="noopener">Buy me a coffee</a>
        </footer>
      </div>
    `;
    if (savedRoom) this._restoreAddRoomForm(savedRoom);
    this._applyRoomFlash(root);
    if (this._selectedBoardId) {
      const bsel = root.getElementById("hcc-board-sel");
      if (bsel) bsel.value = this._selectedBoardId;
    }
    this._renderBoardPreview();
    this._populateBoilerCatalog();
  }

  async _populateBoilerCatalog() {
    const makeSel = this.shadowRoot.getElementById("hcc-bi-make");
    if (!makeSel || makeSel.options.length > 1) return; // already populated
    try {
      if (!this._boilerCat) {
        this._boilerCat = await this._hass.callWS({
          type: "home_climate_control/get_boiler_catalog",
        });
      }
      const cat = this._boilerCat;
      const sys = (this._status?.systems || [])[0] || {};
      const bi = sys.boiler_info || {};
      for (const mk of cat.makes) {
        const o = document.createElement("option");
        o.value = mk;
        o.textContent = mk;
        makeSel.appendChild(o);
      }
      makeSel.value = bi.make || "";
      this._fillBoilerModels(cat, bi);
      if (!makeSel.dataset.wired) {
        makeSel.dataset.wired = "1";
        makeSel.addEventListener("change", () =>
          this._fillBoilerModels(this._boilerCat, null)
        );
      }
    } catch (err) {
      /* catalog unavailable */
    }
  }

  _fillBoilerModels(cat, bi) {
    const makeSel = this.shadowRoot.getElementById("hcc-bi-make");
    const modelSel = this.shadowRoot.getElementById("hcc-bi-model");
    const models =
      (cat.models && cat.models[makeSel.value]) ||
      (bi ? bi.models_available : []) ||
      [];
    modelSel.innerHTML = '<option value="">—</option>';
    for (const m of models) {
      const o = document.createElement("option");
      o.value = m;
      o.textContent = m;
      modelSel.appendChild(o);
    }
    if (bi) modelSel.value = bi.model || "";
  }

  async _onSaveBoilerInfo() {
    try {
      await this._hass.callWS({
        type: "home_climate_control/set_boiler_info",
        make: this.shadowRoot.getElementById("hcc-bi-make").value || null,
        model: this.shadowRoot.getElementById("hcc-bi-model").value || null,
      });
      await this._refresh(); // rebuild DOM, then show the message on the fresh node
      const msg = this.shadowRoot.getElementById("hcc-bi-msg");
      if (msg) msg.textContent = "Saved";
      setTimeout(() => {
        const m = this.shadowRoot.getElementById("hcc-bi-msg");
        if (m) m.textContent = "";
      }, 3000);
    } catch (err) {
      const msg = this.shadowRoot.getElementById("hcc-bi-msg");
      if (msg) msg.textContent = "Failed: " + (err?.message || String(err));
    }
  }

  async _onSaveFailsafe() {
    const msg = this.shadowRoot.getElementById("hcc-fs-msg");
    try {
      await this._hass.callWS({
        type: "home_climate_control/set_failsafe",
        enable: this.shadowRoot.getElementById("hcc-fs-en").checked,
        flow: parseFloat(this.shadowRoot.getElementById("hcc-fs-flow").value),
        grace_min: parseInt(
          this.shadowRoot.getElementById("hcc-fs-grace").value,
          10
        ),
      });
      if (msg) msg.textContent = "Saved to device";
    } catch (err) {
      if (msg) msg.textContent = "Failed: " + (err?.message || String(err));
    }
    setTimeout(() => {
      if (msg) msg.textContent = "";
    }, 3000);
  }

  _tabBtn(id, label) {
    return `<button type="button" class="tab ${this._tab === id ? "active" : ""}" data-tab="${id}">${label}</button>`;
  }

  _body(sys, systems) {
    if (!systems.length && this._tab !== "firmware") {
      return `
        <div class="empty card">
          <p><strong>No Home Climate Control system configured yet.</strong></p>
          <p class="sub">Settings → Devices &amp; services → Add integration → Home Climate Control</p>
        </div>`;
    }
    switch (this._tab) {
      case "rooms":
        return `<div id="hcc-zones-wrap">${this._zonesHtml(sys)}</div>`;
      case "devices":
        return `<div id="hcc-fw-head-wrap">${this._fwHeadHtml()}</div>
          <div id="hcc-board-wrap">${this._boardHtml()}</div>
          ${this._otConsoleHtml()}
          <div id="hcc-fw-wrap">${this._fwCardHtml()}</div>`;
      case "settings":
        return `${this._soptMsg ? `<div class="card" style="border-color:#3a7">${this._esc(this._soptMsg)}</div>` : ""}${this._settingsHtml(sys)}`;
      case "diagnostics":
        return `<div id="hcc-diag-wrap">
          <p class="sub" style="margin-top:0">Engineering telemetry — safe to ignore, fun to watch.</p>
          ${this._settingsLiveHtml(sys)}
        </div>`;
      default: // home
        return `<div id="hcc-live">${this._homeHtml(sys)}</div>`;
    }
  }

  _overviewHtml(sys) {
    const outdoor = this._fmt(sys.outdoor_temp);
    const flow = this._fmt(sys.flow_setpoint);
    const demand = sys.total_demand != null ? Math.round(sys.total_demand * 100) : "—";
    const ch =
      sys.boiler?.ch_active || sys.boiler?.flame_on
        ? `<span class="badge heat">Heating</span>`
        : `<span class="badge off">Idle</span>`;
    const flame = sys.boiler?.flame_on
      ? `<span class="badge heat">Flame</span>`
      : `<span class="badge off">No flame</span>`;
    const active = (sys.active_zones || []).join(", ") || "None";

    return `
      <div class="grid">
        <div class="card"><h3>Outdoor</h3><div class="metric">${outdoor}<span class="unit">°C</span></div>
          <div class="sub">${sys.demo ? "Simulated outdoor (demo)" : (sys.boiler?.outdoor_source === "ha" ? "HA fallback sensor" : sys.boiler?.outdoor_source === "boiler_stale" ? "Boiler outdoor (stale)" : "Boiler outdoor sensor")}${sys.boiler?.duty_cycle?.active ? " · duty-cycle" : ""}</div></div>
        <div class="card"><h3>Flow setpoint</h3><div class="metric">${flow}<span class="unit">°C</span></div>
          <div class="sub">Weather-compensated target</div></div>
        <div class="card"><h3>Total demand</h3><div class="metric">${demand}<span class="unit">%</span></div>
          <div class="sub">Active: ${this._esc(active)}</div></div>
        <div class="card"><h3>Boiler</h3><div class="metric" style="font-size:1.1rem">${ch} ${flame}</div>
          <div class="sub">Mod ${this._fmt(sys.boiler?.modulation_level)}% · Return ${this._fmt(sys.boiler?.return_temp)}°C</div></div>
      </div>
      ${this._healthHtml(sys)}
      ${this._zonesHtml(sys, true)}
    `;
  }

  _healthHtml(sys) {
    const rooms = sys.boiler?.health?.rooms || {};
    const flagged = Object.entries(rooms).filter(([, r]) => r.flag);
    if (!flagged.length) return "";
    return `
      <div class="card wide" style="margin-bottom:12px">
        <h3>Room health</h3>
        ${flagged
          .map(
            ([name]) =>
              `<div class="sub">⚠ <strong>${this._esc(name)}</strong> — struggles to reach target at full flow. Check radiator size, bleeding (air/sludge), or the TRV.</div>`
          )
          .join("")}
      </div>`;
  }

  /* ── OpenTherm console (Board tab) ─────────────────────────────────
     Frames come from the board via the integration proxy (server-side
     HTTP fetch — no CORS). Lives outside hcc-board-wrap so the poll's
     telemetry swap never scrolls away what you're reading. */
  _otConsoleHtml() {
    const devs = (this._status?.devices || []).filter((d) => d.online);
    if (!devs.length) return "";
    const sel = this._otlogNodeId ||
      (this._selectedBoardId && devs.some(d=>d.node_id===this._selectedBoardId)
        ? this._selectedBoardId : devs[0].node_id);
    this._otlogNodeId = sel;
    const opts = devs.map(
      (d) => `<option value="${d.node_id}"${d.node_id === sel ? " selected" : ""}>${this._esc(d.name || d.node_id)}</option>`
    ).join("");
    const lines = this._otlogLines;
    const body = lines == null
      ? "loading…"
      : (lines.length ? this._esc(lines.join("\n")) : "(no frames yet)");
    return `
      <div class="card wide" style="margin-top:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div class="zone-title" style="margin:0">OpenTherm console</div>
          <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
            <select id="hcc-otlog-node" style="background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px;padding:3px 8px;font-size:.78rem">${opts}</select>
            <button type="button" class="ghost" data-otlog="refresh" title="Refresh"
              style="padding:2px 10px;font-size:.78rem">⟳ Refresh</button>
            <button type="button" class="ghost" data-otlog="clear" title="Clear log"
              style="padding:2px 10px;font-size:.78rem">✕ Clear</button>
          </div>
        </div>
        <pre id="hcc-otlog-pre" style="max-height:260px;overflow:auto;font-size:.72rem;line-height:1.35;margin:8px 0 0;white-space:pre">${body}</pre>
      </div>`;
  }

  _otAutoTick_() {
    const now = Date.now();
    if (now - (this._otlogLastMs || 0) < 5000) return;
    this._otlogLastMs = now;
    this._fetchOtLog();
  }

  async _fetchOtLog(clear = false) {
    const node = this._otlogNodeId;
    if (!node || !this._hass || this._otlogBusy) return;
    this._otlogBusy = true;
    const pre = this.shadowRoot.getElementById("hcc-otlog-pre");
    try {
      const res = await this._hass.callWS({
        type: "home_climate_control/get_ot_log",
        node_id: node,
        clear,
      });
      if (res?.ok) {
        const stick = pre
          ? pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4
          : true;
        this._otlogLines = res.lines || [];
        if (pre) {
          pre.textContent = this._otlogLines.length
            ? this._otlogLines.join("\n")
            : "(no frames yet)";
          if (stick) pre.scrollTop = pre.scrollHeight;
        }
      } else if (pre) {
        pre.textContent = "error: " + (res?.error || "unknown");
      }
    } finally {
      this._otlogBusy = false;
    }
  }

  /* Highlight + scroll to a room card on the Rooms tab. Survives the
     poll: _fpFlashName stays set until the animation completes and is
     re-applied after every live swap of the zones list. */
  _applyRoomFlash(root) {
    const name = this._fpFlashName;
    if (!name || this._tab !== "rooms") return;
    for (const el of root.querySelectorAll(".zone-title")) {
      if (!el.textContent.includes(name)) continue;
      const card = el.closest(".card") || el;
      if (card.classList.contains("fp-flash")) break; // already animating
      card.classList.add("fp-flash");
      requestAnimationFrame(() => {
        if (card.scrollIntoView)
          card.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      setTimeout(() => {
        card.classList.remove("fp-flash");
        if (this._fpFlashName === name) this._fpFlashName = null;
      }, 3400);
      break;
    }
  }

  /* ── Floor plan ────────────────────────────────────────────────────
     SVG bands per floor (highest floor first, ground at bottom).
     Room fill encodes comfort delta: blue=cold, green=at-target,
     orange=over. Zero backend dependencies — everything comes from
     get_status zones + this._hass states. */
  static FP_TEMP_SPAN = 2.0; // °C around setpoint mapped to full color sweep

  static _fpColor(delta) {
    const span = HomeClimatePanel.FP_TEMP_SPAN;
    const x = Math.max(-span, Math.min(span, delta)); // -2..+2
    // three-stop lerp: 210°(blue) → 130°(green) → 30°(orange)
    let h;
    if (x < 0) h = 210 + (130 - 210) * ((x + span) / span);
    else h = 130 + (30 - 130) * (x / span);
    return `hsl(${h.toFixed(0)}, 55%, 26%)`;
  }

  static _fpEsc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  _floorplanHtml(sys) {
    const zones = sys?.zones || [];
    if (!zones.length)
      return this._placeholder("Floor plan", "No rooms configured yet.");
    const byFloor = new Map();
    for (const z of zones) {
      const f = Number.isFinite(z.floor) ? z.floor : 0;
      if (!byFloor.has(f)) byFloor.set(f, []);
      byFloor.get(f).push(z);
    }
    const floors = [...byFloor.keys()].sort((a, b) => a - b);

    const RH = 108, GAP = 10, PAD = 6;   // room height / gaps
    const bands = [];
    let y = 0;
    for (let i = floors.length - 1; i >= 0; i--) {   // top floor rendered first
      const f = floors[i];
      const rooms = byFloor.get(f);
      const W = Math.max(320, rooms.length * 150);
      const labelY = y + 12;
      const rectY = y + 20;
      let rects = "";
      let x = PAD;
      const w = (W - PAD * 2 - GAP * (rooms.length - 1)) / rooms.length;
      for (const z of rooms) {
        const cur = typeof z.current_temperature === "number" ? z.current_temperature : null;
        const tgt = z.effective_setpoint ?? z.target_temperature;
        const delta = cur != null && typeof tgt === "number" ? cur - tgt : null;
        const fill = delta == null ? "#3a3f44" : HomeClimatePanel._fpColor(delta);
        const heating = String(z.hvac_action || "") === "heating";
        const demandPct = z.demand_level != null ? Math.round(z.demand_level * 100) : 0;
        const manual = z.heat_control === "manual";
        const cx = x + w / 2;
        const tempTxt = cur != null ? `${cur.toFixed(1)}°` : "—";
        const subBits = [];
        if (typeof tgt === "number") subBits.push(`→ ${tgt.toFixed(0)}°`);
        if (manual) subBits.push("✋ manual");
        if (z.window_open) subBits.push("🪟 window");
        const badges = [];
        if (heating) badges.push(`<tspan class="fp-badge" fill="#ff8a65">🔥</tspan>`);
        if (demandPct > 0) badges.push(`<tspan class="fp-badge" fill="#4fc3f7">${demandPct}%</tspan>`);
        rects += `
        <g class="fp-room${manual ? " manual" : ""}" data-fp-zone="${HomeClimatePanel._fpEsc(z.name)}">
          <rect class="r" x="${x.toFixed(1)}" y="${rectY}" width="${w.toFixed(1)}" height="${RH}"
            rx="12" ry="12" fill="${fill}"></rect>
          <text class="fp-name" x="${cx}" y="${rectY + 24}" text-anchor="middle">${HomeClimatePanel._fpEsc(z.name)}</text>
          <text class="fp-temp" x="${cx}" y="${rectY + 52}" text-anchor="middle">${tempTxt}</text>
          <text class="fp-sub" x="${cx}" y="${rectY + 72}" text-anchor="middle">${HomeClimatePanel._fpEsc(subBits.join(" · "))}</text>
          <text class="fp-sub" x="${cx}" y="${rectY + RH - 14}" text-anchor="middle">${badges.join(" ")}</text>
        </g>`;
        x += w + GAP;
      }
      bands.push(`
        <div class="fp-floor-label">${HomeClimatePanel.FLOOR_LABEL(f)}</div>
        <svg class="fp-svg" viewBox="0 0 ${W} ${rectY + RH + PAD}" role="img"
             aria-label="Floor plan, ${HomeClimatePanel.FLOOR_LABEL(f)}">${rects}
        </svg>`);
      y = rectY + RH + PAD + 14;
    }
    return `<div class="card wide" style="padding:14px">
        <p class="sub" style="margin-top:0">Live comfort map — click a room to manage it.
        <span style="opacity:.7">Blue = below target · Green = at target · Orange = above.</span></p>
      ${bands.join("\n")}
      </div>`;
  }

  /* ── Home tab: status-only dashboard ───────────────────────────── */
  _homeHtml(sys) {
    const b = sys?.boiler || {};
    const gas = sys?.gas;
    const bi = sys?.boiler_info || {};
    const make = bi.make || bi.detected_make || "";
    const model = bi.model || "";
    const imgHtml = (bi && bi.image)
      ? `<img src="${bi.image}" alt="${this._esc(make)}"><div class="bp-cap">${this._esc(make)}${model ? `<br>${this._esc(model)}` : ""}</div>`
      : `<div class="bp-cap">no boiler info</div>`;
    const ch = b.ch_active || b.flame_on
      ? `<span class="badge heat">Heating</span>`
      : `<span class="badge off">Idle</span>`;
    const flame = b.flame_on ? `<span class="badge heat">🔥 Flame</span>` : "";
    const mod = this._fmt(b.modulation_level);
    const flowT = this._fmt(b.flow_temp);
    const retT = this._fmt(b.return_temp);
    const gasToday = gas ? `${this._esc(gas.today_kwh)}<span class="unit">kWh today</span>` : "—";

    return `
      ${this._alertsRow(sys)}
      <div class="card wide bp-hero">
        <div class="bp-hero-img">
          ${imgHtml}
        </div>
        <div class="bp-hero-stats">
          <div class="zone-title" style="justify-content:flex-start;gap:10px">
            Boiler ${ch} ${flame}
            <span style="margin-left:auto;font-weight:400" class="fp-sub">mod ${mod}% · flow ${flowT}°C · return ${retT}°C</span>
          </div>
          <div class="grid" style="grid-template-columns:repeat(3,1fr);gap:10px;margin-top:4px">
            <div><div class="metric" style="font-size:1.5rem">${gasToday}</div><div class="sub">gas estimate</div></div>
            <div><div class="metric" style="font-size:1.5rem">${this._fmt(sys.outdoor_temp)}<span class="unit">°C</span></div><div class="sub">outdoor</div></div>
            <div><div class="metric" style="font-size:1.5rem">${Math.round((sys.total_demand || 0) * 100)}<span class="unit">% demand</span></div>
              <div class="sub">active: ${this._esc((sys.active_zones || []).join(", ") || "none")}</div></div>
          </div>
        </div>
      </div>
      ${this._floorplanHtml(sys)}
    `;
  }

  _alertsRow(sys) {
    const alerts = [];
    for (const [, r] of Object.entries(sys?.boiler?.health?.rooms || {})) {
      if (r.flag) alerts.push(`⚠ Room struggles to reach target — check radiators/TRV`);
      break;
    }
    for (const d of this._status?.devices || []) {
      if (!d.online)
        alerts.push(`⚠ Board offline: ${this._esc(d.name || d.node_id)}`);
      if (HomeClimatePanel.OTA_ACTIVE.has(d.ota_state))
        alerts.push(`⏳ Update running on ${this._esc(d.name || d.node_id)} (${this._esc(d.ota_state)})`);
    }
    const fs = sys?.boiler?.failsafe;
    if (fs && !["OFF", "connected"].includes(fs))
      alerts.push(`🚨 Failsafe ${this._esc(fs)}`);
    if (sys?.update_info?.available)
      alerts.push(`⬆ Board firmware update available`);
    if (!alerts.length) return "";
    return `<div class="card wide" style="border-color:#a33;margin-bottom:12px;padding:10px 14px">
      ${alerts.map((a) => `<div class="sub" style="margin:2px 0">${a}</div>`).join("")}
    </div>`;
  }

  static FLOOR_LABEL = (f) =>
    f === 0 ? "Ground floor" : `${f}${f === 1 ? "st" : f === 2 ? "nd" : f === 3 ? "rd" : "th"} floor`;

  static ZONE_PRESET_OPTS = ["comfort", "eco", "away", "boost"];

  _zonesHtml(sys, compact = false) {
    const zones = sys.zones || [];
    if (!zones.length) {
      return `<div class="card empty">No rooms configured. Add rooms (TRV + optional temp sensor) in the integration setup.</div>`;
    }
    const ctx = {
      compact,
      cal: sys.boiler?.calibration || {},
      rates: sys.boiler?.setbacks?.rooms || {},
      dts: sys.boiler?.deadtime?.rooms || {},
      health: sys.boiler?.health?.rooms || {},
      insul: sys.boiler?.insulation?.rooms || {},
    };
    // Group rooms by floor (0 = ground); stable order inside each floor.
    const byFloor = new Map();
    for (const z of zones) {
      const f = Number.isFinite(z.floor) ? z.floor : 0;
      if (!byFloor.has(f)) byFloor.set(f, []);
      byFloor.get(f).push(z);
    }
    const floors = [...byFloor.keys()].sort((a, b) => a - b);
    const body = floors
      .map((f) => `
        ${compact ? "" : `<div class="floor-head">${HomeClimatePanel.FLOOR_LABEL(f)}</div>`}
        <div class="zones">
          ${byFloor.get(f).map((z) => this._zoneCard(z, ctx)).join("")}
        </div>`)
      .join("");
    if (compact) return body;
    return `${body}
      ${this._addRoomHtml()}`;
  }

  _saveAddRoomForm() {
    const r = this.shadowRoot;
    const prefix = this._editingZone ? "er" : "nr";
    return {
      prefix,
      name: r.getElementById(prefix + "-name")?.value || "",
      control: r.getElementById(prefix + "-control")?.value || "smart",
      floor: r.getElementById(prefix + "-floor")?.value || "0",
      trv: r.getElementById(prefix + "-trv")?.value || "",
      sensor: r.getElementById(prefix + "-sensor")?.value || "",
      window: r.getElementById(prefix + "-window")?.value || "",
    };
  }

  _restoreAddRoomForm(s) {
    const r = this.shadowRoot;
    const set = (id, v) => { const e = r.getElementById(id); if (e) e.value = v; };
    set(s.prefix + "-name", s.name);
    set(s.prefix + "-control", s.control);
    set(s.prefix + "-floor", s.floor);
    set(s.prefix + "-trv", s.trv);
    set(s.prefix + "-sensor", s.sensor);
    set(s.prefix + "-window", s.window);
  }

  _addRoomHtml() {
    if (!this._addingRoom) {
      return `<div class="card" style="text-align:center">
        <button type="button" data-zone-action="add" style="width:100%;padding:10px">+ Add room</button>
      </div>`;
    }
    return this._roomFormHtml(null);
  }

  _roomFormHtml(z) {
    const isEdit = z != null;
    const prefix = isEdit ? "er" : "nr";
    const hass = this._hass?.states || {};
    const friendly = (id) => hass[id]?.attributes?.friendly_name || id;
    const climates = Object.keys(hass)
      .filter((id) => id.startsWith("climate."))
      .sort((a, b) => friendly(a).localeCompare(friendly(b)));
    const tempSensors = Object.keys(hass)
      .filter((id) => id.startsWith("sensor.")
        && (hass[id]?.attributes?.device_class === "temperature"
          || hass[id]?.attributes?.state_class === "measurement"))
      .sort((a, b) => friendly(a).localeCompare(friendly(b)));
    const windowSensors = Object.keys(hass)
      .filter((id) => id.startsWith("binary_sensor.")
        && hass[id]?.attributes?.device_class === "opening")
      .sort((a, b) => friendly(a).localeCompare(friendly(b)));
    const luxSensors = Object.keys(hass)
      .filter((id) => id.startsWith("sensor.")
        && hass[id]?.attributes?.device_class === "illuminance")
      .sort((a, b) => friendly(a).localeCompare(friendly(b)));
    const co2Sensors = Object.keys(hass)
      .filter((id) => id.startsWith("sensor.")
        && hass[id]?.attributes?.device_class === "carbon_dioxide")
      .sort((a, b) => friendly(a).localeCompare(friendly(b)));
    const valveSensors = Object.keys(hass)
      .filter((id) => /^(sensor|number)\./.test(id)
        && /valve|position/i.test(id + " " + (hass[id]?.attributes?.friendly_name || "")))
      .sort((a, b) => friendly(a).localeCompare(friendly(b)));
    const curTrv = isEdit ? (z.trv || "") : "";
    const curSensor = isEdit ? (z.temp_sensor || "") : "";
    const curWindows = isEdit ? (z.window_sensors || []).join(", ") : "";
    const curLux = isEdit ? (z.lux_sensor || "") : "";
    const curCo2 = isEdit ? (z.co2_sensor || "") : "";
    const curValve = isEdit ? (z.trv_position_entity || "") : "";
    const curRadKw = isEdit && z.radiator_kw != null ? z.radiator_kw : "";
    const curName = isEdit ? (z.name || "") : "";
    const curControl = isEdit ? (z.heat_control || "smart") : "smart";
    const curFloor = isEdit ? String(z.floor ?? 0) : "0";
    const action = isEdit ? "save-edit" : "create";
    return `
      <div class="card" style="margin-top:12px">
        <h3>${isEdit ? "Edit room" : "New room"}</h3>
        ${isEdit ? "" : `<div class="row"><label>Name</label>
          <input id="${prefix}-name" type="text" placeholder="e.g. Kitchen" value="${this._esc(curName)}" style="flex:1"></div>`}
        <div class="row"><label>Heater control</label>
          <select id="${prefix}-control" style="flex:1">
            <option value="smart" ${curControl === "smart" ? "selected" : ""}>⚡ Smart TRV (controlled)</option>
            <option value="manual" ${curControl === "manual" ? "selected" : ""}>✋ Manual radiator (observed)</option>
          </select></div>
        <div class="row"><label>Floor</label>
          <select id="${prefix}-floor" style="flex:1">
            ${[0, 1, 2, 3].map((f) => `<option value="${f}" ${curFloor === String(f) ? "selected" : ""}>${HomeClimatePanel.FLOOR_LABEL(f)}</option>`).join("")}
          </select></div>
        <div class="row"><label>TRV climate<br><span style="font-weight:400">(required for smart)</span></label>
          <input id="${prefix}-trv" list="${prefix}-climates" value="${this._esc(curTrv)}" placeholder="climate.… (blank for manual)" style="flex:1">
          <datalist id="${prefix}-climates">${climates.map((c) => `<option value="${this._esc(c)}">${this._esc(friendly(c))}</option>`).join("")}</datalist></div>
        <div class="row"><label>Temp sensor<br><span style="font-weight:400">(optional)</span></label>
          <input id="${prefix}-sensor" list="${prefix}-sensors" value="${this._esc(curSensor)}" placeholder="sensor… (else TRV's own)" style="flex:1">
          <datalist id="${prefix}-sensors">${tempSensors.map((c) => `<option value="${this._esc(c)}">${this._esc(friendly(c))}</option>`).join("")}</datalist></div>
        <div class="row"><label>Window/door<br><span style="font-weight:400">(optional, comma-sep)</span></label>
          <input id="${prefix}-window" list="${prefix}-windows" value="${this._esc(curWindows)}" placeholder="binary_sensor.…" style="flex:1">
          <datalist id="${prefix}-windows">${windowSensors.map((c) => `<option value="${this._esc(c)}">${this._esc(friendly(c))}</option>`).join("")}</datalist></div>
        <div class="row"><label>Lux sensor<br><span style="font-weight:400">(Tier 3, optional)</span></label>
          <input id="${prefix}-lux" list="${prefix}-luxs" value="${this._esc(curLux)}" placeholder="sensor.… (solar gain)" style="flex:1">
          <datalist id="${prefix}-luxs">${luxSensors.map((c) => `<option value="${this._esc(c)}">${this._esc(friendly(c))}</option>`).join("")}</datalist></div>
        <div class="row"><label>CO₂ sensor<br><span style="font-weight:400">(Tier 3, optional)</span></label>
          <input id="${prefix}-co2" list="${prefix}-co2s" value="${this._esc(curCo2)}" placeholder="sensor.… ppm (ventilation flag)" style="flex:1">
          <datalist id="${prefix}-co2s">${co2Sensors.map((c) => `<option value="${this._esc(c)}">${this._esc(friendly(c))}</option>`).join("")}</datalist></div>
        <div class="row"><label>TRV valve position<br><span style="font-weight:400">(Tier 4, optional)</span></label>
          <input id="${prefix}-valve" list="${prefix}-valves" value="${this._esc(curValve)}" placeholder="sensor.°/number.… 0-100%" style="flex:1">
          <datalist id="${prefix}-valves">${valveSensors.map((c) => `<option value="${this._esc(c)}">${this._esc(friendly(c))}</option>`).join("")}</datalist></div>
        <div class="row"><label>Radiator nominal kW<br><span style="font-weight:400">(Tier 4 @ ΔT50, optional)</span></label>
          <input id="${prefix}-radkw" type="number" step="0.1" min="0" max="20" value="${this._esc(curRadKw)}" placeholder="e.g. 1.8" style="flex:1"></div>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button type="button" class="a" data-zone-action="${action}" ${isEdit ? `data-zone-name="${this._esc(z.name || "")}"` : ""} style="flex:1">${isEdit ? "Save changes" : "Create room"}</button>
          <button type="button" class="ghost" data-zone-action="${isEdit ? "cancel-edit" : "cancel-add"}" style="flex:1">Cancel</button>
        </div>
      </div>`;
  }

  _zoneCard(z, ctx) {
    const { compact, cal, rates, dts, health, insul } = ctx;
    if (this._editingZone === z.name && !compact) {
      return this._roomFormHtml(z);
    }
    const heat =
      String(z.hvac_action).includes("heat") || z.hvac_action === "heating";
    const rate = rates[z.name]?.warm_rate;
    const dt = dts[z.name]?.minutes;
    const ins = insul[z.name];
    const manual = z.heat_control === "manual";
    const calHere = cal.active && cal.zone === z.name;
    const infoHtml = `
              <div class="z-info">
                <div class="zone-title">${this._esc(z.name || z.entity_id || "Room")}</div>
                <div class="zone-meta">
                  ${this._fmt(z.current_temperature)}°C${manual ? "" : ` → ${this._fmt(z.effective_setpoint ?? z.target_temperature)}°C`}
                  ${!manual ? ` · demand ${Math.round((z.demand_level || 0) * 100)}%` : ""}
                  ${!manual && heat ? ' · <span class="badge heat">heating</span>' : ""}
                  ${!manual && z.preheat ? ' · <span class="badge heat" title="Optimal-start catch-up using dead-time + warm rate">pre-heat</span>' : ""}
                  ${z.window_open ? ' · <span class="badge heat">🪟 open</span>' : ""}
                  ${!manual && health[z.name]?.flag ? ' · <span class="badge heat" title="Demands heat at full flow for a long time without getting warm — check radiator size, bleeding, or TRV">⚠ struggling</span>' : ""}
                  ${!manual && calHere ? ' · <span class="badge heat">calibrating… keep the room closed</span>' : ""}
                </div>
                <details class="z-insights">
                  <summary>insights</summary>
                  <div class="zone-meta">
                    ${!manual && rate ? `warms ${rate} °C/h · ` : ""}
                    ${!manual && dt != null ? `responds ~${dt} min · ` : ""}
                    ${!manual && z.lead_time_s != null && z.lead_time_s > 0 ? `lead ~${Math.round(z.lead_time_s / 60)} min · ` : ""}
                    ${!manual && ins?.label ? `insulation ${this._esc(ins.label)} (k=${ins.k}) · ` : ""}
                    temp source: ${z.temp_sensor || (!manual && z.temp_source === "trv" ? "TRV internal" : "—")}<br>
                    ${!manual && z.trv ? `TRV: ${this._esc(z.trv)}<br>` : ""}
                    ${(z.window_sensors || []).length ? `window sensors: ${this._esc((z.window_sensors || []).join(", "))}<br>` : "no window sensors<br>"}
                    ${z.solar_gain ? `<span style="color:#ffd54f">☀️ solar gain</span> · ` : ""}${z.co2_ppm != null ? `CO₂ ${z.co2_ppm} ppm${z.needs_ventilation ? " ⚠ ventilate" : ""} · ` : ""}${z.valve_pct != null ? `valve ${Math.round(z.valve_pct)}% · ` : ""}${z.radiator_kw_est != null ? `radiator ~${z.radiator_kw_est} kW · ` : ""}${z.balance && z.balance.state !== "learning" && z.balance.state !== "ok" ? `<span style="color:#ef9a9a">balance: ${this._esc(z.balance.state)}</span>` : ""}
                  </div>
                </details>
              </div>`;
    if (compact) {
      return `
          <div class="card zone" style="position:relative">
            <span class="mode-pill ${manual ? "manual" : "smart"}">${manual ? "✋ manual" : "⚡ smart"}</span>
            ${infoHtml}
          </div>`;
    }
    const tempHtml = manual
      ? `<div class="z-left" aria-hidden="true"></div>`
      : `
              <div class="z-left">
                <div class="z-temp-grid">
                  <button type="button" class="z-tg" data-zone-action="dec" data-entity="${this._esc(z.entity_id || "")}" data-temp="${z.target_temperature ?? 20}">−</button>
                  <input type="number" step="0.5" min="5" max="30" value="${z.target_temperature ?? 20}"
                    data-entity="${this._esc(z.entity_id || "")}" class="temp-input z-bigtemp" />
                  <button type="button" class="z-tg" data-zone-action="inc" data-entity="${this._esc(z.entity_id || "")}" data-temp="${z.target_temperature ?? 20}">+</button>
                  <button type="button" class="z-tg" data-zone-action="apply" data-entity="${this._esc(z.entity_id || "")}">Set</button>
                  <button type="button" ${cal.active ? "disabled" : ""} data-zone-action="calibrate"
                    data-entity="${this._esc(z.entity_id || "")}" data-zone-name="${this._esc(z.name || "")}"
                    title="Measure how fast this room heats up (~15–60 min)">Calibrate</button>
                </div>
              </div>`;
    const railHtml = `
              <div class="z-rail">
                <div class="z-ddcol">
                  <div class="z-ddrow">
                    ${manual ? "<div></div>" : `
                    <div>
                      <span class="z-lbl">Mode</span>
                      <select data-zone-mode data-entity="${this._esc(z.entity_id || "")}">
                        <option value="heat" ${String(z.hvac_mode) === "heat" ? "selected" : ""}>Heat</option>
                        <option value="off" ${String(z.hvac_mode) === "off" ? "selected" : ""}>Off</option>
                      </select>
                    </div>`}
                    <button type="button" class="ghost" data-zone-action="edit"
                      data-zone-name="${this._esc(z.name || "")}"
                      title="Edit this room's settings">Edit</button>
                  </div>
                  <div class="z-ddrow">
                    ${manual ? "<div></div>" : `
                    <div>
                      <span class="z-lbl">Profile</span>
                      <select data-zone-preset data-entity="${this._esc(z.entity_id || "")}">
                        ${["none", "away", "eco", "comfort", "boost"]
                          .map(
                            (p) =>
                              `<option value="${p}" ${z.preset_mode === p ? "selected" : ""}>${p}</option>`
                          )
                          .join("")}
                      </select>
                    </div>`}
                    <button type="button" class="ghost" data-zone-action="remove"
                      data-zone-name="${this._esc(z.name || "")}"
                      title="Remove this room">Delete</button>
                  </div>
                </div>
              </div>`;
    return `
          <div class="card zone" style="position:relative">
            <span class="mode-pill ${manual ? "manual" : "smart"}">${manual ? "✋ manual" : "⚡ smart"}</span>
            <div class="z-main">
              ${infoHtml}
              ${tempHtml}
              ${railHtml}
            </div>
          </div>`;
  }

  static OTA_ACTIVE = new Set(["starting", "downloading", "rebooting"]);

  /** Progress bar / failure box markup for one device's OTA attempt. */
  static _otaHtml(d) {
    const esc = (x) =>
      String(x == null ? "" : x)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    const st = d.ota_state || "";
    if (!st || st === "done") {
      return st === "done"
        ? '<div class="ota-done">Firmware updated successfully.</div>'
        : "";
    }
    if (st === "failed") {
      const err = d.ota_error || "update failed";
      return `<div class="ota-fail"><span>⚠</span><div>
        <strong>Update failed.</strong> ${esc(err)}
      </div></div>`;
    }
    const pct =
      typeof d.ota_progress === "number" ? Math.max(0, Math.min(100, d.ota_progress)) : null;
    const label =
      st === "rebooting"
        ? "Flashing finished — board is rebooting…"
        : pct == null
          ? "Starting update…"
          : `Downloading firmware — ${pct}%`;
    const indeterminate = pct == null && st !== "rebooting";
    return `<div class="ota-wrap">
      <div class="ota-label">${label}</div>
      <div class="ota-bar ${indeterminate ? "ind" : ""}"><i style="width:${pct == null ? 30 : pct}%"></i></div>
    </div>`;
  }

  static _verTuple(v) {
    return String(v || "")
      .replace(/^[vV]+/, "")
      .split(".")
      .map((n) => {
        const m = String(n).match(/^\d+/);
        return m ? parseInt(m[0], 10) : 0;
      });
  }

  /** True when semver a > b (device should be offered an update). */
  static _verNewer(a, b) {
    const A = HomeClimatePanel._verTuple(a);
    const B = HomeClimatePanel._verTuple(b);
    const len = Math.max(A.length, B.length);
    for (let i = 0; i < len; i++) {
      const x = A[i] || 0;
      const y = B[i] || 0;
      if (x !== y) return x > y;
    }
    return false;
  }

  _boardSettingsHtml() {
    const devs = (this._status?.devices || []).filter((d) => d.online);
    if (!devs.length) return "";
    const selId =
      this._bsSel && devs.some((d) => d.node_id === this._bsSel)
        ? this._bsSel
        : devs[0].node_id;
    const dev = devs.find((d) => d.node_id === selId);
    const cfg = dev.cfg || {};
    const draft = this._bsDraft && this._bsDraft.node === selId ? this._bsDraft.v : null;
    const val = (k, dflt = "") => {
      if (draft && draft[k] != null) return draft[k];
      return cfg[k] != null ? cfg[k] : dflt;
    };
    const inp = (id, label, key, type = "text", ph = "") => `
      <div class="row"><label>${label}</label>
      <input id="${id}" data-bs-field="${key}" type="${type}" value="${this._esc(val(key))}" placeholder="${ph}"></div>`;
    return `
      <div class="card wide">
        <h3>Board settings</h3>
        <div class="row"><label>Device</label>
          <select id="hcc-bs-device">${devs.map((d) =>
            `<option value="${this._esc(d.node_id)}" ${d.node_id === selId ? "selected" : ""}>${this._esc(d.name || d.node_id)}</option>`
          ).join("")}</select></div>
        ${inp("hcc-bs-name", "Name", "device_name")}
        <div class="row"><label>MQTT host</label><span style="flex:1;display:flex;gap:8px">
          <input id="hcc-bs-host" data-bs-field="mqtt_host" type="text" value="${this._esc(val("mqtt_host"))}" style="flex:2">
          <input id="hcc-bs-port" data-bs-field="mqtt_port" type="number" value="${this._esc(val("mqtt_port", "1883"))}" style="flex:1;max-width:90px"></span></div>
        ${inp("hcc-bs-user", "MQTT user", "mqtt_user")}
        ${inp("hcc-bs-pass", "MQTT password", "mqtt_pass", "password", "(unchanged)")}
        ${inp("hcc-bs-ota", "OTA password", "ota_password", "password", cfg.ota_password_set ? "(set — type to replace)" : "(none)")}
        <div class="row"><label>MQTT prefix</label><input id="hcc-bs-prefix" data-bs-field="mqtt_prefix" type="text" value="${this._esc(val("mqtt_prefix", "hcs"))}"></div>
        <p class="sub">Secrets are write-only. Saving reboots the board.
          ${cfg.ota_password_set ? " · OTA password: set" : ""}${cfg.mqtt_user_set ? " · MQTT user: set" : ""}
          ${dev.cfg_ts ? ` · synced ${this._ago(dev.cfg_ts)}` : " · pre-1.2.0 firmware: save works, live sync of board-side edits needs v1.2.0+"}</p>
        <button type="button" class="a" data-action="save-board">Save to board</button>
      </div>`;
  }

  _settingsHtml(sys) {
    const bi = sys?.boiler_info || {};
    const o = sys?.options || {};
    const detected = bi.detected_make
      ? `<p class="sub">Detected from boiler MemberID ${bi.member_id ?? "?"}: <strong>${this._esc(bi.detected_make)}</strong></p>`
      : `<p class="sub">No MemberID received yet — select manually.</p>`;
    const num = (v) => (v == null ? "" : this._esc(v));
    const optList = (domains, selected, placeholder) => {
      const hass = this._hass?.states || {};
      const opts = Object.keys(hass)
        .filter((id) => domains.some((d) => id.startsWith(d + ".")))
        .sort()
        .map((id) =>
          `<option value="${this._esc(id)}" ${id === selected ? "selected" : ""}>${this._esc(hass[id]?.attributes?.friendly_name || id)}</option>`
        ).join("");
      return `<option value="" ${!selected ? "selected" : ""}>${placeholder}</option>${opts}`;
    };
    const selCls = 'style="width:100%;padding:8px;background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px"';
    const numCls = selCls;
    // Presence chips: draft survives re-renders until Save commits it.
    const occSel = Array.isArray(this._occDraft)
      ? this._occDraft
      : (o.occupancy_trackers || []);
    const hassStates = this._hass?.states || {};
    const fname = (id) => hassStates[id]?.attributes?.friendly_name || id;
    const presenceIds = Object.keys(hassStates)
      .filter((id) => /^(device_tracker|person|binary_sensor)\./.test(id))
      .sort();
    const avail = presenceIds.filter((id) => !occSel.includes(id));
    const chips = occSel.length
      ? occSel.map((id) =>
          `<span class="chip"><span>${this._esc(fname(id))}</span><button type="button" data-occ-remove="${this._esc(id)}" title="Remove">✕</button></span>`
        ).join("")
      : `<span class="sub" style="margin:0">No presence entities selected</span>`;
    const ck = (key, label, checked) => `
      <label class="hcc-switch">
        <span>
          <input type="checkbox" class="sopt-live" data-sopt="${key}" ${checked ? "checked" : ""}>
          <span class="hcc-switch-track" aria-hidden="true"></span>
        </span>
        <span>${label}</span>
      </label>`;
    const saveBtn = (group) => `
      <button class="ghost" type="button" data-sopt-save="${group}"
        style="margin-top:8px;padding:6px 14px">Save</button>
      <span class="sopt-msg" data-sopt-msg="${group}" style="margin-left:8px;font-size:.85rem"></span>`;
    return `
      <div class="settings-grid">
      <div class="card">
        <h3>Curve &amp; flow limits</h3>
        <label>Heating curve coefficient</label>
        <input type="number" id="so-curve" step="0.1" min="0.2" max="3" value="${num(o.curve_coeff)}" ${numCls}>
        <label style="margin-top:6px">Min flow °C</label>
        <input type="number" id="so-minflow" step="1" min="10" max="90" value="${num(o.min_flow_temp)}" ${numCls}>
        <label style="margin-top:6px">Max flow °C</label>
        <input type="number" id="so-maxflow" step="1" min="20" max="95" value="${num(o.max_flow_temp)}" ${numCls}>
        ${ck("autotune_curve", "Auto-tune curve", o.autotune_curve)}
        ${ck("learn_setbacks", "Learn smart setbacks", o.learn_setbacks)}
        <div class="settings-save">${saveBtn("curve")}</div>
      </div>
      <div class="card">
        <h3>Outdoor &amp; wind</h3>
        <label>Outdoor temperature fallback</label>
        <select id="so-outdoor" ${selCls}>${optList(["sensor", "weather"], o.outdoor_sensor, "— none (boiler only) —")}</select>
        ${ck("wind_compensation", "Wind compensation", o.wind_compensation)}
        <label>Weather entity (wind)</label>
        <select id="so-wind-entity" ${selCls}>${optList(["weather"], o.wind_entity, "— none —")}</select>
        <label style="margin-top:6px">Wind trim cap (°C)</label>
        <input type="number" id="so-wind-cap" step="0.5" min="1" max="6" value="${num(o.wind_max_delta)}" ${numCls}>
        <div class="settings-save">${saveBtn("outdoor")}</div>
      </div>
      <div class="card">
        <h3>Low-load behaviour</h3>
        <label>Boiler minimum modulation (%)</label>
        <input type="number" id="so-minmod" step="1" min="5" max="80" value="${num(o.boiler_min_modulation)}" ${numCls}>
        ${ck("duty_cycle_enabled", "Low-load duty cycling", o.duty_cycle_enabled)}
        <div class="settings-save">${saveBtn("load")}</div>
      </div>
      <div class="card">
        <h3>Schedule</h3>
        <label>Schedule entity</label>
        <select id="so-sched" ${selCls}>${optList(["schedule", "input_select", "sensor", "input_text"], o.schedule_entity, "— none —")}</select>
        <label style="margin-top:6px">Preset when ON</label>
        <select id="so-sched-on" ${selCls}>${HomeClimatePanel.ZONE_PRESET_OPTS.map((p) => `<option value="${p}" ${p === o.schedule_on_preset ? "selected" : ""}>${p}</option>`).join("")}</select>
        <label style="margin-top:6px">Preset when OFF</label>
        <select id="so-sched-off" ${selCls}>${HomeClimatePanel.ZONE_PRESET_OPTS.map((p) => `<option value="${p}" ${p === o.schedule_off_preset ? "selected" : ""}>${p}</option>`).join("")}</select>
        <div class="settings-save">${saveBtn("schedule")}</div>
      </div>
      <div class="card">
        <h3>Occupancy (phones)</h3>
        ${ck("occupancy_enabled", "Occupancy auto-setback", o.occupancy_enabled)}
        <label>Presence entities</label>
        <div class="chips">${chips}</div>
        <div class="occ-add-row">
          <select id="so-occ-add" ${selCls}><option value="">— choose entity —</option>${avail
            .map((id) => `<option value="${this._esc(id)}">${this._esc(fname(id))}</option>`)
            .join("")}</select>
          <button class="ghost" type="button" data-occ-add>Add</button>
        </div>
        <label style="margin-top:8px">Away preset</label>
        <select id="so-occ-away" ${selCls}>${HomeClimatePanel.ZONE_PRESET_OPTS.map((p) => `<option value="${p}" ${p === o.occupancy_away_preset ? "selected" : ""}>${p}</option>`).join("")}</select>
        <label style="margin-top:6px">Home preset</label>
        <select id="so-occ-home" ${selCls}>${HomeClimatePanel.ZONE_PRESET_OPTS.map((p) => `<option value="${p}" ${p === o.occupancy_home_preset ? "selected" : ""}>${p}</option>`).join("")}</select>
        <div class="settings-save">${saveBtn("occupancy")}</div>
      </div>
      <div class="card">
        <h3>Gas metering</h3>
        <label>Nameplate heat input (kW)</label>
        <input type="number" id="so-gas-rated" step="0.1" min="0" max="200" value="${num(o.rated_heat_input_kw)}" ${numCls}>
        <label style="margin-top:6px">Minimum heat input (kW)</label>
        <input type="number" id="so-gas-min" step="0.1" min="0" max="200" value="${num(o.min_heat_input_kw)}" ${numCls}>
        <label style="margin-top:6px">No-modulation duty factor</label>
        <input type="number" id="so-gas-nomod" step="0.05" min="0.1" max="1" value="${num(o.nomod_duty_factor)}" ${numCls}>
        <label style="margin-top:6px">Calibration factor</label>
        <input type="number" id="so-gas-calib" step="0.05" min="0.2" max="5" value="${num(o.gas_calibration)}" ${numCls}>
        <label style="margin-top:6px">Price per kWh</label>
        <input type="number" id="so-gas-price" step="0.01" min="0" max="100" value="${num(o.gas_price_per_kwh)}" ${numCls}>
        <div class="settings-save">${saveBtn("gas")}</div>
      </div>
      <div class="card">
        <h3>Presets (°C vs target)</h3>
        <label>Comfort</label>
        <input type="number" id="so-pre-comfort" step="0.5" min="-10" max="10" value="${num(o.preset_offsets?.comfort)}" ${numCls}>
        <label style="margin-top:6px">Eco</label>
        <input type="number" id="so-pre-eco" step="0.5" min="-10" max="10" value="${num(o.preset_offsets?.eco)}" ${numCls}>
        <label style="margin-top:6px">Away</label>
        <input type="number" id="so-pre-away" step="0.5" min="-10" max="10" value="${num(o.preset_offsets?.away)}" ${numCls}>
        <label style="margin-top:6px">Boost</label>
        <input type="number" id="so-pre-boost" step="0.5" min="-10" max="10" value="${num(o.preset_offsets?.boost)}" ${numCls}>
        <p class="sub">Offsets apply to every room's target; smart setbacks may deepen away/eco further.</p>
        <div class="settings-save">${saveBtn("presets")}</div>
      </div>
      <div class="card">
        <h3>Your boiler</h3>
        ${detected}
        <label>Manufacturer</label>
        <select id="hcc-bi-make" data-role="bi-make" ${selCls}>
          <option value="">— auto-detected —</option>
        </select>
        <label style="margin-top:8px">Model</label>
        <select id="hcc-bi-model" ${selCls}>
          <option value="">—</option>
        </select>
        <button class="ghost" type="button" data-action="save-boiler-info"
          style="margin-top:10px;padding:6px 14px">Save selection</button>
        <span id="hcc-bi-msg" style="margin-left:8px;font-size:.85rem"></span>
      </div>
      <div class="card">
        <h3>Connection-loss failsafe</h3>
        <p class="sub">If WiFi/MQTT stays down longer than the grace period,
        the HCS device forces CH on at this flow setpoint (values are saved on
        the device itself).</p>
        <label style="display:flex;align-items:center;gap:8px;margin:8px 0">
          <input type="checkbox" id="hcc-fs-en"> Enable failsafe heating
        </label>
        <label>Flow setpoint °C</label>
        <input type="number" id="hcc-fs-flow" min="20" max="90" step="1" value="40">
        <label>Grace period (minutes)</label>
        <input type="number" id="hcc-fs-grace" min="1" max="120" step="1" value="10">
        <button class="ghost" type="button" data-action="save-failsafe"
          style="margin-top:8px;padding:6px 14px">Save to device</button>
        <span id="hcc-fs-msg" style="margin-left:8px;font-size:.85rem"></span>
      </div>
      </div>`;
  }

  /* Diagnostics tab body (read-only engineering telemetry).
     Swapped in place by _applyStatus. */
  _settingsLiveHtml(sys) {
    return `
      <div class="grid">
        <div class="card"><h3>Curve coefficient</h3><div class="metric">${this._fmt(sys.curve_coeff)}</div>
        ${sys.autotune ? `<p class="sub">auto-tune: ${this._esc(sys.autotune.last_action || "")}${sys.autotune.mean_error != null ? ` · err ${this._esc(sys.autotune.mean_error)}°C` : ""} · ${sys.autotune.adjustments} adjustment${sys.autotune.adjustments === 1 ? "" : "s"}</p>` : ""}</div>
        <div class="card"><h3>Min flow</h3><div class="metric">${this._fmt(sys.min_flow)}<span class="unit">°C</span></div></div>
        <div class="card"><h3>Max flow</h3><div class="metric">${this._fmt(sys.max_flow)}<span class="unit">°C</span></div></div>
        ${sys.cycle_guard ? `<div class="card"><h3>Burner cycles</h3><div class="metric">${sys.cycle_guard.starts_1h}<span class="unit">/h</span></div><p class="sub">${this._esc(sys.cycle_guard.last_reason || sys.cycle_guard.state)} · patience ×${this._esc(sys.cycle_guard.multiplier)}</p></div>` : ""}
        ${sys.gas ? `<div class="card"><h3>Gas (est.)</h3>
          <div class="metric">${this._esc(sys.gas.today_kwh)}<span class="unit">kWh today</span></div>
          <p class="sub">${this._esc(sys.gas.mode)} · ${this._esc(sys.gas.rated_power_kw)} kW${sys.gas.min_power_kw ? `–${this._esc(sys.gas.min_power_kw)} kW` : ""} nameplate</p>
          <p class="sub">${sys.gas.last_rate_kw != null ? `now: ${this._esc(sys.gas.last_rate_kw)} kW` : ""}${sys.gas.last_dt_k != null ? ` · ΔT ${this._esc(sys.gas.last_dt_k)} K` : ""}${sys.gas.last_hydronic_kw != null ? ` · hydronic ${this._esc(sys.gas.last_hydronic_kw)} kW` : ""}${sys.gas.total_kwh != null ? ` · total ${this._esc(sys.gas.total_kwh)} kWh` : ""}${sys.gas.today_cost != null ? ` · ~${this._esc(sys.gas.today_cost)} today` : ""}</p>
        </div>` : ""}
        ${sys.schedule?.enabled ? `<div class="card"><h3>Schedule</h3>
          <div class="metric" style="font-size:1.2rem">${this._esc(sys.schedule.last_preset || "—")}</div>
          <p class="sub">${this._esc(sys.schedule.entity_id || "")}${sys.schedule.last_state != null ? ` · state ${this._esc(sys.schedule.last_state)}` : ""}</p>
          <p class="sub">on→${this._esc(sys.schedule.on_preset)} · off→${this._esc(sys.schedule.off_preset)}</p>
        </div>` : ""}
        ${sys.occupancy?.enabled ? `<div class="card"><h3>Occupancy</h3>
          <div class="metric" style="font-size:1.2rem">${this._esc(sys.occupancy.last_presence || "—")}${sys.occupancy.last_preset ? ` → ${this._esc(sys.occupancy.last_preset)}` : ""}</div>
          <p class="sub">${(sys.occupancy.entity_ids || []).length} tracker${(sys.occupancy.entity_ids || []).length === 1 ? "" : "s"} · away→${this._esc(sys.occupancy.away_preset)} · home→${this._esc(sys.occupancy.home_preset)}</p>
        </div>` : ""}
        ${sys.wind_trim?.entity ? `<div class="card"><h3>Wind trim</h3>
          <div class="metric" style="font-size:1.2rem">${sys.wind_trim.trim_c ? `−${this._esc(sys.wind_trim.trim_c)}<span class="unit">°C</span>` : "0<span class=\"unit\">°C</span>"}</div>
          <p class="sub">${this._esc(sys.wind_trim.entity)}${sys.wind_trim.wind_kmh != null ? ` · wind ${this._esc(sys.wind_trim.wind_kmh)} km/h` : " · no wind data"} · cap ${this._esc(sys.wind_trim.max_delta_c)}°C${sys.wind_trim.enabled ? "" : " · disabled"}</p>
        </div>` : ""}
        ${(sys.zones || []).some((z) => z.solar_gain || z.co2_ppm != null || z.valve_pct != null || z.radiator_kw_est != null) ? `<div class="card" style="grid-column:1/-1"><h3>Tier 3/4 — rooms</h3>
          ${sys.zones.filter((z) => z.solar_gain || z.co2_ppm != null || z.valve_pct != null || z.radiator_kw_est != null || (z.balance && z.balance.state !== "learning")).map((z) => `<p class="sub"><strong>${this._esc(z.name)}</strong>: ${z.solar_gain ? "☀️ solar · " : ""}${z.co2_ppm != null ? `CO₂ ${z.co2_ppm} ppm${z.needs_ventilation ? " ⚠ ventilate" : ""} · ` : ""}${z.valve_pct != null ? `valve ${Math.round(z.valve_pct)}% · ` : ""}${z.radiator_kw_est != null ? `radiator ~${z.radiator_kw_est} kW · ` : ""}${z.balance ? this._esc(z.balance.state) : ""}</p>`).join("")}
        </div>` : ""}
        ${sys.setbacks ? `<div class="card"><h3>Smart setbacks</h3>
          ${Object.entries(sys.setbacks.rooms || {}).length === 0 ? '<p class="sub">No rooms seen yet — learning starts after the first away/eco period.</p>' : Object.entries(sys.setbacks.rooms).map(([n, r]) => `<p class="sub"><strong>${this._esc(n)}</strong>: ${r.mature ? `${this._esc(r.learned_offset)}°C` : "learning…"} <span style="opacity:.7">(${r.cycles} cycle${r.cycles === 1 ? "" : "s"}${r.warm_rate ? ` · ${this._esc(r.warm_rate)}°C/h recovery` : ""})</span></p>`).join("")}
        </div>` : ""}
        ${sys.boiler?.datalogger ? `<div class="card"><h3>Training data</h3>
          <div class="metric">${sys.boiler.datalogger.rows_total ?? 0}<span class="unit">rows logged</span></div>
          <p class="sub">${sys.boiler.datalogger.last_row_ts ? `last: ${this._esc(sys.boiler.datalogger.last_row_ts)} · ` : ""}buffered: ${this._esc(sys.boiler.datalogger.rows_buffered ?? 0)}</p>
          <p class="sub" style="opacity:.75">Saved to <code>${this._esc(sys.boiler.datalogger.directory || "")}</code> as monthly JSONL — survives integration updates.</p>
        </div>` : ""}
        ${(sys.probes && sys.probes.length) ? `<div class="card"><h3>1-Wire probes</h3>
          ${sys.probes.map(p => `<p class="sub"><strong>${this._esc((p.addr || "").slice(-8) || "?")}</strong>: ${p.temp_c != null ? this._esc(p.temp_c) + "°C" : "—"} · ${this._esc(p.health || "?")} · ${this._esc(p.role || "none")}${p.name ? " · " + this._esc(p.name) : ""}</p>`).join("")}
        </div>` : ""}
        <div class="card"><h3>Entry</h3><div class="sub">${this._esc(sys.entry_id || "")}</div></div>
      </div>`;
  }

  static _modelLabel(c) {
    if (!c) return "";
    if (c.model) return c.model;
    // Fallback: strip legacy "HCS x.y.z — " / "HCS x.y.z GW — " prefixes.
    return String(c.title || "").replace(/^HCS\s+[\d.]+\s+(GW\s+)?—\s+/, "");
  }

  static _ctlVal(ctl, key, dflt = "—") {
    const v = ctl?.[key];
    if (v == null) return dflt;
    return v;
  }

  /** Replica of the ESP board Control page, driven over MQTT. */
  _boardHtml() {
    const devs = (this._status?.devices || []).filter((d) => d.online);
    if (!devs.length)
      return this._placeholder(
        "Board",
        "No online HCS boards. They re-register within seconds of coming back."
      );
    return devs.map((d) => {
      const c = d.ctl || {};
      const node = this._esc(d.node_id);
      const on = (b) => (b === true ? "ON" : b === false ? "OFF" : "—");
      const num = (k, dflt = "") => {
        const v = c[k];
        return v == null ? dflt : v;
      };
      const draftKey = `bd:${d.node_id}`;
      const draft = this._drafts[draftKey] || {};
      const dv = (k, dflt = "") => (draft[k] != null ? draft[k] : num(k, dflt));
      const fs = c.fs_state || "OFF";
      const fsColor =
        fs === "FAILSAFE" ? "#ef5350" : fs === "HOLD" ? "#ffb74d" : "#7cb342";
      return `
      <div class="card wide" style="margin-bottom:14px">
        <div class="zone-title">${this._esc(d.name || d.node_id)}
          <span class="badge on">v${this._esc(d.version || "?")}</span>
          ${fs !== "OFF" ? `<span class="badge heat">failsafe: ${fs}</span>` : ""}
        </div>
        <div class="zone-meta">live mirror of the board Control page · changes apply instantly over MQTT</div>

        <div class="row"><label>Central heating</label>
          <button type="button" class="${c.ch_enable === false ? "" : "a"}" data-ctl-node="${node}" data-ctl-key="ch_enable" data-ctl-value="true">CH on</button>
          <button type="button" class="ghost" data-ctl-node="${node}" data-ctl-key="ch_enable" data-ctl-value="false">CH off</button>
          <span style="margin-left:auto">now: <b>${on(c.ch_enable)}</b></span></div>

        <div class="row"><label>DHW enable</label>
          <button type="button" class="${c.dhw_enable === false ? "" : "a"}" data-ctl-node="${node}" data-ctl-key="dhw_enable" data-ctl-value="true">DHW on</button>
          <button type="button" class="ghost" data-ctl-node="${node}" data-ctl-key="dhw_enable" data-ctl-value="false">DHW off</button>
          <span style="margin-left:auto">now: <b>${on(c.dhw_enable)}</b></span></div>

        <div class="row"><label>DHW setpoint °C</label>
          <input type="number" min="30" max="60" step="1" style="max-width:100px"
            value="${dv("dhw_setpoint", "")}" data-draft-node="${node}" data-draft-key="dhw_setpoint">
          <button type="button" class="a" data-ctl-node="${node}" data-ctl-key="dhw_setpoint" data-ctl-from-input="1">Apply</button>
          <button type="button" class="ghost" title="release to boiler/thermostat"
            data-ctl-node="${node}" data-ctl-key="dhw_setpoint" data-ctl-value="auto">Auto</button>
          <span style="margin-left:auto">now: <b>${c.dhw_setpoint == null ? "auto" : c.dhw_setpoint + " °C"}</b></span></div>

        <div class="row"><label>Flow setpoint °C</label>
          <input type="number" min="20" max="90" step="0.5" style="max-width:100px"
            value="${dv("flow_setpoint", "")}" data-draft-node="${node}" data-draft-key="flow_setpoint">
          <button type="button" class="a" data-ctl-node="${node}" data-ctl-key="flow_setpoint" data-ctl-from-input="1">Apply</button>
          <input type="range" min="20" max="90" step="0.5" style="flex:1"
            value="${dv("flow_setpoint", 45)}" data-draft-node="${node}" data-draft-key="flow_setpoint"
            data-range-for="flow_setpoint" data-ctl-node="${node}">
          <span style="margin-left:auto">now: <b>${c.flow_setpoint == null ? "—" : c.flow_setpoint + " °C"}</b></span></div>

        <div class="row"><label>Max modulation</label>
          <input type="range" min="0" max="100" step="5" style="flex:1"
            value="${num("max_modulation", 100)}" data-ctl-node="${node}" data-ctl-key="max_modulation" data-range-live="1">
          <span style="margin-left:auto">now: <b>${c.max_modulation != null ? c.max_modulation + "%" : "—"}</b></span></div>

        <h3 style="margin-top:16px">Weather compensation
          <span style="font-weight:400;font-size:.85rem"> target: <b>${c.wc_target != null ? c.wc_target + " °C" : "—"}</b></span></h3>
        <div class="row"><label>&nbsp;</label>
          <button type="button" class="${c.wc_enable === false ? "" : "a"}" data-ctl-node="${node}" data-ctl-key="weather_comp" data-ctl-value="true">WC on</button>
          <button type="button" class="ghost" data-ctl-node="${node}" data-ctl-key="weather_comp" data-ctl-value="false">WC off</button>
          <span style="margin-left:auto">now: <b>${on(c.wc_enable)}</b></span></div>
        <div class="row"><label>Curve °C</label>
          <input type="number" step="1" style="max-width:80px" title="Ref (zero demand)" placeholder="Ref"
            value="${dv("wc_ref", "")}" data-draft-node="${node}" data-draft-key="wc_ref">
          <input type="number" step="1" style="max-width:80px" title="Design temp" placeholder="Design"
            value="${dv("wc_design", "")}" data-draft-node="${node}" data-draft-key="wc_design">
          <input type="number" step="1" style="max-width:80px" title="Flow max" placeholder="Max"
            value="${dv("wc_fmax", "")}" data-draft-node="${node}" data-draft-key="wc_fmax">
          <input type="number" step="1" style="max-width:80px" title="Flow min" placeholder="Min"
            value="${dv("wc_fmin", "")}" data-draft-node="${node}" data-draft-key="wc_fmin">
          <button type="button" class="a" data-wc-apply="${node}">Apply curve</button></div>
      </div>`;
    }).join("");
  }

  /* Devices tab — slim header strip + merged Firmware card. */
  _fwHeadHtml() {
    const ui = this._status?.systems?.[0]?.update_info || null;
    let banner = "";
    if (ui?.error) {
      banner = `<div class="card placeholder"><p class="sub">Update check failed: ${this._esc(ui.error)}</p></div>`;
    } else if (ui?.available) {
      const outdatedIds = new Set(
        (ui?.outdated_devices || []).map((d) => d.node_id)
      );
      banner = `
      <div class="card" style="border-color:var(--warning-color,#f6ad55)">
        <h3>New firmware ${this._esc(ui.latest_tag)} available</h3>
        <p class="sub">${this._esc(outdatedIds.size)} device(s) outdated —
          update from the list below, or</p>
        <button type="button" data-fw-action="flash-all"
          style="padding:6px 16px;margin:6px 0">Update all outdated</button>
        <details style="margin-top:6px">
          <summary style="cursor:pointer;color:var(--secondary-text-color,#aaa);font-size:.9rem">Changelog (${this._esc(ui.title || ui.latest_tag)})</summary>
          <pre style="white-space:pre-wrap;font-size:.85rem;color:var(--primary-text-color,#ddd);max-height:260px;overflow:auto;background:var(--secondary-background-color,#141414);padding:10px;border-radius:8px">${this._esc(ui.changelog || "—")}</pre>
          ${ui.url ? `<a href="${this._esc(ui.url)}" target="_blank" rel="noopener" style="font-size:.85rem">Release page ↗</a>` : ""}
        </details>
      </div>`;
    }
    return banner;
  }

  _fwCardHtml() {
    // Only currently-online boards — a powered-off module re-registers
    // within seconds of coming back, so no need to keep dead cards around.
    const devices = (this._status?.devices || []).filter((d) => d.online);
    let catalog = [...(this._status?.firmware_catalog || [])];

    const deviceCards = devices
      .map((d) => {
        const match = catalog.find((c) => c.board === d.board) || null;
        const update =
          match && HomeClimatePanel._verNewer(match.version, d.version)
            ? match
            : null;
        const label = (c) =>
          HomeClimatePanel._modelLabel(c) +
          (String(c.board || "").endsWith("_gw") ? " · gateway" : "");
        const options = [
          ...catalog.map(
            (c) =>
              `<option value="${this._esc(c.id)}" ${match === c ? "selected" : ""}>${this._esc(label(c))}</option>`
          ),
          `<option value="__custom__">Custom URL…</option>`,
        ].join("");
        return `
      <div class="zone">
        <div>
          <div class="zone-title">${this._esc(d.name || d.node_id)}
            ${d.online ? '<span class="badge on">online</span>' : '<span class="badge off">offline</span>'}
            ${update
              ? `<span class="badge heat">v${this._esc(update.version)} available</span>`
              : match
                ? '<span class="badge on">up to date</span>'
                : ""}
          </div>
          <div class="zone-meta">
            ${this._esc(d.node_id)} · ${this._esc(d.board || "?")} · v${this._esc(d.version || "?")} · ${this._esc(d.ip || "no IP")}
            · seen ${this._ago(d.last_seen)}
            ${d.last_error ? ` · <span style="color:#ef9a9a">${this._esc(d.last_error)}</span>` : ""}
          </div>
          ${HomeClimatePanel._otaHtml(d)}
        </div>
        <div class="controls">
          <select data-catalog-for="${this._esc(d.node_id)}"
            style="margin-top:14px;max-width:220px">${options}</select>
          <button type="button" data-fw-action="flash" data-node="${this._esc(d.node_id)}"
            ${!d.online || this._busy[d.node_id] ? "disabled" : ""}>Flash</button>
          <button type="button" class="ghost" data-fw-action="reboot" data-node="${this._esc(d.node_id)}"
            ${!d.online || this._busy[d.node_id] ? "disabled" : ""}>Reboot</button>
          <button type="button" class="ghost" data-fw-action="open" data-node="${this._esc(d.node_id)}"
            ${!d.ota_http ? "disabled" : ""}>OTA page</button>
          <button type="button" class="ghost" data-fw-action="forget" data-node="${this._esc(d.node_id)}"
            title="Remove this board from the list">Remove</button>
        </div>
      </div>`;
      })
      .join("");


    if (this._selectedBoardId) {
      // keep the user's choice sticky across periodic re-renders
      const wanted = catalog.find((c) => c.id === this._selectedBoardId);
      if (wanted) catalog = [wanted, ...catalog.filter((c) => c !== wanted)];
    }
    const boardOptions = catalog
      .map(
        (c) =>
          `<option value="${this._esc(c.id)}"${c.id === this._selectedBoardId ? " selected" : ""}>${this._esc(HomeClimatePanel._modelLabel(c))}</option>`
      )
      .join("");

    const emptyState = devices.length
      ? ""
      : (this._status?.devices || []).length
      ? `<p class="sub" style="margin-top:10px">Your board is powered off or unreachable — it reappears here within seconds of coming back.</p>`
      : `<p class="sub" style="margin-top:10px">No board found yet — flash any supported board below with Home Climate System firmware, wire it to the boiler's OpenTherm bus and power it on; it registers here automatically.</p>`;

    return `
      <div class="card" style="margin-top:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
          <div class="zone-title" style="margin:0">Firmware</div>
          <div style="margin-left:auto;display:flex;gap:6px">
            <button type="button" class="ghost" data-fw-action="ping"
              style="padding:2px 10px;font-size:.78rem">Scan now</button>
            <button type="button" class="ghost" data-fw-action="check-updates"
              style="padding:2px 10px;font-size:.78rem">Check updates</button>
          </div>
        </div>
        <div class="zone-meta">Boards announce via MQTT every 30 s — powered-off boards hide until they return.</div>
        ${devices.length
          ? `<div style="font-size:.85rem;color:var(--secondary-text-color,#aaa);margin:12px 0 6px">Registered boards</div>
        <div class="zones">${deviceCards}</div>`
          : emptyState}
        <div style="font-size:.85rem;color:var(--secondary-text-color,#aaa);margin:18px 0 6px">
          Flash a new board
        </div>
        <div class="fw-cat">
          <div>
            <label style="display:block;font-size:.85rem;margin-bottom:6px">Board model</label>
            <select id="hcc-board-sel" style="width:100%;padding:8px;margin-top:14px;background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px">
              ${boardOptions}
            </select>
            <label style="display:block;margin-top:14px;font-size:.85rem">Flash this image to a new board</label>
            <div style="display:flex;gap:6px;margin-top:4px">
              <input id="hcc-cat-node" placeholder="node id (hcs-…)"
                style="flex:1;padding:6px;background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px">
              <button type="button" class="ghost" data-fw-action="flash-catalog"
                style="padding:6px 12px">Flash</button>
            </div>
          </div>
          <div id="hcc-board-preview" style="text-align:center">
            <img alt="" style="max-width:170px;width:100%;border-radius:10px">
            <p class="sub" style="margin-top:6px"></p>
          </div>
        </div>
      </div>
`;
  }

  _renderBoardPreview() {
    const sel = this.shadowRoot.getElementById("hcc-board-sel");
    const box = this.shadowRoot.getElementById("hcc-board-preview");
    if (!sel || !box) return;
    const catalog = this._status?.firmware_catalog || [];
    const item = catalog.find((c) => c.id === sel.value);
    if (!item) { box.style.display = "none"; return; }
    box.style.display = "";
    const img = box.querySelector("img");
    img.src = item.image || "";
    img.alt = this._esc(item.title);
    box.querySelector("p").textContent =
      item.description ? `${item.description} — v${item.version}` : `v${item.version}`;
  }

  _onFwAction(el) {
    const action = el.getAttribute("data-fw-action");
    if (action === "ping") return this._pingDevices();
    if (action === "check-updates") {
      this._hass.callWS({ type: "home_climate_control/check_updates" })
        .then(() => this._refresh());
      return;
    }
    if (action === "flash-catalog") {
      const cid = this.shadowRoot.getElementById("hcc-board-sel").value;
      const node =
        this.shadowRoot.getElementById("hcc-cat-node").value.trim();
      if (!node) {
        this._showError("Enter the target device node id (e.g. hcs-aabbccddeeff).");
        return;
      }
      this._hass
        .callWS({
          type: "home_climate_control/flash_device",
          node_id: node,
          catalog_id: cid,
        })
        .then(() => {
          this._flashNotice(
            `Update command sent to ${node}. The device downloads and reboots (~90 s).`,
            8000
          );
        })
        .catch((err) => {
          this._showError(err?.message || String(err));
        });
      return;
    }
    if (action === "flash-all") return this._flashAllOutdated();
    const nodeId = el.getAttribute("data-node");
    if (!nodeId) return;
    if (action === "open") return this._openOtaPage(nodeId);
    if (action === "reboot") return this._rebootDevice(nodeId);
    if (action === "flash") return this._flashDevice(nodeId);
    if (action === "forget") {
      if (!confirm(`Remove board ${nodeId} from the list?\n\nIts MQTT announcements are wiped, so a powered-off board stays gone. A still-running board reappears after 'Scan now' or an HA restart.`)) return;
      return this._forgetDevice(nodeId);
    }
  }

  async _forgetDevice(nodeId) {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({
        type: "home_climate_control/forget_device",
        node_id: nodeId,
      });
      this._status = { ...(this._status || {}), devices: res.devices };
      this._flashNotice(`Board ${nodeId} removed.`);
    } catch (err) {
      this._showError(err?.message || String(err));
    }
    setTimeout(() => this._refresh(), 500);
  }

  async _flashAllOutdated() {
    const ui = this._status?.systems?.[0]?.update_info;
    const targets = (ui?.outdated_devices || []).map((d) => d.node_id);
    for (const nodeId of targets) {
      try {
        await this._flashDevice(nodeId);
      } catch (err) {
        /* keep flashing the rest */
      }
      await new Promise((r) => setTimeout(r, 30000)); // device reboots + re-announces
    }
    this._refresh();
  }

  /** Transient notice: auto-clears after ms (default 4s).
      Targeted DOM update — never rebuilds the panel. */
  _flashNotice(msg, ms = 4000) {
    this._notice = msg;
    const n = this.shadowRoot.getElementById("hcc-notice");
    if (n) {
      n.hidden = false;
      n.textContent = msg;
    }
    clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => {
      this._notice = null;
      const m = this.shadowRoot.getElementById("hcc-notice");
      if (m) {
        m.hidden = true;
        m.textContent = "";
      }
    }, ms);
  }

  /** Persistent error banner, shown without rebuilding the panel. */
  _showError(msg) {
    this._error = msg || null;
    const e = this.shadowRoot.getElementById("hcc-error");
    if (e) {
      e.hidden = !msg;
      e.textContent = msg || "";
    }
  }

  async _pingDevices() {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({
        type: "home_climate_control/ping_devices",
      });
      this._status = { ...(this._status || {}), devices: res.devices };
      this._flashNotice("Discovery ping sent.");
      setTimeout(() => this._refresh(), 3000);
    } catch (err) {
      this._showError(err?.message || String(err));
    }
  }

  _selectedFirmware(nodeId, devices, catalog) {
    const sel = this.shadowRoot.querySelector(`select[data-catalog-for="${nodeId}"]`);
    let value = sel?.value;
    if (!value) {
      const dev = devices.find((d) => d.node_id === nodeId);
      value = catalog.find((c) => c.board === dev?.board)?.id;
    }
    return value;
  }

  async _flashDevice(nodeId) {
    const devices = this._status?.devices || [];
    const catalog = this._status?.firmware_catalog || [];
    const dev = devices.find((d) => d.node_id === nodeId);
    try {
      let selection = this._selectedFirmware(nodeId, devices, catalog);

      // Fallback: always resolve something from the device's board
      if (!selection && dev?.board) {
        const match = catalog.find((c) => c.board === dev.board);
        if (match) selection = match.id;
      }
      if (!selection) {
        this._showError(
          "No firmware image matches this device's board" +
          (dev?.board ? ` ('${dev.board}')` : "") + "."
        );
        return;
      }
      const item = catalog.find((c) => c.id === selection);
      let url, label;
      if (selection === "__custom__") {
        url = prompt("Firmware .bin URL:");
        if (!url) return;
        label = url.split("/").pop();
      } else {
        url = item?.url;
        label = item?.title || selection;
      }


      this._busy[nodeId] = true;
      this._notice = null;
      this._showError(null);
      await this._hass.callWS({
        type: "home_climate_control/flash_device",
        node_id: nodeId,
        ...(selection === "__custom__" ? { url } : { catalog_id: selection }),
      });
      this._flashNotice(
        `Update command sent to ${nodeId}. It will report back after rebooting into the new firmware.`,
        8000
      );
      setTimeout(() => this._refresh(), 90000);
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      delete this._busy[nodeId];
      setTimeout(() => this._refresh(), 300);
    }
  }

  async _rebootDevice(nodeId) {
    if (!confirm(`Reboot ${nodeId}?`)) return;
    try {
      await this._hass.callWS({
        type: "home_climate_control/reboot_device",
        node_id: nodeId,
      });
      this._flashNotice(`Reboot command sent to ${nodeId}.`);
    } catch (err) {
      this._showError(err?.message || String(err));
    }
  }

  _openOtaPage(nodeId) {
    const dev = (this._status?.devices || []).find((d) => d.node_id === nodeId);
    if (dev?.ota_http) window.open(dev.ota_http, "_blank", "noopener");
  }

  _ago(iso) {
    if (!iso) return "unknown";
    const ms = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(ms)) return "unknown";
    const m = Math.floor(ms / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} h ago`;
    return `${Math.floor(h / 24)} d ago`;
  }

  _placeholder(title, text, items = []) {
    return `
      <div class="card placeholder empty">
        <h2 style="margin-top:0">${this._esc(title)}</h2>
        <p>${this._esc(text)}</p>
        ${
          items.length
            ? `<ul>${items.map((i) => `<li>${this._esc(i)}</li>`).join("")}</ul>`
            : ""
        }
      </div>`;
  }

  _onZoneAction(el) {
    const action = el.getAttribute("data-zone-action");
    const id = el.getAttribute("data-entity");
    if (action === "add") {
      this._addingRoom = true;
      this._render();
      return;
    }
    if (action === "cancel-add") {
      this._addingRoom = false;
      this._render();
      return;
    }
    if (action === "create") {
      const root = this.shadowRoot;
      const name = root.getElementById("nr-name")?.value?.trim();
      const heat_control = root.getElementById("nr-control")?.value || "smart";
      const floor = parseInt(root.getElementById("nr-floor")?.value || "0", 10);
      const trv = root.getElementById("nr-trv")?.value?.trim();
      const temp_sensor = root.getElementById("nr-sensor")?.value?.trim();
      const window_sensors = (root.getElementById("nr-window")?.value || "")
        .split(",").map((x) => x.trim()).filter(Boolean);
      if (!name) { this._error = "Room name is required"; this._render(); return; }
      this._addingRoom = false;
      const lux = root.getElementById("nr-lux")?.value?.trim();
      const co2 = root.getElementById("nr-co2")?.value?.trim();
      const valve = root.getElementById("nr-valve")?.value?.trim();
      const radkw = root.getElementById("nr-radkw")?.value;
      this._adminZone("add_zone", {
        name, heat_control, floor,
        trv_climates: trv ? [trv] : [],
        temp_sensor: temp_sensor || undefined,
        window_sensors,
        lux_sensor: lux || undefined,
        co2_sensor: co2 || undefined,
        trv_position_entity: valve || undefined,
        radiator_kw: radkw !== "" && radkw != null ? parseFloat(radkw) : undefined,
      });
      return;
    }
    if (action === "edit") {
      this._editingZone = el.getAttribute("data-zone-name");
      this._render();
      return;
    }
    if (action === "cancel-edit") {
      this._editingZone = null;
      this._render();
      return;
    }
    if (action === "save-edit") {
      const zoneName = el.getAttribute("data-zone-name");
      if (!zoneName) return;
      const root = this.shadowRoot;
      const heat_control = root.getElementById("er-control")?.value || "smart";
      const floor = parseInt(root.getElementById("er-floor")?.value || "0", 10);
      const trv = root.getElementById("er-trv")?.value?.trim();
      const temp_sensor = root.getElementById("er-sensor")?.value?.trim();
      const window_sensors = (root.getElementById("er-window")?.value || "")
        .split(",").map((x) => x.trim()).filter(Boolean);
      this._editingZone = null;
      const elux = root.getElementById("er-lux")?.value?.trim() ?? null;
      const eco2 = root.getElementById("er-co2")?.value?.trim() ?? null;
      const evalve = root.getElementById("er-valve")?.value?.trim() ?? null;
      const eradkw = root.getElementById("er-radkw")?.value;
      this._adminZone("rename_zone", {
        zone: zoneName, heat_control, floor,
        trv_climates: trv ? [trv] : [],
        temp_sensor: temp_sensor || null,
        window_sensors,
        lux_sensor: elux,
        co2_sensor: eco2,
        trv_position_entity: evalve,
        radiator_kw: eradkw !== "" && eradkw != null ? parseFloat(eradkw) : null,
      });
      return;
    }
    if (action === "control") {
      const zoneName = el.getAttribute("data-zone-name");
      if (!zoneName) return;
      const sys = (this._status?.systems || [])[0];
      const zone = (sys?.zones || []).find(z => z.name === zoneName);
      const now = zone?.heat_control || "smart";
      const next = now === "manual" ? "smart" : "manual";
      const msg =
        next === "manual"
          ? `Mark "${zoneName}" as a manual radiator?\n\nHCC will observe its temperature but the valve is turned by hand.`
          : `Mark "${zoneName}" as smart-TRV controlled?`;
      if (!confirm(msg)) return;
      this._adminZone("rename_zone", { zone: zoneName, heat_control: next });
      return;
    }
    if (action === "remove") {
      const zoneName = el.getAttribute("data-zone-name");
      if (!zoneName) return;
      if (!confirm(`Remove room "${zoneName}"?\n\nIts climate entity is deleted. Learned values are kept in case you re-add it later.`)) return;
      this._adminZone("remove_zone", { zone: zoneName });
      return;
    }
    if (!id) return;
    const card = el.closest(".zone");
    const input = card?.querySelector(".temp-input");
    let t = parseFloat(input?.value ?? el.getAttribute("data-temp") ?? "20");
    if (Number.isNaN(t)) t = 20;
    if (action === "dec") {
      t = Math.max(5, t - 0.5);
      if (input) input.value = t;
      this._setZone(id, { temperature: t });
      return;
    }
    if (action === "inc") {
      t = Math.min(30, t + 0.5);
      if (input) input.value = t;
      this._setZone(id, { temperature: t });
      return;
    }
    if (action === "apply") {
      if (input) t = parseFloat(input.value);
      this._setZone(id, { temperature: t });
    }
    if (action === "calibrate") {
      const zoneName = el.getAttribute("data-zone-name");
      if (!zoneName) return;
      if (!confirm("Calibrate this room? The target will be raised ~2 °C for up to 90 minutes while the room's warm-up speed is measured. Keep windows/doors closed.")) return;
      this._calibrateZone("start", zoneName, id);
    }
  }

  async _adminZone(command, payload) {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({
        type: `home_climate_control/${command}`,
        ...payload,
      });
      this._status = res.status || this._status;
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._render();
  }

  async _setOptions(patch) {
    if (!this._hass || !patch || !Object.keys(patch).length) return;
    try {
      const res = await this._hass.callWS({
        type: "home_climate_control/set_options",
        ...patch,
      });
      this._status = res.status || this._status;
      this._error = null;
      this._soptMsg = "Saved ✓";
      this._occDraft = null; // committed — future renders bind to saved values
    } catch (err) {
      this._error = err?.message || String(err);
      this._soptMsg = null;
    }
    this._render();
  }

  _soptNum(id) {
    const el = this.shadowRoot.getElementById(id);
    if (!el || el.value === "") return null;
    const v = parseFloat(el.value);
    return Number.isFinite(v) ? v : null;
  }

  _soptSel(id, allowEmpty) {
    const el = this.shadowRoot.getElementById(id);
    if (!el) return undefined;
    const v = (el.value || "").trim();
    if (!v) return allowEmpty ? "" : undefined;
    return v;
  }

  _onSoptSave(group) {
    const r = this.shadowRoot;
    let patch = {};
    switch (group) {
      case "curve": {
        const curve = this._soptNum("so-curve");
        const mn = this._soptNum("so-minflow");
        const mx = this._soptNum("so-maxflow");
        if (curve != null) patch.curve_coeff = curve;
        if (mn != null) patch.min_flow_temp = mn;
        if (mx != null) patch.max_flow_temp = mx;
        break;
      }
      case "outdoor": {
        const outdoor = this._soptSel("so-outdoor", true);
        if (outdoor !== undefined) patch.outdoor_sensor = outdoor;
        const wind = this._soptSel("so-wind-entity", true);
        if (wind !== undefined) patch.wind_entity = wind;
        const cap = this._soptNum("so-wind-cap");
        if (cap != null) patch.wind_max_delta = cap;
        break;
      }
      case "load": {
        const mm = this._soptNum("so-minmod");
        if (mm != null) patch.boiler_min_modulation = mm;
        break;
      }
      case "schedule": {
        const sched = this._soptSel("so-sched", true);
        if (sched !== undefined) patch.schedule_entity = sched;
        const on = this._soptSel("so-sched-on", false);
        if (on !== undefined) patch.schedule_on_preset = on;
        const off = this._soptSel("so-sched-off", false);
        if (off !== undefined) patch.schedule_off_preset = off;
        break;
      }
      case "occupancy": {
        patch.occupancy_trackers = Array.isArray(this._occDraft)
          ? [...this._occDraft]
          : (o.occupancy_trackers || []);
        const away = this._soptSel("so-occ-away", false);
        if (away !== undefined) patch.occupancy_away_preset = away;
        const home = this._soptSel("so-occ-home", false);
        if (home !== undefined) patch.occupancy_home_preset = home;
        break;
      }
      case "presets": {
        const po = {};
        for (const k of ["comfort", "eco", "away", "boost"]) {
          const v = this._soptNum(`so-pre-${k}`);
          if (v != null) po[k] = v;
        }
        if (Object.keys(po).length) patch.preset_offsets = po;
        break;
      }
      case "gas": {
        const rated = this._soptNum("so-gas-rated");
        const minKw = this._soptNum("so-gas-min");
        const nomod = this._soptNum("so-gas-nomod");
        const calib = this._soptNum("so-gas-calib");
        const price = this._soptNum("so-gas-price");
        if (rated != null) patch.rated_heat_input_kw = rated;
        if (minKw != null) patch.min_heat_input_kw = minKw;
        if (nomod != null) patch.nomod_duty_factor = nomod;
        if (calib != null) patch.gas_calibration = calib;
        if (price != null) patch.gas_price_per_kwh = price;
        break;
      }
      default:
        return;
    }
    this._setOptions(patch);
  }

  _occDraftArray() {
    if (Array.isArray(this._occDraft)) return this._occDraft;
    return this._status?.systems?.[0]?.options?.occupancy_trackers || [];
  }

  _occAddTracker() {
    const sel = this.shadowRoot.getElementById("so-occ-add");
    const id = sel?.value;
    if (!id) return;
    const cur = this._occDraftArray();
    if (!cur.includes(id)) this._occDraft = [...cur, id];
    this._render();
  }

  _occRemoveTracker(id) {
    this._occDraft = this._occDraftArray().filter((x) => x !== id);
    this._render();
  }

  async _calibrateZone(action, zoneName, entityId) {
    if (!this._hass || !zoneName) return;
    try {
      const res = await this._hass.callWS({
        type: "home_climate_control/calibrate_zone",
        action,
        zone: zoneName,
        entity_id: entityId || "",
      });
      this._status = res.status || this._status;
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._render();
  }

  _fmt(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    if (typeof v === "number") return (Math.round(v * 10) / 10).toString();
    return String(v);
  }

  _esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /**
   * Boiler diagnostics banner: reads the HCS device's boiler_diag sensor
   * entity (plain English fault text). Hidden when healthy/unknown.
   */
  /**
   * Boiler picture card, top-right of the overview: image + maker/model
   * caption underneath. Hidden when no boiler info is available.
   */
  _boilerPictureHtml(sys) {
    const bi = sys?.boiler_info;
    if (!bi || (!bi.make && !bi.detected_make)) return "";
    const make = bi.make || bi.detected_make || "";
    const model = bi.model || "";
    return `<div class="boiler-pic">
      ${bi.image ? `<img src="${bi.image}" alt="${this._esc(make)}">` : ""}
      <div class="bp-cap">${this._esc(make)}${model ? `<br>${this._esc(model)}` : ""}</div>
    </div>`;
  }

  _boilerPillHtml(sys) {
    /* Header pill:
       red   = board MQTT offline / no telemetry (5 min)
       amber = board up but OT bus down, or boiler diagnostic text
       green = board MQTT up (OT optional)
       (hidden only before any state is known) */
    if (!this._hass?.states) return "";
    const b = this._status?.systems?.[0]?.boiler || {};
    const conn = b.boiler_connected;
    const ot = b.ot_valid;

    let text = "";
    const entry = Object.entries(this._hass.states).find(([id]) =>
      id.endsWith("_boiler_diagnostic")
    );
    if (entry) {
      const t = String(entry[1].state ?? "");
      // "no data" = board hasn't read ASF/OEM diag yet — not a fault
      if (t && t !== "unknown" && t !== "unavailable" && t !== "no faults" &&
          t !== "ok" && t !== "no data") text = t;
    }

    if (conn === false) {
      return `<span class="hdr-alert" title="No MQTT telemetry from the HCS board recently — check power, Wi‑Fi, MQTT broker, and node id">
        <ha-icon icon="mdi:lan-disconnect" style="--mdc-icon-size:16px;vertical-align:-3px"></ha-icon>
        <span class="hdr-alert-txt">Board offline</span>
      </span>`;
    }
    if (conn === true && ot === false) {
      return `<span class="hdr-alert" title="Board is online over MQTT, but OpenTherm Status is not answering — check OT wiring / boiler power">
        <ha-icon icon="mdi:fire-off" style="--mdc-icon-size:16px;vertical-align:-3px"></ha-icon>
        <span class="hdr-alert-txt">OT not linked</span>
      </span>`;
    }
    if (text) {
      return `<span class="hdr-alert" title="Boiler diagnostic: ${this._esc(text)}">
        <ha-icon icon="mdi:fire-alert" style="--mdc-icon-size:16px;vertical-align:-3px"></ha-icon>
        <span class="hdr-alert-txt">${this._esc(text)}</span>
      </span>`;
    }
    if (conn === true) {
      const tip = ot === true
        ? "Board MQTT up · OpenTherm linked"
        : "Board MQTT up (OT status unknown — flash firmware ≥1.4.5 for ot_valid)";
      return `<span class="hdr-ok" title="${this._esc(tip)}">
        <ha-icon icon="mdi:fire" style="--mdc-icon-size:16px;vertical-align:-3px"></ha-icon>
        <span class="hdr-ok-txt">Boiler connected</span>
      </span>`;
    }
    return "";
  }
}

customElements.define("home-climate-panel", HomeClimatePanel);
