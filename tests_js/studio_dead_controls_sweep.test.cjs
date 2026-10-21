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

test("swept Settings panels have no dead action rows", () => {
  const team = slice("const SettingsTeam = ", ";// ── Profile");
  for (const label of ["invite a teammate", "set seat count", "transfer ownership", "leave firm"]) {
    assert.equal(team.includes(label), false, label + " is not drawn without a firm handler");
  }

  const theme = slice("const SettingsTheme = ", "const SettingsShortcuts = ");
  assert.equal(/<button[^>]*data-theme=/.test(theme), false, "theme offerings are not fake buttons");
  assert.equal(theme.includes("Switching themes is not linked yet"), false);

  const models = slice("const SettingsModels = ", "// ── BABOOM startup");
  for (const unrouted of ["Vision · sketch parsing", "Long context (>100k)", "Fast bulk · drafts", "Embedding · skill search", "not routed separately in this build"]) {
    assert.equal(models.includes(unrouted), false, unrouted + " is not shown as a dead route");
  }
  assert.match(models, /<select aria-label="Reasoning model"[\s\S]*onChange=\{save\}/);
  assert.match(models, /rememberComposerModel\(item\)/, "select saves through existing composer persistence");
  assert.match(models, /Other jobs use the reasoning model\./);
  assert.match(source, /const freeModelRoute = item =>[\s\S]*route\.endsWith\(':free'\)[\s\S]*route\.startsWith\('lmstudio\/'\)[\s\S]*route\.startsWith\('ollama\/'\)/);
});
