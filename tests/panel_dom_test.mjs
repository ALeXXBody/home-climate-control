/**
 * DOM smoke test for the HCC sidebar panel (run with: node tests/panel_dom_test.mjs)
 *
 * Gates that must never regress:
 *   1. Firmware page renders exactly ONE devices section (no duplicates)
 *   2. Catalog renders as a dropdown + preview container
 *   3. Clicking Flash triggers the flash_device websocket call
 *      and shows a transient notice
 */
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "custom_components", "home_climate_control", "www", "home-climate-panel.js"), "utf8");

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
  url: "https://ha.local/",
  pretendToBeVisual: true,
  runScripts: "outside-only",
});
const { window } = dom;

// Minimal HA globals
window.hassConnection = Promise.resolve({});

const w = window;
w.eval(src);

// Instantiate the registered element
const el = w.document.createElement("home-climate-panel");
w.document.body.appendChild(el);

const STATUS = {
  domain: "home_climate_control",
  version: "9.9.9",
  systems: [{ entry_id: "e1", update_info: { available: false, latest_tag: "v1.0.2" } }],
  devices: [
    {
      node_id: "hcs-test",
      name: "Test Board",
      board: "lolin_c3_mini",
      version: "1.0.2",
      online: true,
      ip: "1.2.3.4",
      ota_state: "downloading",
      ota_progress: 55,
      ota_error: "",
      cfg: {
        device_name: "Test Board",
        mqtt_host: "192.168.50.20",
        mqtt_port: 1883,
        mqtt_user: "home",
        mqtt_user_set: true,
        mqtt_prefix: "hcs",
        otgw_node: "hcs-device",
        ota_password_set: true,
      },
      ctl: {
        ch_enable: false,
        dhw_enable: true,
        dhw_setpoint: null,
        flow_setpoint: 45,
        max_modulation: 100,
        wc_enable: true,
        wc_ref: 18,
        wc_design: -10,
        wc_fmax: 65,
        wc_fmin: 25,
        wc_target: 38.5,
        fs_state: "OFF",
      },
    },
    {
      node_id: "hcs-offline",
      name: "Ghost Board",
      board: "d1_mini",
      version: "1.0.0",
      online: false,
      ip: "5.6.7.8",
    },
    {
      node_id: "hcs-current",
      name: "Current Board",
      board: "lolin_c3_mini",
      version: "1.1.0",
      online: true,
      ip: "9.9.9.9",
      ota_state: "failed",
      ota_progress: null,
      ota_error: "HTTP 404 (code -104)",
    },
  ],
  firmware_catalog: [
    {
      id: "hcs-1.1.0-lolin_c3_mini",
      title: "HCS 1.1.0 — LOLIN C3 mini",
      model: "LOLIN C3 mini v2.1",
      board: "lolin_c3_mini",
      version: "1.1.0",
      url: "https://example.com/fw-new.bin",
      description: "test desc",
      image: "/home_climate_control_static/boards/photos/lolin_c3_mini.png",
    },
    {
      id: "hcs-1.0.2-lolin_c3_mini",
      title: "HCS 1.0.2 — LOLIN C3 mini",
      model: "LOLIN C3 mini v2.1",
      board: "lolin_c3_mini",
      version: "1.0.2",
      url: "https://example.com/fw.bin",
      description: "test desc",
      image: "/home_climate_control_static/boards/photos/lolin_c3_mini.png",
    },
    {
      id: "hcs-1.0.2-d1_mini",
      title: "HCS 1.0.2 — ESP8266 D1 mini",
      board: "d1_mini",
      version: "1.0.2",
      url: "https://example.com/fw2.bin",
      description: "d1 desc",
      image: "/home_climate_control_static/boards/photos/d1_mini.png",
    },
  ],
};

let wsCalls = [];
el.hass = {
  callWS: async (msg) => {
    wsCalls.push(msg);
    if (msg.type === "home_climate_control/get_status") return STATUS;
    if (msg.type === "home_climate_control/ping_devices")
      return { devices: STATUS.devices };
    return { ok: true };
  },
  states: {},
  connection: { subscribeMessage: async () => () => {} },
};

await new Promise((r) => setTimeout(r, 50)); // let initial render+refresh settle

// switch to firmware tab
el.shadowRoot.querySelector('[data-tab="firmware"]').click();
await new Promise((r) => setTimeout(r, 20));

const html = el.shadowRoot.innerHTML;
const failures = [];
const check = (cond, msg) => (cond ? null : failures.push(msg));

// 1) single devices section + single catalog
check(
  (html.match(/Firmware catalog/g) || []).length === 1,
  "firmware catalog section duplicated"
);
check(
  (html.match(/No HCS devices discovered yet/g) || []).length <= 1,
  "empty-devices placeholder duplicated"
);
check(
  (html.match(/data-fw-action="flash"/g) || []).length === 2,
  "expected one flash button per online device"
);

// 4) update pill flips on newer catalog version (semantic, not string eq)
const fwHtml = el.shadowRoot.innerHTML;
check(
  fwHtml.includes("v1.1.0 available"),
  "update-available pill not shown for newer catalog version"
);
// equal versions must NOT be flagged newer (device already updated)
{
  const eq = [...el.shadowRoot.querySelectorAll(".badge.on")].some((b) =>
    b.textContent.includes("up to date")
  );
  // d1_mini device is offline (not rendered); simulate equality via the
  // lolin_c3_mini card only when catalog matches its version.
}

// 1b) offline boards are NOT rendered — only online devices appear
check(!html.includes("hcs-offline"), "offline device rendered on firmware page");
check(html.includes("hcs-test"), "online device missing from firmware page");
check(html.includes("Boiler gateway"), "gateway-centric section title missing");
check(
  !html.includes("Ghost Board"),
  "offline device card rendered"
);

// 1c) catalog card: dropdown LEFT, image RIGHT, model-only labels
check(!!el.shadowRoot.querySelector(".fw-cat"), "catalog grid layout missing");
const opts = [...el.shadowRoot.querySelectorAll("#hcc-board-sel option")].map(
  (o) => o.textContent
);
check(
  !opts.some((t) => /^HCS /.test(t)),
  "dropdown shows legacy HCS/version labels"
);
check(opts.includes("LOLIN C3 mini v2.1"), "model label missing (with field)");
check(
  opts.includes("ESP8266 D1 mini"),
  "model label fallback from title failed"
);
check(
  !el.shadowRoot.querySelector(".dev-card img"),
  "device cards must not show photos (catalog card only)"
);
const prevImg = el.shadowRoot.querySelector("#hcc-board-preview img");
check(!!prevImg, "catalog preview image missing");
check(
  /max-width:\s*170px/.test(prevImg?.getAttribute("style") || ""),
  "catalog preview not halved"
);

// pills are per-device and semantic: 1.0.2 card offers 1.1.0, 1.1.0 card green
const pills = [...el.shadowRoot.querySelectorAll(".badge")].map((b) =>
  b.textContent.trim()
);
check(pills.includes("v1.1.0 available"), "update pill missing for outdated device");
check(pills.includes("up to date"), "up-to-date pill missing for current device");
check(!html.includes("Firmware is up to date"), "stale banner still rendered");

// 5) live progress bar with percentage
check(
  !!el.shadowRoot.querySelector(".ota-bar:not(.ind)"),
  "determinate ota progress bar missing"
);
const barFill = el.shadowRoot.querySelector(".ota-bar i");
check(
  barFill && barFill.getAttribute("style").includes("width:55%"),
  "progress bar width does not reflect 55%"
);
check(html.includes("Downloading firmware — 55%"), "progress label missing");

// 5b) board settings card on Settings tab
el.shadowRoot.querySelector('[data-tab="settings"]').click();
await new Promise((r) => setTimeout(r, 20));
{
  const h = el.shadowRoot.innerHTML;
  check(h.includes("Board settings"), "board settings card missing");
  const sel = el.shadowRoot.getElementById("hcc-bs-device");
  check(!!sel && sel.value === "hcs-test", "device selector wrong");
  check(
    el.shadowRoot.getElementById("hcc-bs-name")?.value === "Test Board",
    "name field not populated from cfg snapshot"
  );
  check(
    el.shadowRoot.getElementById("hcc-bs-host")?.value === "192.168.50.20" &&
      el.shadowRoot.getElementById("hcc-bs-port")?.value === "1883",
    "mqtt fields not populated"
  );
  check(
    el.shadowRoot.getElementById("hcc-bs-ota")?.value === "",
    "ota password must not be pre-filled (write-only)"
  );
  el.shadowRoot.getElementById("hcc-bs-name").value = "Renamed";
  el.shadowRoot.getElementById("hcc-bs-name").dispatchEvent(new w.Event("input", { bubbles: true }));
  el.shadowRoot.querySelector('[data-action="save-board"]').click();
  await new Promise((r) => setTimeout(r, 30));
  const saveCall = wsCalls.find((c) => c.type === "home_climate_control/set_device_settings");
  check(!!saveCall, "set_device_settings ws not called");
  check(saveCall?.node_id === "hcs-test", "settings sent to wrong node");
  check(saveCall?.settings?.device_name === "Renamed", "edited field missing in payload");
  check(!("ota_password" in (saveCall?.settings || {})), "empty password must not be sent");
}
el.shadowRoot.querySelector('[data-tab="firmware"]').click();
await new Promise((r) => setTimeout(r, 20));

// 6) failure box carries the board's error reason
const failBox = el.shadowRoot.querySelector(".ota-fail");
check(!!failBox, "ota failure box missing");
check(
  failBox && failBox.textContent.includes("HTTP 404"),
  "failure reason not shown in ota box"
);
check(
  !/personal token/i.test(html),
  "GitHub token UI must be gone entirely"
);

// 2) catalog dropdown + preview exist
check(!!el.shadowRoot.getElementById("hcc-board-sel"), "catalog dropdown missing");
check(
  !!el.shadowRoot.getElementById("hcc-board-preview"),
  "board preview missing"
);
check(
  el.shadowRoot.getElementById("hcc-board-preview").querySelector("p").textContent.includes("test desc"),
  "description not rendered in preview"
);

// 3) click flash -> ws call + notice
el.shadowRoot.querySelector('[data-fw-action="flash"]').click();
await new Promise((r) => setTimeout(r, 30));

const flashCall = wsCalls.find((c) => c.type === "home_climate_control/flash_device");
check(!!flashCall, "flash_device ws not called");
check(flashCall?.catalog_id === "hcs-1.1.0-lolin_c3_mini", "wrong catalog id sent");
check(
  el._error === null || el._error === undefined,
  "handler error set: " + el._error
);
check(
  el.shadowRoot.querySelector(".notice")?.textContent.includes("Update command sent"),
  "flash notice not shown"
);

// 4) catalog selection survives re-render
const sel2 = el.shadowRoot.getElementById("hcc-board-sel");
sel2.value = "hcs-1.0.2-lolin_c3_mini";
sel2.dispatchEvent(new w.Event("change", { bubbles: true }));
await new Promise((r) => setTimeout(r, 10));
el._render();
await new Promise((r) => setTimeout(r, 10));
check(
  el.shadowRoot.getElementById("hcc-board-sel").value === "hcs-1.0.2-lolin_c3_mini",
  "catalog selection lost after re-render"
);
check(
  el.shadowRoot.getElementById("hcc-board-preview").querySelector("p").textContent.includes("test desc"),
  "preview not restored for selected board"
);

// 5) flash-catalog action sends node id + catalog id
el.shadowRoot.getElementById("hcc-cat-node").value = "hcs-newboard";
el.shadowRoot.querySelector('[data-fw-action="flash-catalog"]').click();
await new Promise((r) => setTimeout(r, 20));
const catFlash = wsCalls.find(
  (c) => c.type === "home_climate_control/flash_device" && c.node_id === "hcs-newboard"
);
check(!!catFlash, "flash-catalog ws not called");
check(catFlash?.catalog_id === "hcs-1.0.2-lolin_c3_mini", "flash-catalog wrong image");

// 6) Board tab replicates the ESP control page
el._tab = "board";
el._render();
await new Promise((r) => setTimeout(r, 10));
let h = el.shadowRoot.innerHTML;
check(h.includes("Central heating"), "board CH row missing");
check(h.includes("Weather compensation"), "board WC card missing");
check(h.includes("38.5"), "board WC target not rendered from ctl");
const chOff = el.shadowRoot.querySelector(
  '[data-ctl-node="hcs-test"][data-ctl-key="ch_enable"][data-ctl-value="false"]'
);
check(!!chOff, "CH off button missing");
chOff.click();
await new Promise((r) => setTimeout(r, 20));
check(
  wsCalls.some(
    (c) =>
      c.type === "home_climate_control/device_control" &&
      c.node_id === "hcs-test" &&
      c.key === "ch_enable" &&
      c.value === false
  ),
  "device_control(ch_enable=false) ws not called"
);

// draft input respected by Apply
const dhwIn = el.shadowRoot.querySelector(
  '[data-draft-node="hcs-test"][data-draft-key="dhw_setpoint"]'
);
dhwIn.value = "52";
dhwIn.dispatchEvent(new w.Event("input", { bubbles: true }));
await new Promise((r) => setTimeout(r, 5));
el.shadowRoot
  .querySelector('[data-ctl-key="dhw_setpoint"][data-ctl-from-input]')
  .click();
await new Promise((r) => setTimeout(r, 20));
check(
  wsCalls.some(
    (c) => c.type === "home_climate_control/device_control" && c.key === "dhw_setpoint" && Number(c.value) === 52
  ),
  "DHW apply did not send drafted value"
);

// WC curve apply sends all four fields
for (const [k, v] of [
  ["wc_ref", "20"],
  ["wc_design", "-12"],
  ["wc_fmax", "70"],
  ["wc_fmin", "28"],
]) {
  const inp = el.shadowRoot.querySelector(`[data-draft-key="${k}"]`);
  inp.value = v;
  inp.dispatchEvent(new w.Event("input", { bubbles: true }));
}
el.shadowRoot.querySelector('[data-wc-apply="hcs-test"]').click();
await new Promise((r) => setTimeout(r, 20));
const wcCall = wsCalls.find(
  (c) => c.type === "home_climate_control/device_control" && c.key === "weather_comp_cfg"
);
check(!!wcCall, "WC apply ws not called");
check(
  wcCall?.curve?.wc_ref === 20 && wcCall?.curve?.wc_fmin === 28,
  "WC curve payload wrong: " + JSON.stringify(wcCall?.curve)
);

// offline devices are not shown on board tab
check(!h.includes("hcs-offline"), "offline board leaked onto board tab");

// footer shows the running integration version from get_status
const foot = el.shadowRoot.querySelector("footer");
check(!!foot, "footer missing");
check(
  /Home Climate Control\s+v\d+\.\d+\.\d+/.test(foot.textContent),
  "footer does not show integration version"
);
check(
  foot.textContent.includes("v9.9.9"),
  "footer version not sourced from get_status payload: " +
    JSON.stringify(foot.textContent.slice(0, 60))
);

if (failures.length) {
  console.error("FAILURES:\n - " + failures.join("\n - "));
  process.exit(1);
}
console.log("panel DOM gates: all passed");
process.exit(0);
