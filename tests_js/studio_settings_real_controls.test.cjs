/* Court (lane baboom-settings, 2026-09-24): every enabled Settings control reads and writes one
   source its effect uses, or it is not drawn. Before this lane the Permissions switches, the
   per-host switches, the HARD CAP buttons and "Choose sync folder" wrote this page's localStorage
   and nothing read them; Profile drew invented dropdowns; Storage's destructive rows only opened
   a folder; the Shortcuts sheet listed keys with no handler; there was no way to grant the cloud
   publish consent start_cloud_relay reads. Real browser DOM in memory; no server or network. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {createHash} = require("node:crypto");
const root = path.resolve(__dirname, "..");
const read = name => fs.readFileSync(path.join(root, name), "utf8");
const seedText = read("nodelang/universal_presentation_seed.py").match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function openSettings({account = null, connectors = [], memory = null, session = undefined} = {}) {
  const manifest = JSON.parse(read("nodelang/studio/compiled/manifest.json"));
  for (const source of ["studio-lm.jsx", "studio-account.jsx"]) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash("sha256").update(fs.readFileSync(path.join(root, "nodelang/studio", source))).digest("hex");
    assert.equal(held && held.source_sha256, live, "Studio build is stale for " + source + ": run npm run build:studio");
  }
  const {JSDOM} = await import("jsdom");
  const dom = new JSDOM("<div id=\"root\"></div>", {url:"http://127.0.0.1:53917/", runScripts:"outside-only", pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  if (account) win.localStorage.setItem("archhub.account.v1", JSON.stringify(account));
  const calls = {consent:[], reveal:[], memory:0};
  if (memory) win.ARCHHUB_LOAD_MEMORY = async () => { calls.memory += 1; return memory(); };
  let consent = {allowed:false, account:""};
  win.ARCHHUB_CLOUD_SESSION = session === "pending" ? () => new Promise(() => {})
    : async () => (session || {state:"signed_in", email:"owner@example.com", expires_at:2000000000, founder:false});
  win.ARCHHUB_REVEAL = async what => { calls.reveal.push(what); return {ok:true, opened:"C:/x/" + what}; };
  const listeners = new Set();
  const snapshot = {canvas:null, workshops:[], applicationUpdate:{state:"idle", current_build:"b1"},
    theme:{configuration:{theme:{...seed}, binding_mode:"personal-wip", state:"WIP", history:[], personal_wip_heads:["head-a"],
      baboom_startup:{value:"on", source:"default", revision:null, available:true, control:"c", event_fact_input:"i"}}, pending:false, error:""}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    readProviders:async () => [],
    watchApplicationUpdate:() => () => {},
    readCloudPublishConsent:async () => ({...consent}),
    setCloudPublishConsent:async allow => { calls.consent.push(allow); consent = {allowed:allow, account:allow ? "owner@example.com" : ""}; return {...consent}; },
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {}, selectTopology:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts:[], connectors, graph:{nodes:[], wires:[]},
    memory:[{id:"m1", text:"Real fact read from the brain.", src:"folder"}], skills:[]};
  win.eval(read("nodelang/studio/vendor/react.js"));
  win.eval(read("nodelang/studio/vendor/react-dom.js"));
  for (const file of manifest.files) {
    if (file.source !== "mount.jsx") win.eval(read("nodelang/studio/compiled/" + file.output));
  }
  win.eval("window.__studioRoot=ReactDOM.createRoot(document.getElementById(\"root\")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));");
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise(resolve => win.setTimeout(resolve, 0)); };
  const opener = doc.querySelector("[title=\"Settings\"]");
  assert.ok(opener, "actual Studio Settings control exists");
  flush(() => opener.click());
  await settle();
  const anchor = [...doc.querySelectorAll("button")].find(button => button.firstElementChild?.textContent === "Theme");
  const sidebar = anchor.parentElement;
  const tab = async label => {
    const button = [...sidebar.children].find(child => child.firstElementChild?.textContent === label);
    assert.ok(button, "the sidebar has the " + label + " tab");
    flush(() => button.click());
    await settle();
    return sidebar.nextElementSibling;
  };
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, tab, calls, close};
}

test("Permissions and Hosts draw no switch that nothing reads", async () => {
  const s = await openSettings();
  try {
    const perms = await s.tab("Permissions");
    const labels = [...perms.querySelectorAll("button")].map(b => b.textContent.trim());
    for (const mode of ["AUTO", "ASK", "BLOCK"]) assert.equal(labels.includes(mode), false, "no " + mode + " switch");
    assert.match(perms.textContent, /run only inside a Workshop workflow you approved/);
    assert.equal(/Cost ceiling per session|Auto-undo window/.test(perms.textContent), false, "no invented ceiling or undo window");
    const hosts = await s.tab("Hosts");
    const switches = [...hosts.querySelectorAll("[role=\"switch\"]")].map(node => node.getAttribute("aria-label") || node.getAttribute("title"));
    assert.deepEqual(switches, ["Start BABOOM when ArchHub opens"], "the only Hosts switch is the graph-held BABOOM startup");
    assert.equal(hosts.textContent.includes("Auto-build a new host connector"), false, "no button without a handler");
    assert.equal(hosts.textContent.includes("Toggle off to remove from the graph"), false);
  } finally { s.close(); }
});

test("Account: cloud publish consent is a real control; no cap, meter or sync folder nobody reads", async () => {
  const s = await openSettings({account:{signedIn:true, email:"owner@example.com", name:"Owner"}});
  try {
    const panel = await s.tab("Account");
    for (const gone of ["HARD CAP", "runs stop at the cap", "THIS CYCLE", "Choose sync folder", "~/ArchHub/brain"]) {
      assert.equal(panel.textContent.includes(gone), false, "no " + gone);
    }
    assert.match(panel.textContent, /Model spend is not measured on this machine and no spend cap is enforced\./);
    const consent = panel.querySelector("[role=\"switch\"][aria-label=\"Publish this machine map to the cloud\"]");
    assert.ok(consent, "the consent switch is drawn");
    assert.equal(consent.getAttribute("aria-checked"), "false");
    assert.match(panel.textContent, /Nothing leaves this machine/);
    s.flush(() => consent.click());
    await s.settle();
    assert.deepEqual(s.calls.consent, [true], "the switch writes the consent record through the app");
    assert.equal(consent.getAttribute("aria-checked"), "true", "the switch states what the record now holds");
    assert.match(panel.textContent, /Allowed for owner@example\.com/);
    s.flush(() => consent.click());
    await s.settle();
    assert.deepEqual(s.calls.consent, [true, false], "withdrawing is the same control");
  } finally { s.close(); }
});

test("Profile, Models, Theme, Brain and Storage carry no inert dropdown or mislabelled action", async () => {
  const s = await openSettings();
  try {
    const profile = await s.tab("Profile");
    for (const invented of ["Cairo (UTC+2)", "ISO 128", "Millimeters (mm)", "Project lead", "English, Arabic", "▾"]) {
      assert.equal(profile.textContent.includes(invented), false, "Profile draws no invented " + invented);
    }
    const models = await s.tab("Models");
    assert.equal(models.querySelectorAll("button[disabled]").length, 0, "no disabled dropdowns");
    assert.equal(models.textContent.includes("▾"), false);
    const theme = await s.tab("Theme");
    const changes = [...theme.querySelectorAll("span, button, [role=\"button\"]")].filter(n => n.textContent.trim() === "change");
    assert.equal(changes.length, 1, "only the accent row change, which opens the saved-theme editor");
    const brain = await s.tab("Brain");
    for (const inert of ["restore all", "show recovery kit", "rotate login"]) {
      assert.equal([...brain.querySelectorAll("button")].some(b => b.textContent.trim() === inert), false, "no " + inert);
    }
    const storage = await s.tab("Storage");
    const labels = [...storage.querySelectorAll("button")].map(b => b.textContent.trim());
    assert.equal(labels.includes("do it"), false, "no destructive label on a reveal");
    assert.deepEqual(labels, ["open folder", "open folder"]);
    s.flush(() => storage.querySelectorAll("button")[0].click());
    await s.settle();
    assert.deepEqual(s.calls.reveal, ["graph"], "the row opens the folder it names");
  } finally { s.close(); }
});

test("Shortcuts lists only keys that have a handler, and they act", async () => {
  const s = await openSettings();
  try {
    const sheet = await s.tab("Shortcuts");
    const keys = [...sheet.querySelectorAll("kbd")].map(k => k.textContent);
    for (const unbound of ["⌘K", "⌘N", "⌘↵", "⌥B", "⌘⇧S", "⌘M", "⌥R"]) {
      assert.equal(keys.includes(unbound), false, unbound + " has no handler in this build");
    }
    assert.ok(keys.includes("⌘,") && keys.includes("⌘/"));
    const before = !!s.doc.querySelector("[title=\"Settings\"]") && [...s.doc.querySelectorAll("button")].some(b => b.firstElementChild?.textContent === "Theme");
    assert.equal(before, true);
    s.flush(() => s.win.dispatchEvent(new s.win.KeyboardEvent("keydown", {key:",", ctrlKey:true, bubbles:true})));
    await s.settle();
    assert.equal([...s.doc.querySelectorAll("button")].some(b => b.firstElementChild?.textContent === "Theme"), false,
      "Ctrl+, closes Settings: the listed key acts");
  } finally { s.close(); }
});

test("Sign-up lists the hosts the probe answered, never a fixed FOUND list", async () => {
  const account = read("nodelang/studio/studio-account.jsx");
  assert.equal(/Revit 2025|Rhino 8|AutoCAD 2024/.test(account), false, "no fixed host list");
  assert.equal(account.includes("Prefers dimensions on exterior walls first."), false, "no invented brain fact");
  assert.match(account, /window\.ARCHHUB_LIVE\.connectors/);
});

test("Account identity never says Not signed in before or without the sign-in record's answer", async () => {
  // cloud.json is signed in, but /api/universal/cloud-session is still asking the cloud (up to 5 s).
  const s = await openSettings({account:{signedIn:false, email:"", name:"Owner"}, session:"pending"});
  try {
    const panel = await s.tab("Account");
    assert.equal(panel.textContent.includes("Not signed in"), false, "no verdict before the record answers");
    assert.match(panel.textContent, /Reading the sign-in/);
  } finally { s.close(); }
  const t = await openSettings({account:{signedIn:true, email:"owner@example.com", name:"Owner"},
    session:{ok:false, error:"the app did not answer"}});
  try {
    const panel = await t.tab("Account");
    assert.equal(panel.textContent.includes("Not signed in"), false, "an unanswered read is not a sign-out");
    assert.match(panel.textContent, /Sign-in state unavailable/);
  } finally { t.close(); }
});

test("Account identity follows the one sign-in record, not this page's storage", async () => {
  // Page storage says signed out; cloud.json (via /api/universal/cloud-session) says signed in.
  const s = await openSettings({account:{signedIn:false, email:"", name:"Owner"}});
  try {
    const panel = await s.tab("Account");
    assert.equal(panel.textContent.includes("Not signed in"), false, panel.textContent.slice(0, 200));
    assert.match(panel.textContent, /Owner\s*owner@example\.com/);
    assert.ok([...panel.querySelectorAll("button")].some(b => b.textContent.trim() === "Sign out"));
  } finally { s.close(); }
});

test("Settings opens without asking the brain; the Brain tab reads it and says when it is not answering", async () => {
  const s = await openSettings({memory: () => Promise.reject(new Error("Brain not answering"))});
  try {
    assert.equal(s.calls.memory, 0, "opening Settings does not wait on the brain");
    const brain = await s.tab("Brain");
    await s.settle();
    assert.equal(s.calls.memory, 1, "the Brain tab reads the brain");
    assert.match(brain.textContent, /Brain not answering\. Nothing here is lost/);
  } finally { s.close(); }
});
