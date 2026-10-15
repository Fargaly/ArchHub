const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');

test('APP-FRAME p3: mounted workspace row owns the viewport height between top and status bars', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const frameStart = source.indexOf('// DSYS-060 app frame parts.');
  const frameEnd = source.indexOf('const CommandBar = (', frameStart);
  assert.ok(frameStart >= 0 && frameEnd > frameStart, 'Frame slice is available');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53916/', pretendToBeVisual:true});
  Object.defineProperty(dom.window, 'innerHeight', {configurable:true, value:959});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  try {
    const vm = require('node:vm');
    const context = vm.createContext({
      React, window:dom.window, document:dom.window.document,
      LM:{bgDeep:'#000', ink:'#fff', sans:'Inter, sans-serif', bg:'#111', lineSoft:'#222', bgHover:'#333',
        accent:'#d97757', inkSoft:'#aaa', warn:'#fb0', onFill:'#111', rad:{sm:4}, bgPanel:'#151515', line:'#333',
        userAv:'#654', onUserAv:'#fff'},
      useWorkshopProjection:() => ({waiting:[]}),
      workshopWaitingItems:() => [],
    });
    dom.window.AH = context.LM;
    const sharedRail = fs.readFileSync(path.join(root, 'nodelang/studio/shared-data.jsx'), 'utf8').slice(fs.readFileSync(path.join(root, 'nodelang/studio/shared-data.jsx'), 'utf8').indexOf('window.ARCHHUB_APP_RAIL ='));
    vm.runInContext(transformSync(sharedRail, {loader:'jsx'}).code, context);
    vm.runInContext(transformSync(source.slice(frameStart, frameEnd) + '\nglobalThis.Frame = Frame;',
      {loader:'jsx', format:'cjs'}).code, context);
    const reactRoot = createRoot(dom.window.document.getElementById('root'));
    await React.act(async () => reactRoot.render(React.createElement(context.Frame, {
      rail:'Library', left:React.createElement('div', null, 'left'),
      top:React.createElement('div', null, 'top'), status:React.createElement('div', null, 'status'),
      onHome:() => {}, onPanel:() => {}, onDocs:() => {}, onSettings:() => {}, account:{},
    }, React.createElement('main', {'data-workspace-main':'', style:{height:'100%', display:'grid', gridTemplateRows:'36px 1fr'}},
      React.createElement('div', null, 'workspace header'),
      React.createElement('section', {'data-workspace-fill':''}, 'canvas')))));
    const frame = dom.window.document.querySelector('[data-app-frame]');
    const workspace = dom.window.document.querySelector('[data-workspace-frame]');
    const main = dom.window.document.querySelector('[data-workspace-main]');
    assert.equal(frame.style.gridTemplateRows, '36px minmax(0, 1fr) 22px');
    assert.equal(workspace.style.height, '100%');
    assert.equal(workspace.style.display, '', 'wrapper is not a grid that can create an empty implicit column');
    assert.equal(main.style.height, '100%');
    assert.equal(959 - 36 - 22, 901, 'workspace fill height equals viewport minus top bar and status strip');
    reactRoot.unmount();
  } finally {
    global.window = oldWindow; global.document = oldDocument; dom.window.close();
  }
});

test('DSYS-060 app frame owns the one Studio shell grid', () => {
  assert.match(source, /const Frame = \(/, 'the app frame primitive is present');
  assert.match(source, /data-app-frame/, 'the shipped shell exposes the frame boundary');
  assert.match(source, /gridTemplateColumns:hasLeft \? `\$\{railWidth\}px 248px minmax\(0, 1fr\) 320px` : `\$\{railWidth\}px minmax\(0, 1fr\)`/,
    'frame columns collapse the empty left panel to rail 64 + content');
  assert.match(source, /\{hasLeft && <aside data-left-panel=/,
    'the left panel element is not mounted when the screen has no left content');
  assert.match(source, /left=\{panel && !workshopContext \? <Sidebar/s,
    'Home sends no empty Sidebar into the frame');
  assert.match(source, /gridTemplateRows:\s*'36px minmax\(0, 1fr\) 22px'/,
    'frame rows are top bar 36, canvas fluid, status strip 22');
  assert.match(source, /data-workspace-frame=""[\s\S]*height:'100%'/,
    'the workspace wrapper fills the frame instead of shrinking to content height');
  assert.doesNotMatch(source, /data-workspace-frame=""[\s\S]{0,180}display:'grid'/,
    'the workspace wrapper does not create implicit grid columns');
  assert.match(source, /data-workspace-main=""[\s\S]*height:'100%'/,
    'the Workspace grid inherits the filled wrapper height');
  assert.doesNotMatch(source, /gridTemplateColumns:\s*\(!panel \|\| workshopContext\) \? '64px 1fr' : '292px 1fr'/,
    'the old variable outer shell is removed');
  assert.equal((source.match(/<Frame\b/g) || []).length, 1,
    'Home, graph, workshop and tools go through one frame instance');
});

test('DSYS-060 rail, panel head, search and breadcrumb primitives are the shared plate parts', () => {
  assert.match(source, /const AppRail = window\.ARCHHUB_APP_RAIL/, 'the frame reuses the Workshop v3 rail');
  assert.match(source, /Home:onHome, Workshop:onWorkshop, Canvas:onCanvas/, 'the shared rail routes all primary surfaces');
  assert.doesNotMatch(source, /const RailItem =|const IconRail =|const RailIcon =/, 'the old rail implementations are deleted');
  assert.match(source, /const PanelHead = \(/, 'PanelHead primitive is shared');
  assert.match(source, /fontSize:16,\s*fontWeight:600/, 'PanelHead title is Inter 16/600');
  assert.doesNotMatch(source, /drag · or 2× click/, 'left panel header has no instruction text');
  assert.match(source, /const Search = \(/, 'Search primitive is shared');
  assert.match(source, /Ctrl K/, 'Search carries the Ctrl K hint');
  assert.match(source, /const Crumb = \(/, 'Crumb primitive is shared');
  assert.match(source, /\u25b8/, 'Crumb uses triangle separators');
});

test('APP-FRAME p3 chrome removes mono instruction labels from canvas and inspector headers', () => {
  assert.doesNotMatch(source, /scroll → zoom|drag → pan|right-click → menu/,
    'canvas toolbar draws controls, not instruction text');
  assert.doesNotMatch(source, /<CanvasHint\/>/, 'retired canvas hint is not rendered');
  const railStart = source.indexOf('const NodeRail = (');
  const railEnd = source.indexOf('// ─── Conversation rail', railStart);
  const railSource = source.slice(railStart, railEnd);
  assert.match(railSource, /fontFamily:LM\.sans,\s*fontSize:11,\s*fontWeight:600[\s\S]*Graph/,
    'graph inspector caption is Inter 11/600');
  assert.match(railSource, /fontFamily:LM\.sans,\s*fontSize:16,\s*fontWeight:600/,
    'inspector title is Inter 16/600');
  assert.doesNotMatch(railSource, /'GRAPH'/,
    'inspector header no longer uses mono caps or serif display type');
  const inspectorHeader = railSource.slice(railSource.indexOf('<div style={{ display:\'flex\', alignItems:\'center\', gap:7 }}>'),
    railSource.indexOf('<InspectorTabs', railSource.indexOf('<div style={{ display:\'flex\', alignItems:\'center\', gap:7 }}>')));
  assert.doesNotMatch(inspectorHeader, /fontFamily:LM\.serif|letterSpacing:'-0/,
    'inspector header no longer uses serif display type');
  const modelConversationStart = source.indexOf('const NodeModelConversation = (');
  const modelConversationEnd = source.indexOf('const formatNodeConversationTime', modelConversationStart);
  const modelConversationSource = source.slice(modelConversationStart, modelConversationEnd);
  assert.doesNotMatch(modelConversationSource, /CONVERSATION|fontFamily:LM\.mono[\s\S]{0,120}Conversation/,
    'conversation header no longer uses mono caps');
  const toolbarStart = source.indexOf('const CanvasToolbar = (');
  const toolbarEnd = source.indexOf('// ─── floating composer', toolbarStart);
  const toolbarSource = source.slice(toolbarStart, toolbarEnd);
  assert.doesNotMatch(toolbarSource, /(Arrange|Run|Automate|add node)[\s\S]{0,160}fontFamily:LM\.mono|fontFamily:LM\.mono[\s\S]{0,160}(Arrange|Run|Automate|add node)/,
    'canvas toolbar command labels use Inter');
});

test('DSYS-060 status strip is fed from live state, not seeded plate literals', () => {
  const statusStart = source.indexOf('const StatusBar = (');
  const statusEnd = source.indexOf('const ServerStrip = StatusBar;', statusStart);
  const statusSource = source.slice(statusStart, statusEnd > statusStart ? statusEnd : statusStart + 7000);
  assert.match(source, /const StatusBar = \(/, 'StatusBar primitive is shared');
  assert.doesNotMatch(statusSource, /Revit 2025/, 'status host is not hard-coded to the plate seed');
  assert.doesNotMatch(statusSource, /Nile_Tower/, 'status document is not hard-coded to the plate seed');
  assert.doesNotMatch(statusSource, /server\s*:/, 'status strip does not expose local server/port text');
  assert.doesNotMatch(statusSource, /0\/0|proof/, 'status strip does not expose zero host tallies or proof labels');
  assert.match(statusSource, /No program connected/, 'status has the approved disconnected state');
  assert.match(statusSource, /Connected/, 'status has the approved connected state');
  assert.match(statusSource, /sessionsForStatus\.filter\(s => s\.state === 'running'\)/,
    'status uses the existing running session count source');
  assert.match(statusSource, /window\.ARCHHUB_LIVE\?\.sessions/,
    'status keeps a live-session fallback for isolated mounts');
  assert.match(statusSource, /waitingItems\.length/, 'status uses live waiting counts');
  assert.match(statusSource, /modelRoute\(/, 'status reads the selected model/provider route');
  assert.match(statusSource, /Checking programs/, 'status preserves the in-flight host-read state');
  assert.match(statusSource, /Programs unavailable/, 'status preserves the failed host-read state');
  assert.match(statusSource, /Last known:/, 'status labels cached host values as last-known after a failed refresh');
  assert.match(statusSource, /const hostReadFailed = !!hostCatalogue\.error;/,
    'failed host freshness outranks cached connected rows');
  assert.match(statusSource, /const hostReadInFlight = !!hostCatalogue\.loading \|\| \(!hostReadSucceeded && !hostReadFailed\);/,
    'initial unstarted host reads stay in the checking state');
  assert.match(statusSource, /loadCatalogue\('ARCHHUB_LOAD_HOSTS', LM_HOSTS\)/, 'failed host reads expose a real Retry route');
  assert.match(statusSource, /postStopControl\('\/stop-all', true\)/, 'status keeps global Stop routed to the server control');
  assert.match(statusSource, /postStopControl\('\/resume', false\)/, 'status keeps global Resume routed to the server control');
  assert.doesNotMatch(statusSource, />docs</, 'status strip has no docs link');
});

test('DSYS-060 command bar is the one Ctrl K and slash search route', () => {
  assert.match(source, /const CommandBar = \(/, 'CommandBar primitive is present');
  assert.match(source, /data-command-bar/, 'the shipped command surface is exposed');
  assert.match(source, /shortcut\.action === 'open-command-bar'/, 'Ctrl K opens the command bar');
  assert.match(source, /e\.key === '\/'[\s\S]*setCommandOpen\(true\)/, 'slash opens the same command bar');
  assert.match(source, /group:'Add node'[\s\S]*addNodeFromLibrary/, 'Add node rows use the existing add route');
  assert.match(source, /group:'Skills'[\s\S]*ArchHubStudioScreens\?\.open[\s\S]*openSkill\('skill', skill\)/,
    'Skill rows use the existing skill route');
  assert.doesNotMatch(source, /LM_SAVED_SKILLS\.filter[\s\S]{0,160}\.slice\(0, 3\)/,
    'Skill rows are not capped to three saved skills');
  assert.match(source, /Skill viewer is unavailable[\s\S]*return false/, 'unavailable skill routes keep the command bar open with a visible error');
  assert.match(source, /group:'Chats'[\s\S]*onOpenSession/, 'Chat rows use the existing open route');
});

test('DSYS-060 toast and destructive dialog contracts are centralized', () => {
  assert.match(source, /const AppToast = \(/, 'one app toast component is present');
  assert.match(source, /setTimeout\(toast\.close, 6000\)/, 'toast lifetime is 6 seconds');
  assert.match(source, /toast\.actionLabel && <button/, 'toast renders at most one action');
  assert.match(source, /const DestructiveDialog = \(/, 'destructive dialog component is present');
  assert.match(source, /width:400/, 'dialog is 400 wide');
  assert.match(source, /rgba\(0,0,0,\.5\)/, 'dialog scrim is .5');
  assert.match(source, /autoFocus onClick=\{onCancel\}/, 'dialog focus starts on Cancel');
  assert.match(source, /Undo brings them back/, 'dialog body names what goes with the delete and the undo recovery');
});

test('DSYS-060 plate sample data does not ship in the changed Studio JSX', () => {
  for (const sample of [
    'Revit 2025',
    'Nile_Tower',
    'Omar',
    'sara@firm.com',
    'Clinic',
    '46 doors',
    'L3-D001',
    '09:14',
    'run #48',
  ]) {
    assert.equal(source.includes(sample), false, 'studio-lm.jsx still contains plate sample ' + JSON.stringify(sample));
  }
});
