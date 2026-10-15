const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
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

async function openSettings({account = null, connectors = [], hosts = [], memory = null, session = undefined, models = undefined,
  providers = [], socialAccounts = [], socialApprovals = [],
  permissionRows = ['Claude Code','Codex','OpenCode','BABOOM'].map(actor =>
    ({actor, kind:'agent', read:'Ask', write:'Ask', send:'Ask'}))} = {}) {
  const manifest = JSON.parse(read("nodelang/studio/compiled/manifest.json"));
  for (const source of ["studio-lm.jsx", "studio-account.jsx"]) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash("sha256").update(fs.readFileSync(path.join(root, "nodelang/studio", source))).digest("hex");
    assert.equal(held && held.source_sha256, live, "Studio build is stale for " + source + ": run npm run build:studio");
  }
  const {JSDOM} = await import("jsdom");
  const dom = new JSDOM("<div id=\"root\"></div>", {url:"http://127.0.0.1:53917/", runScripts:"outside-only", pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = url => {
    if (models !== undefined && String(url).startsWith("/api/universal/models")) {
      return Promise.resolve({ok:true, json:async () => JSON.parse(JSON.stringify(models))});
    }
    return new Promise(() => {});
  };
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  if (account) win.localStorage.setItem("archhub.account.v1", JSON.stringify(account));
  const calls = {consent:[], reveal:[], memory:0, modelSelect:[], socialRemovals:[], approvals:[], permissions:[]};
  win.ARCHHUB_AGENT_SELECT = async route => { calls.modelSelect.push(route); return route; };
  if (memory) win.ARCHHUB_LOAD_MEMORY = async () => { calls.memory += 1; return memory(); };
  let consent = {allowed:false, account:""};
  win.ARCHHUB_CLOUD_SESSION = session === "pending" ? () => new Promise(() => {})
     : async () => {
      const held = session || {state:"signed_in", email:"owner@example.com", expires_at:2000000000, founder:false};
      // Both existing account owners read this real session contract.
      return {...held, state:held.state || (held.signed_in ? "signed_in" : "signed_out"),
        signed_in:held.signed_in ?? (held.state === "signed_in")};
    };
  win.ARCHHUB_REVEAL = async what => { calls.reveal.push(what); return {ok:true, opened:"C:/x/" + what}; };
  const listeners = new Set();
  const snapshot = {canvas:null, workshops:[], applicationUpdate:{state:"idle", current_build:"b1"},
    theme:{configuration:{theme:{...seed}, binding_mode:"personal-wip", state:"WIP", history:[], personal_wip_heads:["head-a"],
      baboom_startup:{value:"on", source:"default", revision:null, available:true, control:"c", event_fact_input:"i"}}, pending:false, error:""}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    readProviders:async () => providers.map(row => ({...row})),
    watchApplicationUpdate:() => () => {},
    readCloudPublishConsent:async () => ({...consent}),
    setCloudPublishConsent:async allow => { calls.consent.push(allow); consent = {allowed:allow, account:allow ? "owner@example.com" : ""}; return {...consent}; },
    listLocalSocialAccounts:async () => socialAccounts.map(row => ({...row})),
    removeLocalSocialAccount:async body => { calls.socialRemovals.push({...body}); return {ok:true, ...body, state:"removed"}; },
    listSocialApprovals:async () => socialApprovals.map(row => ({...row})),
    decideSocialApproval:async body => { calls.approvals.push({...body}); return {ok:true, ...body}; },
    readSettingsPermissionRows:async () => permissionRows.map(row => ({...row})),
    setSettingsPermission:async row => { calls.permissions.push({...row}); return {ok:true, ...row}; },
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {}, selectTopology:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[], currentGraph:null, hosts, connectors, graph:{nodes:[], wires:[]},
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
  const {sidebar, tab, labels} = settingsNavigator({doc, flush, settle});
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, sidebar, tab, labels, calls, close};
}

test("Team uses the signed-in account as Owner and draws no fake rows", async () => {
  const s = await openSettings({account:{signedIn:true, email:"o@x.test", name:"Owner"}, session:{signed_in:true, email:"o@x.test"}});
  try {
    const panel = await s.tab("Team");
    assert.match(panel.textContent, /Owner/);
    assert.match(panel.textContent, /o@x\.test/);
    assert.match(panel.textContent, /Members you invite will appear here\./);
    for (const fake of ["Amina", "Karim", "Dina", "seat", "invite a teammate"]) {
      assert.equal(panel.textContent.includes(fake), false, "no fake Team value: " + fake);
    }
    assert.ok([...panel.querySelectorAll("button")].some(button => button.textContent.trim() === "Manage account"));
  } finally { s.close(); }
});

test("Team signed out asks for sign-in through the existing Account route", async () => {
  const s = await openSettings({account:{signedIn:false, email:"", name:""}, session:{signed_in:false}});
  try {
    const panel = await s.tab("Team");
    assert.match(panel.textContent, /Sign in to see your team/);
    const signIn = [...panel.querySelectorAll("button")].find(button => button.textContent.trim() === "Sign in");
    assert.ok(signIn, "Team has a real sign-in control");
    s.flush(() => signIn.click());
    await s.settle();
    assert.match(panel.parentElement.textContent, /Account/);
  } finally { s.close(); }
});

test("Permissions renders only rows backed by stores and its controls call existing endpoints", async () => {
  const s = await openSettings({
    account:{signedIn:true, email:"o@x.test", name:"Owner"},
    session:{signed_in:true, email:"o@x.test"},
    hosts:[{id:"h1", name:"Rhino", state:"connected", detail:"ready"}],
    connectors:[{id:"c1", name:"Rhino"}],
    socialAccounts:[{provider:"linkedin", account_id:"li-a", vault_entry:"social-li-a", account_binding:"provider-verified"}],
    socialApprovals:[{delegation:"d1", input_digest:"dg1", operation:"linkedin.post", account_id:"li-a", review_text:"post"}],
  });
  try {
    const panel = await s.tab("Permissions");
    for (const row of ["Claude Code", "Codex", "OpenCode", "BABOOM"]) assert.ok(panel.textContent.includes(row), row + " row is backed and rendered");
    assert.equal(panel.textContent.includes("File system"), false, "unbacked rows are omitted");
    const allow = panel.querySelector("[data-permission-col=\"Write\"] [data-seg-control] button:nth-child(2)");
    assert.ok(allow, "permission row has the existing segmented write control");
    s.flush(() => allow.click());
    await s.settle();
    assert.ok(s.calls.permissions.length >= 1);
  } finally { s.close(); }
});

test("Every Settings section has a working control and no stub words", async () => {
  const s = await openSettings({
    account:{signedIn:true, email:"o@x.test", name:"Owner"},
    session:{signed_in:true, state:"signed_in", email:"o@x.test"},
    hosts:[{id:"h1", name:"Rhino", state:"connected", detail:"ready"}],
    connectors:[{id:"c1", name:"Rhino"}],
    providers:[{id:"cloud", name:"ArchHub cloud", state:"no key", source:"", sets:""}],
    models:{ok:true, groups:[{name:"Local", items:[{name:"Local model", route:"ollama/m", routed:"ollama/m", vendor:"Ollama", tag:"LOCAL"}]}], selected_route:""},
    socialAccounts:[{provider:"linkedin", account_id:"li-a", vault_entry:"social-li-a", account_binding:"provider-verified"}],
    socialApprovals:[{delegation:"d1", input_digest:"dg1", operation:"linkedin.post", account_id:"li-a", review_text:"post"}],
  });
  try {
    const labels = s.labels;
    for (const label of labels) {
      const panel = await s.tab(label);
      assert.equal(/coming soon|not available yet|placeholder|stub/i.test(panel.textContent), false, label + " has no stub words");
      const controls = panel.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [role=\"button\"]:not([disabled]), [role=\"switch\"]:not([disabled])");
      assert.ok(controls.length >= 1, label + " has at least one working control");
    }
  } finally { s.close(); }
});

test("Permissions and Hosts draw no switch that nothing reads", async () => {
  const s = await openSettings();
  try {
    const perms = await s.tab("Permissions");
    const labels = [...perms.querySelectorAll("button")].map(b => b.textContent.trim());
    for (const mode of ["AUTO", "ASK", "BLOCK"]) assert.equal(labels.includes(mode), false, "no " + mode + " switch");
    assert.match(perms.textContent, /Writes always ask unless you allow them/);
    assert.equal(/Cost ceiling per session|Auto-undo window/.test(perms.textContent), false, "no invented ceiling or undo window");
    const hosts = await s.tab("Hosts");
    const switches = [...hosts.querySelectorAll("[role=\"switch\"]")].map(node => node.getAttribute("aria-label") || node.getAttribute("title"));
    assert.deepEqual(switches, [], "Hosts draws no switch: BABOOM startup lives only in Settings > BABOOM");
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
    assert.equal(panel.textContent.includes("Model spend is not measured"), false, "spend paragraph is not shown");
    assert.match(panel.textContent, /Brain accessLOCALPrivate on this machine/);
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

test("Model routing shows only real routed jobs; the select saves the free reasoning model", async () => {
  const freeRoute = "qwen/qwen3.8-27b:free";
  const s = await openSettings({models:{ok:true, groups:[{name:"BYO · OpenRouter", items:[
    {name:"Qwen free", route:freeRoute, routed:freeRoute, vendor:"qwen", tag:"BYO", cost:"$0 / $0 per M"},
    {name:"Paid model", route:"openrouter/openai/gpt-paid", routed:"openrouter/openai/gpt-paid", vendor:"openai", tag:"BYO", cost:"$1 / $1 per M"},
    {name:"Local model", route:"ollama/llama3", routed:"ollama/llama3", vendor:"Ollama", tag:"LOCAL", cost:"free · local"},
  ]}], selected_route:""}});
  try {
    const models = await s.tab("Models");
    const select = models.querySelector('select[aria-label="Reasoning model"]');
    assert.ok(select, "Reasoning is a real select");
    assert.equal(models.textContent.includes("Vision · sketch parsing"), false, "unrouted Vision row is not drawn");
    assert.equal(models.textContent.includes("Long context"), false, "unrouted Long context row is not drawn");
    assert.equal(models.textContent.includes("Fast bulk"), false, "unrouted Fast bulk row is not drawn");
    assert.equal(models.textContent.includes("Embedding"), false, "unrouted Embedding row is not drawn");
    assert.match(models.textContent, /Other jobs use the reasoning model\./);
    assert.equal([...select.options].some(option => option.value === "openrouter/openai/gpt-paid"), false, "paid model is not offered");
    select.value = freeRoute;
    s.flush(() => select.dispatchEvent(new s.win.Event("change", {bubbles:true})));
    await s.settle();
    assert.deepEqual(s.calls.modelSelect, [freeRoute], "select saves through the existing composer-model path");
  } finally { s.close(); }
});

test("Shortcuts lists only keys that have a handler, and they act", async () => {
  const s = await openSettings();
  try {
    const sheet = await s.tab("Shortcuts");
    const keys = [...sheet.querySelectorAll("kbd")].map(k => k.textContent);
    for (const unbound of ["⌘N", "⌘↵", "⌥B", "⌘⇧S", "⌘M", "⌥R"]) {
      assert.equal(keys.includes(unbound), false, unbound + " has no handler in this build");
    }
    assert.ok(keys.includes("Ctrl/Cmd+,") && keys.includes("Ctrl/Cmd+/") && keys.includes("Ctrl/Cmd+K"), "Ctrl/Cmd+K opens the command bar");
    const before = !!s.doc.querySelector("[title=\"Settings\"]") && !!s.doc.querySelector("[data-settings54-shell]");
    assert.equal(before, true);
    s.flush(() => s.win.dispatchEvent(new s.win.KeyboardEvent("keydown", {key:",", ctrlKey:true, bubbles:true})));
    await s.settle();
    assert.equal(!!s.doc.querySelector("[data-settings54-shell]"), false,
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
    // DP-CLOUD: the design identity row names the account the cloud record holds (page storage has no email).
    assert.match(panel.textContent, /Signed in as owner@example\.com/);
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
