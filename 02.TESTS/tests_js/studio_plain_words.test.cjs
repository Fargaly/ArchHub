const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..", '..');
const source = fs.readFileSync(path.join(root, "01.APP/nodelang/studio/studio-lm.jsx"), "utf8");

function slice(open, close) {
  const start = source.indexOf(open);
  const end = source.indexOf(close, start + open.length);
  assert.ok(start >= 0 && end > start, "source slice starts at " + open);
  return source.slice(start, end);
}

test("a: first screen and Studio shell never expose internal host-probe or unknown text", () => {
  const visibleShell = slice("const Home = ", "const Workspace = ");
  assert.doesNotMatch(visibleShell, /host probe is still running/i);
  assert.doesNotMatch(visibleShell, />[^<]*\bunknown\b[^<]*</i);
});

test("p: Chat no-model state uses the existing account chip instead of rendering a duplicate account block", () => {
  const chat = slice("const ChatView = ", "// \u2500\u2500\u2500 Calm inference inspector");
  assert.match(chat, /onAccount/);
  assert.doesNotMatch(chat, /window\.CloudSignIn|Continue with Google/);
  assert.doesNotMatch(chat, /setSigningIn|signingIn/);
});

test("t: host state wording comes from one plain vocabulary shared by Connectors, Settings Hosts and Hub cards", () => {
  const vocabulary = slice("const HOST_STATE_WORD = ", "const providerStateWord = ");
  for (const word of ["Connected", "Not running", "Not installed", "Checking"]) {
    assert.match(vocabulary, new RegExp("'" + word + "'"));
  }
  for (const surface of [
    slice("const chatConnectors = ", "// \u2500\u2500\u2500 Calm chat view"),
    slice("const hostDetail = ", "const ModelPicker = "),
    slice("const toolRowsFromOwners = ", "const ToolOffPanel = "),
  ]) {
    assert.match(surface, /hostStateWord/);
    assert.doesNotMatch(surface, />\{state\}</);
    assert.doesNotMatch(surface, /state\.toUpperCase\(\)/);
  }
});

test("v: provider rows show plain status words, never raw provider codes", () => {
  const providers = slice("const providerDetail = ", "const SettingsGenerationControl = ");
  const vocabulary = slice("const providerStateWord = ", "const toolStateWord = ");
  assert.match(providers, /providerStateWord/);
  for (const raw of ["NO KEY", "Paste a real key", "Local runtime is running"]) {
    assert.doesNotMatch(providers, new RegExp(raw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  for (const word of ["Connected", "Not connected", "Sign in needed", "Unavailable"]) {
    assert.match(vocabulary, new RegExp("'" + word + "'"));
  }
});

test('row a: no internal host-probe wording anywhere the user can see', () => {
  for (const file of ['01.APP/nodelang/studio/studio.html', '01.APP/nodelang/studio/studio-lm.jsx', '01.APP/nodelang/studio/studio-account.jsx']) {
    const text = fs.readFileSync(path.join(root, file), 'utf8');
    assert.equal(/host probe is still running|hosts were not read|has answered a probe/i.test(text), false, file + ' has no internal host-probe text');
  }
});
