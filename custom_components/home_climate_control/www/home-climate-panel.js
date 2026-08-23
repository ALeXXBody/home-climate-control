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
    this._tab = "overview";
    this._loading = true;
    this._error = null;
    this._notice = null;
    this._busy = {};
    this._poll = null;
    this._selectedBoardId = null;
  }

  set hass(hass) {
    const first = this._hass == null;
    this._hass = hass;
    if (first) {
      this._render();
      this._refresh();
      this._poll = setInterval(() => this._refresh(), 5000);
    }
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
  }

  async _refresh() {
    if (!this._hass) return;
    // Avoid stacking renders while a flash/reboot is in flight.
    if (Object.keys(this._busy || {}).length) return;
    try {
      this._status = await this._hass.callWS({
        type: "home_climate_control/get_status",
      });
      this._error = null;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._loading = false;
    this._render();
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

    root.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          background: var(--primary-background-color, #111);
          color: var(--primary-text-color, #eee);
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
          box-sizing: border-box;
        }
        * { box-sizing: border-box; }
        .wrap {
          position: relative;
          max-width: 1100px;
          margin: 0 auto;
          padding: 16px 20px 40px;
        }
        .boiler-pic {
          position: absolute;
          top: -6px;
          right: 0;
          width: 120px;
          text-align: center;
          background: var(--secondary-background-color, #16181c);
          border: 1px solid var(--divider-color, #2a2e33);
          border-radius: 12px;
          padding: 8px 8px 6px;
        }
        .boiler-pic img { width: 100%; height: auto; display: block; border-radius: 6px; }
        .boiler-pic .bp-cap {
          font-size: 0.78rem; color: var(--secondary-text-color, #bbb);
          margin-top: 4px; line-height: 1.25;
        }
        header {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }
        h1 {
          font-size: 1.5rem;
          font-weight: 500;
          margin: 0;
          flex: 1;
        }
        .tabs {
          display: flex;
          gap: 4px;
          flex-wrap: wrap;
          margin-bottom: 20px;
          border-bottom: 1px solid var(--divider-color, #333);
          padding-bottom: 8px;
        }
        .tab {
          background: transparent;
          border: none;
          color: var(--secondary-text-color, #aaa);
          padding: 8px 14px;
          border-radius: 8px 8px 0 0;
          cursor: pointer;
          font-size: 0.95rem;
        }
        .tab.active {
          color: var(--primary-color, #03a9f4);
          background: var(--secondary-background-color, #1c1c1c);
          font-weight: 600;
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
        .zones { display: flex; flex-direction: column; gap: 12px; }
        .zone {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 12px;
          align-items: center;
        }
        @media (max-width: 640px) {
          .zone { grid-template-columns: 1fr; }
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
          margin-top: 32px;
          padding-top: 16px;
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

      </style>
      <div class="wrap">
        <header>
          <h1>Home Climate ${sys?.demo ? '<span class="badge heat" style="font-size:0.7rem;vertical-align:middle">DEMO</span>' : ""}</h1>
          <button class="ghost refresh" type="button" data-action="refresh">Refresh</button>
        </header>
        <nav class="tabs">
          ${this._tabBtn("overview", "Overview")}
          ${this._tabBtn("zones", "Rooms")}
          ${this._tabBtn("floorplan", "Floor plan")}
          ${this._tabBtn("firmware", "Firmware")}
          ${this._tabBtn("settings", "Settings")}
        </nav>
        ${this._error ? `<div class="error">${this._esc(this._error)}</div>` : ""}
        ${this._boilerDiagBanner()}
        ${this._notice ? `<div class="notice">${this._esc(this._notice)}</div>` : ""}
        ${this._loading ? `<div class="empty">Loading…</div>` : this._body(sys, systems)}
        <footer>
          <span>Home Climate Control</span>
          <a href="https://github.com/ALeXXBody/home-climate-control" target="_blank" rel="noopener">Software</a>
          <a href="https://github.com/ALeXXBody/home-climate-system" target="_blank" rel="noopener">Hardware</a>
          <a href="https://buymeacoffee.com/alexxbody" target="_blank" rel="noopener">Buy me a coffee</a>
        </footer>
      </div>
    `;

    root.querySelectorAll("[data-tab]").forEach((el) => {
      el.addEventListener("click", () => {
        this._tab = el.getAttribute("data-tab");
        this._render();
      });
    });
    root.querySelector('[data-action="refresh"]')?.addEventListener("click", () => {
      this._loading = true;
      this._render();
      this._refresh();
    });
    root.querySelectorAll("[data-zone-action]").forEach((el) => {
      el.addEventListener("click", () => this._onZoneAction(el));
    });
    root.querySelectorAll("[data-zone-mode]").forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.getAttribute("data-entity");
        this._setZone(id, { hvac_mode: el.value });
      });
    });
    root.querySelectorAll("[data-zone-preset]").forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.getAttribute("data-entity");
        this._setZone(id, { preset_mode: el.value });
      });
    });
    root.querySelectorAll("[data-fw-action]").forEach((el) => {
      el.addEventListener("click", () => this._onFwAction(el));
    });
    root
      .querySelector('[data-action="save-failsafe"]')
      ?.addEventListener("click", () => this._onSaveFailsafe());
    root
      .querySelector('[data-action="save-boiler-info"]')
      ?.addEventListener("click", () => this._onSaveBoilerInfo());
    const bsel = this.shadowRoot.getElementById("hcc-board-sel");
    bsel?.addEventListener("change", () => {
      this._selectedBoardId = bsel.value;
      this._renderBoardPreview();
    });
    if (this._selectedBoardId) bsel.value = this._selectedBoardId;
    this._renderBoardPreview();
    this._populateBoilerCatalog();
  }

  async _populateBoilerCatalog() {
    const makeSel = this.shadowRoot.getElementById("hcc-bi-make");
    if (!makeSel || makeSel.options.length > 1) return; // already populated
    try {
      const cat = await this._hass.callWS({
        type: "home_climate_control/get_boiler_catalog",
      });
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
      makeSel.addEventListener("change", () =>
        this._fillBoilerModels(cat, null)
      );
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
    const msg = this.shadowRoot.getElementById("hcc-bi-msg");
    try {
      await this._hass.callWS({
        type: "home_climate_control/set_boiler_info",
        make: this.shadowRoot.getElementById("hcc-bi-make").value || null,
        model: this.shadowRoot.getElementById("hcc-bi-model").value || null,
      });
      if (msg) msg.textContent = "Saved";
      this._refresh();
    } catch (err) {
      if (msg) msg.textContent = "Failed: " + (err?.message || String(err));
    }
    setTimeout(() => {
      if (msg) msg.textContent = "";
    }, 3000);
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
      case "zones":
        return this._zonesHtml(sys);
      case "floorplan":
        return this._placeholder(
          "Floor plan",
          "Coming soon: interactive house layout with room temperatures and heat demand."
        );
      case "firmware":
        return this._firmwareHtml();
      case "settings":
        return this._settingsHtml(sys);
      default:
        return `<div style="position:relative">${this._boilerPictureHtml(sys)}${this._overviewHtml(sys)}</div>`;
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
          <div class="sub">${sys.demo ? "Simulated outdoor (demo)" : "Boiler outdoor sensor"}</div></div>
        <div class="card"><h3>Flow setpoint</h3><div class="metric">${flow}<span class="unit">°C</span></div>
          <div class="sub">Weather-compensated target</div></div>
        <div class="card"><h3>Total demand</h3><div class="metric">${demand}<span class="unit">%</span></div>
          <div class="sub">Active: ${this._esc(active)}</div></div>
        <div class="card"><h3>Boiler</h3><div class="metric" style="font-size:1.1rem">${ch} ${flame}</div>
          <div class="sub">Mod ${this._fmt(sys.boiler?.modulation_level)}% · Return ${this._fmt(sys.boiler?.return_temp)}°C</div></div>
      </div>
      ${this._zonesHtml(sys, true)}
    `;
  }

  _zonesHtml(sys, compact = false) {
    const zones = sys.zones || [];
    if (!zones.length) {
      return `<div class="card empty">No rooms configured. Add rooms (TRV + optional temp sensor) in the integration setup.</div>`;
    }
    return `
      <div class="zones">
        ${zones
          .map((z) => {
            const heat =
              String(z.hvac_action).includes("heat") || z.hvac_action === "heating";
            return `
          <div class="card zone">
            <div>
              <div class="zone-title">${this._esc(z.name || z.entity_id || "Room")}</div>
              <div class="zone-meta">
                ${this._fmt(z.current_temperature)}°C → ${this._fmt(z.effective_setpoint ?? z.target_temperature)}°C
                · demand ${Math.round((z.demand_level || 0) * 100)}%
                ${z.trv ? ` · TRV ${this._esc(z.trv)}` : ""}
                ${z.temp_sensor ? ` · sensor ${this._esc(z.temp_sensor)}` : (z.temp_source === "trv" ? " · temp from TRV" : "")}
                ${(z.window_sensors || []).length
                  ? ` · window ${this._esc((z.window_sensors || []).join(", "))}`
                  : ""}
                ${z.window_open ? ' · <span class="badge heat">window/door open</span>' : ""}
                ${heat ? ' · <span class="badge heat">heating</span>' : ""}
              </div>
            </div>
            ${
              compact
                ? ""
                : `
            <div class="controls">
              <div class="temp-row">
                <button type="button" data-zone-action="dec" data-entity="${this._esc(z.entity_id || "")}" data-temp="${z.target_temperature ?? 20}">−</button>
                <input type="number" step="0.5" min="5" max="30" value="${z.target_temperature ?? 20}"
                  data-entity="${this._esc(z.entity_id || "")}" class="temp-input" />
                <button type="button" data-zone-action="inc" data-entity="${this._esc(z.entity_id || "")}" data-temp="${z.target_temperature ?? 20}">+</button>
                <button type="button" data-zone-action="apply" data-entity="${this._esc(z.entity_id || "")}">Set</button>
              </div>
              <select data-zone-mode data-entity="${this._esc(z.entity_id || "")}">
                <option value="heat" ${String(z.hvac_mode) === "heat" ? "selected" : ""}>Heat</option>
                <option value="off" ${String(z.hvac_mode) === "off" ? "selected" : ""}>Off</option>
              </select>
              <select data-zone-preset data-entity="${this._esc(z.entity_id || "")}">
                ${["none", "away", "eco", "comfort", "boost"]
                  .map(
                    (p) =>
                      `<option value="${p}" ${z.preset_mode === p ? "selected" : ""}>${p}</option>`
                  )
                  .join("")}
              </select>
            </div>`
            }
          </div>`;
          })
          .join("")}
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

  _settingsHtml(sys) {
    const bi = sys?.boiler_info || {};
    const detected = bi.detected_make
      ? `<p class="sub">Detected from boiler MemberID ${bi.member_id ?? "?"}: <strong>${this._esc(bi.detected_make)}</strong></p>`
      : `<p class="sub">No MemberID received yet — select manually.</p>`;
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
          <p class="sub">${sys.gas.last_rate_kw != null ? `now: ${this._esc(sys.gas.last_rate_kw)} kW · ` : ""}${sys.gas.total_kwh != null ? `total: ${this._esc(sys.gas.total_kwh)} kWh` : ""}${sys.gas.today_cost != null ? ` · ~${this._esc(sys.gas.today_cost)} today` : ""}</p>
        </div>` : ""}
        ${sys.setbacks ? `<div class="card"><h3>Smart setbacks</h3>
          ${Object.entries(sys.setbacks.rooms || {}).length === 0 ? '<p class="sub">No rooms seen yet — learning starts after the first away/eco period.</p>' : Object.entries(sys.setbacks.rooms).map(([n, r]) => `<p class="sub"><strong>${this._esc(n)}</strong>: ${r.mature ? `${this._esc(r.learned_offset)}°C` : "learning…"} <span style="opacity:.7">(${r.cycles} cycle${r.cycles === 1 ? "" : "s"}${r.warm_rate ? ` · ${this._esc(r.warm_rate)}°C/h recovery` : ""})</span></p>`).join("")}
        </div>` : ""}
        ${(sys.probes && sys.probes.length) ? `<div class="card"><h3>1-Wire probes</h3>
          ${sys.probes.map(p => `<p class="sub"><strong>${this._esc((p.addr || "").slice(-8) || "?")}</strong>: ${p.temp_c != null ? this._esc(p.temp_c) + "°C" : "—"} · ${this._esc(p.health || "?")} · ${this._esc(p.role || "none")}${p.name ? " · " + this._esc(p.name) : ""}</p>`).join("")}
        </div>` : ""}
        <div class="card"><h3>Entry</h3><div class="sub">${this._esc(sys.entry_id || "")}</div></div>
      </div>
      <div class="card">
        <h3>Your boiler</h3>
        ${detected}
        <label>Manufacturer</label>
        <select id="hcc-bi-make" data-role="bi-make" style="width:100%;padding:8px;background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px">
          <option value="">— auto-detected —</option>
        </select>
        <label style="margin-top:8px">Model</label>
        <select id="hcc-bi-model" style="width:100%;padding:8px;background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px">
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
      <div class="card placeholder">
        <p>Tune curve and flow limits via <strong>Settings → Devices &amp; services → Home Climate Control → Configure</strong>.</p>
      </div>`;
  }

  static _modelLabel(c) {
    if (!c) return "";
    if (c.model) return c.model;
    // Fallback: strip legacy "HCS x.y.z — " / "HCS x.y.z GW — " prefixes.
    return String(c.title || "").replace(/^HCS\s+[\d.]+\s+(GW\s+)?—\s+/, "");
  }

  _firmwareHtml() {
    // Only currently-online boards — a powered-off module re-registers
    // within seconds of coming back, so no need to keep dead cards around.
    const devices = (this._status?.devices || []).filter((d) => d.online);
    let catalog = [...(this._status?.firmware_catalog || [])];
    const online = devices.filter((d) => d.online).length;
    const ui = this._status?.systems?.[0]?.update_info || null;
    const outdatedIds = new Set(
      (ui?.outdated_devices || []).map((d) => d.node_id)
    );

    let banner = "";
    if (ui?.error) {
      banner = `<div class="card placeholder"><p class="sub">Update check failed: ${this._esc(ui.error)}</p></div>`;
    } else if (ui?.available) {
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
    } // "up to date" state moved onto each device card as a pill

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
      <div class="card zone">
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
        </div>
        <div class="controls">
          <select data-catalog-for="${this._esc(d.node_id)}">${options}</select>
          <button type="button" data-fw-action="flash" data-node="${this._esc(d.node_id)}"
            ${!d.online || this._busy[d.node_id] ? "disabled" : ""}>Flash</button>
          <button type="button" class="ghost" data-fw-action="reboot" data-node="${this._esc(d.node_id)}"
            ${!d.online || this._busy[d.node_id] ? "disabled" : ""}>Reboot</button>
          <button type="button" class="ghost" data-fw-action="open" data-node="${this._esc(d.node_id)}"
            ${!d.ota_http ? "disabled" : ""}>OTA page</button>
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

    return `
      <div class="card zone" style="margin-bottom:16px">
        <div>
          <div class="zone-title">Boiler gateway${devices.length === 1 ? "" : "s"}</div>
          <div class="zone-meta">${devices.length === 1
            ? "This board bridges Home Assistant to your boiler (OpenTherm). It announces itself on MQTT — power it off and it hides until it returns."
            : `${devices.length} gateways online — boards announce via MQTT every 30 s; powered-off boards are hidden until they return`}</div>
        </div>
        <div class="controls">
          <button type="button" class="ghost" data-fw-action="ping">Scan now</button>
          <button type="button" class="ghost" data-fw-action="check-updates">Check updates</button>
        </div>

      </div>
      ${banner}
      ${
        devices.length
          ? `<div class="zones">${deviceCards}</div>`
          : (this._status?.devices || []).length
          ? `<div class="empty card">Gateway offline.<p class="sub">Your board is powered off or unreachable — it reappears here within seconds of coming back.</p></div>`
          : `<div class="empty card">No boiler gateway found yet.<p class="sub">Flash any supported board below with Home Climate System firmware, wire it to the boiler's OpenTherm bus and power it on — it announces itself on MQTT (<code>hcs/discovery/&lt;node&gt;</code>) and appears here automatically.</p></div>`
      }
      <h3 style="margin:24px 0 8px;font-size:1rem;font-weight:500">Firmware catalog</h3>
      <div class="card fw-cat">
        <div>
          <label style="display:block;font-size:.85rem;margin-bottom:6px">Board model</label>
          <select id="hcc-board-sel" style="width:100%;padding:8px;background:var(--secondary-background-color,#1c1c1c);color:inherit;border:1px solid var(--divider-color,#333);border-radius:6px">
            ${boardOptions}
          </select>
          <label style="display:block;margin-top:14px;font-size:.85rem">Flash this image to a device</label>
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
        this._error = "Enter the target device node id (e.g. hcs-aabbccddeeff).";
        this._render();
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
          this._error = err?.message || String(err);
          this._render();
        });
      return;
    }
    if (action === "flash-all") return this._flashAllOutdated();
    const nodeId = el.getAttribute("data-node");
    if (!nodeId) return;
    if (action === "open") return this._openOtaPage(nodeId);
    if (action === "reboot") return this._rebootDevice(nodeId);
    if (action === "flash") return this._flashDevice(nodeId);
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

  /** Transient notice: auto-clears after ms (default 4s). */
  _flashNotice(msg, ms = 4000) {
    this._notice = msg;
    this._render();
    clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => {
      this._notice = null;
      this._render();
    }, ms);
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
      this._error = err?.message || String(err);
    }
    this._render();
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
        this._error =
          "No firmware image matches this device's board" +
          (dev?.board ? ` ('${dev.board}')` : "") + ".";
        this._render();
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
      this._error = null;
      this._render();
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
      this._render();
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
      this._error = err?.message || String(err);
      this._render();
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
    if (!id) return;
    const card = el.closest(".zone");
    const input = card?.querySelector(".temp-input");
    let t = parseFloat(input?.value ?? el.getAttribute("data-temp") ?? "20");
    if (Number.isNaN(t)) t = 20;
    if (action === "dec") {
      t = Math.max(5, t - 0.5);
      if (input) input.value = t;
      return;
    }
    if (action === "inc") {
      t = Math.min(30, t + 0.5);
      if (input) input.value = t;
      return;
    }
    if (action === "apply") {
      if (input) t = parseFloat(input.value);
      this._setZone(id, { temperature: t });
    }
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

  _boilerDiagBanner() {
    if (!this._hass?.states) return "";
    const entry = Object.entries(this._hass.states).find(([id]) =>
      id.endsWith("_boiler_diagnostic")
    );
    if (!entry) return "";
    const st = entry[1];
    const text = String(st.state ?? "");
    if (!text || text === "unknown" || text === "no faults") return "";
    return `<div class="error" style="display:flex;align-items:center;gap:8px">
      <ha-icon icon="mdi:fire-alert"></ha-icon>
      <span>Boiler: ${this._esc(text)}</span>
      <button class="ghost refresh" type="button"
        style="margin-left:auto;padding:2px 10px;font-size:0.8rem"
        onclick="this.getRootNode().host._refresh()">Recheck</button>
    </div>`;
  }
}

customElements.define("home-climate-panel", HomeClimatePanel);
