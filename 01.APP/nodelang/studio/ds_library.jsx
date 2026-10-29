// DSYS-064 Library shelf: the original four tabs and five families, in Canvas.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {

    D,
    api,
    useData,
    useApp,
    Btn,
    Empty
  } = window.UI;
  function LibraryShelf({
    onClose
  }) {
    const s = useData(),
      u = useApp();
    const [tab, setTab] = React.useState('Library'),
      [query, setQuery] = React.useState(''),
      [family, setFamily] = React.useState('All');
    const rows = s.catalogue.filter(c => (family === 'All' || c.family === family) && `${c.name} ${c.description}`.toLowerCase().includes(query.toLowerCase()));
    const families = [...new Set(['Get', 'Change', 'Decide', 'See', 'Send', ...s.catalogue.map(c => c.family)])];
    const add = c => u.act(() => api.addNode(c.id));
    // One table to change when Ping cuts the groups: category -> Library group.
    const GROUP = {trigger: 'Start', input: 'Start', watch: 'Start', note: 'Start', host: 'Programs', file: 'Programs',
      document: 'Programs', files: 'Programs', connectors: 'Programs', office: 'Programs', settings: 'Programs',
      shape: 'Change', transform: 'Change', text: 'Change', math: 'Change', skill: 'Change', logic: 'Decide', ai: 'Decide',
      models: 'Decide', agents: 'Decide', governance: 'Decide', enforce: 'Decide', output: 'Deliver', workshop: 'Deliver'};
    const groupOf = c => GROUP[c.family] || 'Change';
    const sections = query.trim() ? families.filter(f => (family === 'All' || family === f) && rows.some(c => c.family === f)).map(f => [f, rows.filter(c => c.family === f)])
      : ['Start', 'Programs', 'Change', 'Decide', 'Deliver'].map(g => [g, rows.filter(c => groupOf(c) === g)]).filter(([, list]) => list.length);
    return <aside className="pane library-shelf" data-screen="library" aria-label="Library shelf"><header className="spread"><h2>Library</h2><Btn variant="controls" sm ghost aria-label="Close Library" onClick={event => executeAction("projects.ds_library.CloseLibrary.1", {onClose}, event)}>×</Btn></header><div className="shelf-tabs">{['Library', 'Workflows', 'Skills', 'Runs'].map(t => <button key={t} className="tab-button" aria-pressed={t === tab} onClick={event => executeAction("projects.ds_library.SetTabT.2", {setTab,t}, event)}>{t}</button>)}</div><input aria-label="Search nodes" placeholder="Search nodes…" value={query} onChange={e => { setQuery(e.target.value); if (!e.target.value.trim()) setFamily('All'); }} />{tab === 'Library' && query.trim() && <div className="family-chips">{['All', ...families].map(f => <button key={f} aria-pressed={family === f} onClick={event => executeAction("projects.ds_library.SetFamilyF.3", {f,setFamily}, event)}>{f}</button>)}</div>}<div className="scroll fill">{tab === 'Library' ? sections.map(([f, list]) => <section key={f}><div className="spread label" style={{
            padding: '14px 8px 5px'
          }}><span>{f}</span><span>{list.length}</span></div>{list.map(c => <button className="listbutton shelf-node" key={c.id} draggable onDragStart={e => e.dataTransfer.setData('node', c.id)} onClick={event => executeAction("projects.ds_library.AddC.4", {add,c}, event)} title={'Add ' + c.name} aria-label={'Add ' + c.name}><span className="flex"><D.Socket t={c.output} size={8} /><span className="shelf-node-copy"><b>{c.name}</b><small>{c.description}</small></span></span><window.AHIcon name="plus" size={14} /></button>)}</section>) : tab === 'Workflows' ? <><button className="listbutton" onClick={event => executeAction("projects.ds_library.OnClose.5", {onClose}, event)}>{s.graph.name}</button><div className="label" style={{padding: '14px 8px 5px'}}>Starters</div>{s.templates.filter(t => String(t.id).startsWith('starter:') && t.title.toLowerCase().includes(query.toLowerCase())).map(t => <button className="listbutton" key={t.id} title={t.stops_at} onClick={event => executeAction("projects.ds_library.OpenStarter.12", {api,t,u}, event)}><b>{t.title}</b>{(t.needs || []).length > 0 && <small className="muted"> · Needs {t.needs.join(', ')}</small>}</button>)}</> : tab === 'Skills' ? s.templates.filter(t => !String(t.id).startsWith('starter:') && t.title.toLowerCase().includes(query.toLowerCase())).map(t => <button className="listbutton" key={t.id} onClick={event => executeAction("projects.ds_library.UShowSkillIdT.6", {t,u}, event)}>{t.title}</button>) : s.runs.length ? s.runs.map(r => <button className="listbutton" key={r.id} onClick={event => executeAction("projects.ds_library.UShowRunIdR.7", {r,u}, event)}>{r.title}</button>) : <Empty>No runs yet.</Empty>}</div><footer className="shelf-footer"><button className="listbutton flex" onClick={event => executeAction("projects.ds_library.ExportRecipe.8", {u}, event)}><window.AHIcon name="export" size={16} />Export recipe</button><button className="listbutton flex" onClick={event => executeAction("projects.ds_library.ImportFlow.9", {u}, event)}><window.AHIcon name="export" size={16} />Import flow</button><button className="listbutton flex" onClick={event => executeAction("projects.ds_library.MCPTools.10", {u}, event)}><window.AHIcon name="link" size={16} />MCP tools</button><button className="listbutton flex" onClick={event => executeAction("projects.ds_library.InstallMod.11", {u}, event)}><window.AHIcon name="plus" size={16} />Install mod</button>{s.mods.map(m => <div className="spread row" key={m.id}><span>{m.name}</span><D.Toggle label={m.name + ' enabled'} checked={m.enabled} onCheckedChange={v => u.act(() => api.setModEnabled(m.id, v))} /></div>)}</footer></aside>;
  }
  window.UI.LibraryShelf = LibraryShelf;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsdslibraryjsxOpenStarter12({api,t,u}, event) {
  const handler = () => u.act(() => api.openStarter(t.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxCloseLibrary1({onClose}, event) {
  const handler = onClose;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxSetTabT2({setTab,t}, event) {
  const handler = () => setTab(t);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxSetFamilyF3({f,setFamily}, event) {
  const handler = () => setFamily(f);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxAddC4({add,c}, event) {
  const handler = () => add(c);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxOnClose5({onClose}, event) {
  const handler = onClose;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxUShowSkillIdT6({t,u}, event) {
  const handler = () => u.show('Skill', {
          id: t.id
        });
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxUShowRunIdR7({r,u}, event) {
  const handler = () => u.show('Run', {
          id: r.id
        });
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxExportRecipe8({u}, event) {
  const handler = () => u.download('Recipe');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxImportFlow9({u}, event) {
  const handler = u.pickFlow;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxMCPTools10({u}, event) {
  const handler = () => u.show('MCP tools');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxInstallMod11({u}, event) {
  const handler = () => u.show('Install mod');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
const PROJECT_ACTIONS = {
  "projects.ds_library.CloseLibrary.1": "projectsdslibraryjsxCloseLibrary1",
  "projects.ds_library.SetTabT.2": "projectsdslibraryjsxSetTabT2",
  "projects.ds_library.SetFamilyF.3": "projectsdslibraryjsxSetFamilyF3",
  "projects.ds_library.AddC.4": "projectsdslibraryjsxAddC4",
  "projects.ds_library.OnClose.5": "projectsdslibraryjsxOnClose5",
  "projects.ds_library.UShowSkillIdT.6": "projectsdslibraryjsxUShowSkillIdT6",
  "projects.ds_library.UShowRunIdR.7": "projectsdslibraryjsxUShowRunIdR7",
  "projects.ds_library.ExportRecipe.8": "projectsdslibraryjsxExportRecipe8",
  "projects.ds_library.ImportFlow.9": "projectsdslibraryjsxImportFlow9",
  "projects.ds_library.MCPTools.10": "projectsdslibraryjsxMCPTools10",
  "projects.ds_library.InstallMod.11": "projectsdslibraryjsxInstallMod11",
"projects.ds_library.OpenStarter.12": "projectsdslibraryjsxOpenStarter12"
};
window.registerActions(PROJECT_ACTIONS, {projectsdslibraryjsxOpenStarter12,projectsdslibraryjsxCloseLibrary1,projectsdslibraryjsxSetTabT2,projectsdslibraryjsxSetFamilyF3,projectsdslibraryjsxAddC4,projectsdslibraryjsxOnClose5,projectsdslibraryjsxUShowSkillIdT6,projectsdslibraryjsxUShowRunIdR7,projectsdslibraryjsxExportRecipe8,projectsdslibraryjsxImportFlow9,projectsdslibraryjsxMCPTools10,projectsdslibraryjsxInstallMod11});
})();
