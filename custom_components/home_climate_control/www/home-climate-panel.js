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
          max-width: 1100px;
          margin: 0 auto;
          padding: 16px 20px 40px;
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
      </style>
      <div class="wrap">
        <header>
          <h1>Home Climate ${sys?.demo ? '<span class="badge heat" style="font-size:0.7rem;vertical-align:middle">DEMO</span>' : ""}</h1>
          <button class="ghost refresh" type="button" data-action="refresh">Refresh</button>
        </header>
        <nav class="tabs">
          ${this._tabBtn("overview", "Overview")}
          ${this._tabBtn("zones", "Zones")}
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
          "Coming soon: interactive house layout with zone temperatures and heat demand."
        );
      case "firmware":
        return this._firmwareHtml();
      case "settings":
        return this._settingsHtml(sys);
      default:
        return this._overviewHtml(sys);
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
      return `<div class="card empty">No zones in this system.</div>`;
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
              <div class="zone-title">${this._esc(z.name || z.entity_id || "Zone")}</div>
              <div class="zone-meta">
                ${this._fmt(z.current_temperature)}°C → ${this._fmt(z.effective_setpoint ?? z.target_temperature)}°C
                · demand ${Math.round((z.demand_level || 0) * 100)}%
                ${z.window_open ? " · window open" : ""}
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

  _settingsHtml(sys) {
    return `
      <div class="grid">
        <div class="card"><h3>Curve coefficient</h3><div class="metric">${this._fmt(sys.curve_coeff)}</div></div>
        <div class="card"><h3>Min flow</h3><div class="metric">${this._fmt(sys.min_flow)}<span class="unit">°C</span></div></div>
        <div class="card"><h3>Max flow</h3><div class="metric">${this._fmt(sys.max_flow)}<span class="unit">°C</span></div></div>
        <div class="card"><h3>Entry</h3><div class="sub">${this._esc(sys.entry_id || "")}</div></div>
      </div>
      <div class="card placeholder">
        <p>Tune curve and flow limits via <strong>Settings → Devices &amp; services → Home Climate Control → Configure</strong>.</p>
        <p class="sub">Editable settings in this panel will be added later.</p>
      </div>`;
  }

  _firmwareHtml() {
    const devices = this._status?.devices || [];
    const catalog = this._status?.firmware_catalog || [];
    const online = devices.filter((d) => d.online).length;

    const deviceCards = devices
      .map((d) => {
        const match = catalog.find((c) => c.board === d.board) || null;
        const update = match && match.version !== d.version ? match : null;
        const options = [
          ...catalog.map(
            (c) =>
              `<option value="${this._esc(c.id)}" ${match === c ? "selected" : ""}>${this._esc(c.title)}</option>`
          ),
          `<option value="__custom__">Custom URL…</option>`,
        ].join("");
        return `
      <div class="card zone">
        <div>
          <div class="zone-title">${this._esc(d.name || d.node_id)}
            ${d.online ? '<span class="badge on">online</span>' : '<span class="badge off">offline</span>'}
            ${update ? `<span class="badge heat">v${this._esc(update.version)} available</span>` : ""}
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

    const catalogRows = catalog
      .map(
        (c) => `
      <div class="card zone">
        <div>
          <div class="zone-title">${this._esc(c.title)}</div>
          <div class="zone-meta">${this._esc(c.notes || "")} · board: ${this._esc(c.board)}</div>
        </div>
        <div class="controls"><a href="${this._esc(c.url)}" target="_blank" rel="noopener"><button type="button" class="ghost">Download</button></a></div>
      </div>`
      )
      .join("");

    return `
      <div class="card zone" style="margin-bottom:16px">
        <div>
          <div class="zone-title">Devices</div>
          <div class="zone-meta">${online} online / ${devices.length} known — devices announce via MQTT discovery every 30 s</div>
        </div>
        <div class="controls">
          <button type="button" class="ghost" data-fw-action="ping">Scan now</button>
        </div>
      </div>
      ${
        devices.length
          ? `<div class="zones">${deviceCards}</div>`
          : `<div class="empty card">No HCS devices discovered yet.<p class="sub">Power on a device with Home Climate System firmware; it announces itself on MQTT topic <code>hcs/discovery/&lt;node&gt;</code>.</p></div>`
      }
      <h3 style="margin:24px 0 8px;font-size:1rem;font-weight:500">Firmware catalog</h3>
      ${catalog.length ? `<div class="zones">${catalogRows}</div>` : `<div class="sub">Catalog unavailable.</div>`}`;
  }

  _onFwAction(el) {
    const action = el.getAttribute("data-fw-action");
    if (action === "ping") return this._pingDevices();
    const nodeId = el.getAttribute("data-node");
    if (!nodeId) return;
    if (action === "open") return this._openOtaPage(nodeId);
    if (action === "reboot") return this._rebootDevice(nodeId);
    if (action === "flash") return this._flashDevice(nodeId);
  }

  async _pingDevices() {
    if (!this._hass) return;
    try {
      const res = await this._hass.callWS({
        type: "home_climate_control/ping_devices",
      });
      this._status = { ...(this._status || {}), devices: res.devices };
      this._notice = "Discovery ping sent.";
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
    const selection = this._selectedFirmware(nodeId, devices, catalog);
    if (!selection) return;
    const dev = devices.find((d) => d.node_id === nodeId);
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
    if (!confirm(
      `Flash "${label}" to ${dev?.name || nodeId}?\n\nThe device downloads firmware over HTTP and reboots (~60 s). Do not power it off during the update.`
    )) return;

    this._busy[nodeId] = true;
    this._notice = null;
    this._error = null;
    this._render();
    try {
      await this._hass.callWS({
        type: "home_climate_control/flash_device",
        node_id: nodeId,
        ...(selection === "__custom__" ? { url } : { catalog_id: selection }),
      });
      this._notice = `Update command sent to ${nodeId}. It will report back after rebooting into the new firmware.`;
      setTimeout(() => this._refresh(), 90000);
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      delete this._busy[nodeId];
      this._refresh();
    }
  }

  async _rebootDevice(nodeId) {
    if (!confirm(`Reboot ${nodeId}?`)) return;
    try {
      await this._hass.callWS({
        type: "home_climate_control/reboot_device",
        node_id: nodeId,
      });
      this._notice = `Reboot command sent to ${nodeId}.`;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._refresh();
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
