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
  systems: [{ entry_id: "e1", update_info: { available: false } }],
  devices: [
    {
      node_id: "hcs-test",
      name: "Test Board",
      board: "lolin_c3_mini",
      version: "1.0.0",
      online: true,
      ip: "1.2.3.4",
    },
    {
      node_id: "hcs-offline",
      name: "Ghost Board",
      board: "d1_mini",
      version: "1.0.0",
      online: false,
      ip: "5.6.7.8",
    },
  ],
  firmware_catalog: [
    {
      id: "hcs-1.0.2-lolin_c3_mini",
      title: "HCS 1.0.2 — LOLIN C3 mini",
      board: "lolin_c3_mini",
      version: "1.0.2",
      url: "https://example.com/fw.bin",
      description: "test desc",
      image: "/home_climate_control_static/boards/lolin_c3_mini.svg",
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
  (html.match(/data-fw-action="flash"/g) || []).length === 1,
  "expected exactly one flash button"
);

// 1b) offline boards are NOT rendered — only online devices appear
check(!html.includes("hcs-offline"), "offline device rendered on firmware page");
check(html.includes("hcs-test"), "online device missing from firmware page");
check(
  !html.includes("Ghost Board"),
  "offline device card rendered"
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
check(flashCall?.catalog_id === "hcs-1.0.2-lolin_c3_mini", "wrong catalog id sent");
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
sel2.dispatchEvent(new w.Event("change"));
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

if (failures.length) {
  console.error("FAILURES:\n - " + failures.join("\n - "));
  process.exit(1);
}
console.log("panel DOM gates: all passed");
process.exit(0);
