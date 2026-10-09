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
  for (const label of ["Editor font", "Display font", "Density"]) {
    assert.match(theme, new RegExp("<select aria-label=\"" + label + "\"[\\s\\S]*onChange=\\{e => applyAppearance"));
  }
  assert.match(theme, /<input aria-label="Choose accent colour" type="color"/);
  assert.equal(theme.includes("Save accent"), false, "accent applies from the swatch flow, not a form save");
});

test("W6 social accounts expose OAuth buttons, never raw access-token enrollment", () => {
  const social = slice("const SettingsSocialEnrollment = ", "// The design's per-row");
  const meta = slice("const SettingsMetaSignIn = ", "const SettingsSocialEnrollment = ");
  const transport = fs.readFileSync(path.join(root, "nodelang/studio/studio-existing-workshop.js"), "utf8");
  assert.match(source, /Connect LinkedIn/);
  assert.match(source, /Connect Facebook \/ Instagram/);
  assert.match(meta, /saveMetaApp/);
  assert.match(meta, /startMetaSignIn/);
  assert.match(meta, /metaSignInStatus/);
  assert.match(meta, /finishMetaSignIn/);
  assert.match(meta, /Use \{page\.name \|\| page\.id\}/);
  assert.match(meta, /\+ Instagram @/);
  assert.match(meta, /removeLocalSocialAccount/);
  assert.match(transport, /social-meta-app/);
  assert.match(transport, /social-meta-signin/);
  assert.match(transport, /social-meta-finish/);
  assert.match(transport, /post\('\/api\/universal\/social-meta-finish', \{page_id\}\)/);
  for (const dead of ["ACCESS TOKEN", "REFERENCE NAME", "Save account", "removeLocalSocialAccount", "enrollSocialAccount"]) {
    assert.equal(social.includes(dead), false, dead + " is not shown in the user flow");
  }
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
  const shell = slice("const IconRail = ", "const RailIcon = ");
  assert.equal(shell.includes("Share · not available"), false);
  const chats = slice("const ChatsPanel = ", "const NodesPanel = ");
  assert.equal(/<button title="More"[^>]*>/.test(chats), false);
  const skills = slice("const SkillsPanel = ", "const SearchPanel = ");
  assert.equal(/<button title="New skill"[^>]*>/.test(skills), false);
  const header = slice("const WsHeader = ", "const WsTab = ");
  assert.equal(header.includes(">fork<"), false);
  assert.equal(header.includes(">save as skill<"), false);
});

test("W6b Settings renders no developer-only capability or no-wire host prose", () => {
  const hosts = slice("const SettingsHosts = ", "// ──────────────────────── MODEL PICKER");
  const operations = slice("const SettingsOperations = ", "// -- Workspaces:");
  for (const dead of ["COURT", "UNAVAILABLE", "PROVEN BY A COURT", "courts do not"]) {
    assert.equal(hosts.includes(dead) || operations.includes(dead), false, dead + " must not reach Settings");
  }
  assert.match(operations, /tests_replica\|court/);
  assert.match(hosts, /no wire in this build/i);
  assert.match(operations, /Ready/);
  assert.match(operations, /Needs /);
  assert.match(hosts, /visibleHosts = LM_HOSTS\.filter/);
});

test("W6b Settings has no global disabled edit or dash-grid Team placeholders", () => {
  const chat = slice("const ChatView = ", "const ChatTurn = ");
  assert.equal(chat.includes(">edit</button>"), false, "system prompt edit is removed until it has a handler");
  const team = slice("const SettingsTeam = ", "// ── Profile:");
  for (const placeholder of ["FIRM", "SEATS", "USED", "YOUR ROLE", "\\u2014"]) {
    assert.equal(team.includes(placeholder), false, placeholder + " placeholder is not rendered");
  }
  assert.match(team, /No firm in this connection/);
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
  assert.equal(identityBranch.includes("SINCE"), true, "signed-in identity still carries its since label");
  const workspaces = slice("const SettingsWorkspaces = ", "const SettingsHosts = ");
  assert.match(workspaces, /\{ready && <button[\s\S]*>Add<\/button>\}/);
  assert.match(workspaces, /Workspaces are added in Settings > Workspaces after the workspace registry check passes/);
  const addForm = workspaces.slice(workspaces.indexOf("{ready && <button"), workspaces.indexOf("</button>}", workspaces.indexOf("{ready && <button")));
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
  for (const safe of ["Sign in to use ArchHub cloud", "Key invalid. Paste a real key in Settings", "Local runtime is running"]) {
    assert.match(providerHelpers, new RegExp(safe.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.equal(/no key \\u00b7 set|ARCHHUB_CLOUD_TOKEN|127\.0\.0\.1|localhost:/.test(providers), false);
  assert.match(hosts, /hostDetail\(h\)/);
  assert.match(hosts, /Start<\/button>/);
  for (const safe of ["Start 3ds Max from ArchHub when needed", "Start Rhino from ArchHub when needed", "Start Blender from ArchHub when needed", "Manager not found"]) {
    assert.match(source, new RegExp(safe.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});
