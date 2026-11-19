// SETTINGS5: Settings sheet exposes Agents with one live row per agent app (Book Ch.9 / F32).
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const {transformSync} = require('esbuild');

test('SETTINGS5 sheet lists Agents beside Models and Hooks', () => {
  const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
  const source = fs.readFileSync(path.join(studio, 'ds_settings3.jsx'), 'utf8');
  const window = {
    UI: {
      A: {ok: '#0a0', warn: '#fc0', inkSoft: '#888', lineSoft: '#333', blue: '#36f', purple: '#80f', accent: '#f60'},
      D: {Toggle: () => null},
      api: {listAgentsWorking: async () => [], refreshRouter: async () => ({default_model: 'free', models: [], fallback_models: [], free_first: true}),
            readHostAvailability: async () => [], refreshSettingsControls: async () => ({}), readSessionsFolder: async () => 'Sessions',
            setRouterSettings: async () => null, chooseSessionsFolder: async () => null, addWorkspace: async () => null},
      useData: () => ({
        profile: {name: '', email: '', signedIn: false, checking: false},
        settings: [], hosts: [], connections: [], agents: [
          {id: 'claude', name: 'Claude Code', presence: 'working', status_text: 'Working', model: 'Actual model', task: 'Repair'},
          {id: 'codex', name: 'Codex', presence: 'stopped', status_text: 'Not running', model: 'Model not reported', task: 'Connect'},
          {id: 'opencode', name: 'OpenCode', presence: 'idle', status_text: 'Idle', model: 'Model not reported', task: 'Idle'},
          {id: 'gemini', name: 'Gemini CLI', presence: 'stopped', status_text: 'Not running', model: 'Model not reported', task: 'Connect'},
          {id: 'goose', name: 'BABOOM', presence: 'stopped', status_text: 'Not running', model: 'Model not reported', task: 'Connect'},
          {id: 'antigravity', name: 'Antigravity', presence: 'stopped', status_text: 'Not running', model: 'Model not reported', task: 'Connect'},
        ],
        agentSummary: '1 working · 1 idle', workspaces: [], sessionsFolder: 'Sessions', runtimeParameters: {},
      }),
      useApp: () => ({go: () => {}, act: async fn => fn && fn(), show: () => {}, settingsOrigin: 'home', advanced: false, setAdvanced: () => {}}),
      useRegisteredActions: () => ({runAction: () => {}, actionState: {}, retryAction: () => {}}),
      RegisteredActionStatus: () => null,
      Btn: ({children, ...props}) => React.createElement('button', props, children),
      SettingControl: () => null,
      Providers: () => null,
      Av: () => null,
      Chip: ({children}) => React.createElement('span', null, children),
      Empty: ({children}) => React.createElement('p', null, children),
      Heading: ({title, children}) => React.createElement('div', null, title, children),
      Card: ({children}) => React.createElement('section', null, children),
      MemoryRules: () => null,
      Automations: () => null,
      HostSkills: () => null,
      SystemGraph: () => null,
      AccountIdentity: () => null,
    },
    AHIcon: () => null,
    executeAction: (_id, payload) => payload?.handler && payload.handler(),
    React,
  };
  vm.runInNewContext(transformSync(source, {loader: 'jsx'}).code, {window, React});
  const html = renderToStaticMarkup(React.createElement(window.UI.Settings, {page: 'Agents'}));
  assert.match(html, /aria-label="Settings categories"/);
  assert.match(html, />Agents</);
  assert.match(html, /Claude Code/);
  assert.match(html, /Gemini CLI/);
  assert.match(html, /Antigravity/);
  assert.match(html, /Connect/);
  assert.match(html, /Working/);
  assert.doesNotMatch(html, /No live presence|Runtime-/);
});
