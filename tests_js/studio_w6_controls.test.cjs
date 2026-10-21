const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "nodelang/studio/studio-lm.jsx"), "utf8");

function slice(open, close) {
  const start = source.indexOf(open);
  const end = source.indexOf(close, start + open.length);
  assert.ok(start >= 0 && end > start, "source slice starts at " + open);
  return source.slice(start, end);
}

test("W6 Settings Theme rows are real pickers and instant accent controls", () => {
  const theme = slice("const SettingsTheme = ", "const SettingsShortcuts = ");
  // The b16 baseline already delegates application cells to their real parameter
  // owner; the former hand-written font/density select markup was retired.
  assert.match(theme, /const projection = useStudioProjection\(\)/);
  assert.match(theme, /node\.application[\s\S]*row\.k === 'accent' && row\.editable === true/);
  assert.match(theme, /<window\.ApplicationNodeParameters node=\{node\}\/>/);
  assert.match(theme, /: <SettingsPersonalTheme\/>/);
  assert.match(theme, /<input aria-label="Choose accent colour" type="color"/);
  assert.match(theme, /onChange=\{event => \{setAccent\(event\.target\.value\); setDirty\(true\);\}\}/);
  assert.match(theme, /onClick=\{\(\) => run\(\(\) => api\.previewThemeToken\('accent', accent\), true\)\}/);
  assert.match(theme, /Apply accent/);
  assert.equal(theme.includes("Save accent"), false, "accent applies from the swatch flow, not a form save");
});

test("W6 social accounts expose OAuth buttons, never raw access-token enrollment", async () => {
  const {mount,providers,names} = require('./social3_surface_helpers.cjs');
  const s = await mount();
  try {
    assert.equal(s.doc.querySelectorAll('[data-social-provider]').length,6,'one row per supported social network');
    for(const [i,provider] of providers.entries()) {
      const row=s.doc.querySelector(`[data-social-provider="${provider}"]`);
      assert.ok(row.textContent.includes(names[i]));
      await s.click(row.querySelector('button'));
      assert.match(row.textContent,/Connected as @founder/,'provider callback identity is visible');
    }
    assert.deepEqual(s.calls.start,providers,'each OAuth button invokes the existing broker');
    assert.deepEqual(s.calls.finish.map(row=>row[0]),providers,'each callback completes through the existing custody owner');
    assert.equal(s.doc.querySelectorAll('input,textarea,select').length,0,'no keys, tokens, IDs or enrollment fields');
    for(const dead of ['ACCESS TOKEN','REFERENCE NAME','Save account']) assert.equal(s.doc.body.textContent.includes(dead),false);
  } finally {s.close();}
});
test("W6 Providers OpenCode can be selected as local chat route", () => {
  const manage = slice("const ProviderManage = ", "const SettingsProviders = ");
  assert.match(manage, /p\.id === 'opencode'/);
  assert.match(manage, /Use OpenCode/);
  assert.match(manage, /local-cli\/opencode/);
  assert.equal(manage.includes("127.0.0.1:4096"), false);
  assert.equal(manage.includes("Open OpenCode"), false);
  assert.equal(manage.includes("installed but not routed"), false);
});

test("W6 no visible button is left without an action in the swept shell areas", () => {
  const shell = slice("const Frame = ", "const isHistoryNode = ");
  assert.equal(shell.includes("Share · not available"), false);
  const chats = slice("const ChatsPanel = ", "const NodesPanel = ");
  assert.equal(/<(?:button|window\.AH_DS\.Btn) title="More"[^>]*>/.test(chats), false);
  const skills = slice("const SkillsPanel = ", "const SearchPanel = ");
  assert.equal(/<(?:button|window\.AH_DS\.Btn) title="New skill"[^>]*>/.test(skills), false);
  const header = slice("const WsHeader = ", "const WsTab = ");
  assert.equal(header.includes(">fork<"), false);
  assert.equal(header.includes(">save as skill<"), false);
});

test("W6b Settings renders no developer-only capability or no-wire host prose", () => {
  const hosts = slice("const SettingsHosts = ", "// ──────────────────────── MODEL PICKER");
  const hostCatalogue = slice("const hostCatalogueRows = ", "const hostTally = ");
  const operations = slice("const SettingsOperations = ", "// -- Workspaces:");
  for (const dead of ["COURT", "UNAVAILABLE", "PROVEN BY A COURT", "courts do not"]) {
    assert.equal(hosts.includes(dead) || operations.includes(dead), false, dead + " must not reach Settings");
  }
  assert.match(operations, /tests_replica\|court/);
  const rows = [
    {id:'wired', drive:'host.read', state:'off', detail:'not running'},
    {id:'unwired', drive:'', detail:'no wire in this build'},
    {id:'absent', drive:'', detail:'not found on this machine'},
    {id:'needs-key', drive:'', detail:'add a token to connect'},
    {id:'listening', drive:'', detail:'answering on :9999'},
    {id:'legacy-visible', detail:'installed'},
    {id:'legacy-unwired', detail:'no wire in this build'},
  ];
  const visible = new Function('window', 'LM_HOSTS', hostCatalogue + '\nreturn hostCatalogueRows();')(
    {ARCHHUB_HOSTS_READ:true}, rows);
  assert.deepEqual(visible.map(row => row.id), ['wired', 'legacy-visible'],
    'Settings hides every explicitly unwired probe state and retains the legacy no-wire filter');
  assert.equal(rows.length, 7, 'display filtering does not delete probe evidence');
  assert.match(operations, /Ready/);
  assert.match(operations, /Needs /);
  assert.match(hosts, /const visibleHosts = LM_HOSTS;/);
  assert.match(hosts, /const tally = hostTally\(\)/, 'Hosts uses the same admitted total as every other view');
});

test("W6b Settings has no global disabled edit or dash-grid Team placeholders", () => {
  const chat = slice("const ChatView = ", "const ChatTurn = ");
  assert.equal(/>edit<\/(?:button|window\.AH_DS\.Btn)>/.test(chat), false, "system prompt edit is removed until it has a handler");
  const team = slice("const SettingsTeam = ", "// ── Profile:");
  for (const placeholder of ["FIRM", "SEATS", "USED", "YOUR ROLE", "\\u2014"]) {
    assert.equal(team.includes(placeholder), false, placeholder + " placeholder is not rendered");
  }
  // b16 already shows the signed-in owner rather than an invented invitation roster.
  assert.match(team, /const signedIn = !!account\?\.signedIn/);
  assert.match(team, /Sign in to see your team/);
  assert.match(team, /\{signedIn && <div[\s\S]*\{name \|\| email\}[\s\S]*>Owner<\/span>/);
  assert.match(team, /onClick=\{onAccount\}[\s\S]*>Manage account<\/window\.AH_DS\.Btn>/);
});

test("W6b Account and Workspaces hide or explain disabled crawl targets", () => {
  const account = fs.readFileSync(path.join(root, "nodelang/studio/studio-account.jsx"), "utf8");
  const consent = account.slice(account.indexOf("function CloudPublishConsent"), account.indexOf("function SettingsAccount"));
  assert.match(consent, /canShowControl/);
  assert.match(consent, /if \(!canShowControl\) return null/);
  const accountPanel = account.slice(account.indexOf("function SettingsAccount"), account.indexOf("// ────────────────────────", account.indexOf("function SettingsAccount")));
  assert.match(accountPanel, /const signedOut = !!session && session\.state === 'signed_out'/);
  assert.match(accountPanel, /!\s*signedOut && \(/);
  const identityBranch = accountPanel.slice(accountPanel.indexOf("{!signedOut && ("), accountPanel.indexOf("{/* the one sign-in", accountPanel.indexOf("{!signedOut && (")));
  assert.equal(identityBranch.includes("Not signed in"), false, "signed-out Account has no duplicate identity card");
  assert.equal(identityBranch.includes("Signed in as "), true, "signed-in identity row names the account (design #cloud)");
  const workspaces = slice("const SettingsWorkspaces = ", "const SettingsHosts = ");
  assert.match(workspaces, /\{ready && <window\.AH_DS\.Btn[\s\S]*onClick=\{add\}[\s\S]*>Add<\/window\.AH_DS\.Btn>\}/);
  assert.match(workspaces, /Workspaces are added in Settings > Workspaces after the workspace registry check passes/);
  const addForm = workspaces.slice(workspaces.indexOf("{ready && <window.AH_DS.Btn"), workspaces.indexOf("</window.AH_DS.Btn>}", workspaces.indexOf("{ready && <window.AH_DS.Btn")));
  assert.match(addForm, /title=\{!path\.trim\(\) \? 'Choose a folder first'/);
});

test("W6d Settings detail strings are product-safe and short", () => {
  const account = fs.readFileSync(path.join(root, "nodelang/studio/studio-account.jsx"), "utf8");
  const providerManage = slice("const ProviderManage = ", "const SettingsProviders = ");
  const providerHelpers = slice("const KEY_LABEL = ", "// Posts waiting for the founder");
  const providers = slice("const SettingsProviders = ", "// ── Models:");
  const hosts = slice("const SettingsHosts = ", "// ──────────────────────── MODEL PICKER");
  assert.match(account, /if \(!canShowControl\) return null/);
  assert.equal((account.match(/Not signed in/g) || []).length <= 3, true, "signed-out Account should state sign-in status once in the rendered flow");
  assert.match(account, /Sharing needs approval and never includes client folders\./);
  assert.match(providers, /providerDetail\(p\)/);
  for (const safe of ["Sign in to use ArchHub cloud", "Not reachable from this machine \\u00b7 check the key in Manage", "Connected on this machine"]) {
    assert.match(providerHelpers, new RegExp(safe.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.equal(/no key \\u00b7 set|ARCHHUB_CLOUD_TOKEN|127\.0\.0\.1|localhost:/.test(providers), false);
  assert.match(hosts, /hostDetail\(h\)/);
  assert.match(hosts, /onClick=\{e => startHost\(h, e\.currentTarget\)\}[\s\S]*Start<\/window\.AH_DS\.Btn>/);
  for (const safe of ["Start 3ds Max from ArchHub when needed", "Start Rhino from ArchHub when needed", "Start Blender from ArchHub when needed", "Manager not found"]) {
    assert.match(source, new RegExp(safe.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});
