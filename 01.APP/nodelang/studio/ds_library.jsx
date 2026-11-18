// DSYS-064 Library shelf: existing tabs and the owner category tree, in Canvas.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
    A,
    api,
    useData,
    useApp,
    Btn,
    Empty
  } = window.UI;
  function SessionList({list, query='', onOpen, rows: suppliedRows, renderRow, sectionOf, collapsedSections=[], toggleSection}) {
    const s = useData(), u = useApp();
    const [kind, setKind] = React.useState(s.sessionListFilters?.[list] || 'all');
    const [request, setRequest] = React.useState('waiting'), [failure, setFailure] = React.useState(''), [attempt, setAttempt] = React.useState(0);
    React.useEffect(() => {
      let live = true;
      setRequest('waiting');
      api.readSessionListFilters().then(result => {if(live){setKind(result.sessionListFilters[list] || 'all');setRequest('loaded');}}).catch(error=>{if(live){setFailure(error.message);setRequest('error');}});
      return () => {live = false;};
    }, [list, attempt]);
    const choose = value => u.act(async () => {await api.setSessionListFilter(list,value);setKind(value);});
    const rows = (suppliedRows||s.graphs||[]).filter(row=>(kind==='all'||row.kind===kind)&&(row.title||row.name).toLowerCase().includes(query.toLowerCase()));
    const status = request==='loaded'&&!rows.length?'empty':request;
    const render=row=>renderRow?renderRow(row):<button type="button" className="listbutton" key={row.path} onClick={()=>executeAction('ui.select',async()=>{const opened=await u.act(()=>api.openSession(row.path));if(opened&&!opened.cancelled)onOpen?.();})}>{row.title||row.name}</button>;
    const sections=['Needs you','Working now','Today','Earlier this week','Older / archived'];
    const content=sectionOf?sections.map(name=>{const items=rows.filter(row=>sectionOf(row)===name);return items.length?<section className="home-session-section" key={name} data-home-section={name}><button type="button" className="home-section-heading" aria-expanded={!collapsedSections.includes(name)} onClick={()=>executeAction('ui.select',()=>toggleSection(name))}><span>{collapsedSections.includes(name)?'›':'⌄'} {name==='Older / archived'?'Older':name}</span><b>{items.length}</b></button>{!collapsedSections.includes(name)&&items.map(render)}</section>:null;}):rows.map(render);
    return <>{status==='waiting'&&<p role="status">Loading sessions…</p>}{status==='error'&&<p role="alert">{failure}<button type="button" onClick={()=>executeAction('ui.select',()=>setAttempt(attempt+1))}>Retry</button></p>}{(status==='loaded'||status==='empty')&&<><div className="shelf-tabs" role="group" aria-label="Saved document filter">{[['all','All'],['workflow','Workflows'],['agent-session','Agent sessions']].map(([value,label])=><button type="button" className="tab-button" key={value} aria-pressed={kind===value} onClick={()=>executeAction('ui.select',()=>choose(value))}>{label}</button>)}</div>{status==='loaded'&&<div className="session-section-list">{content}</div>}{status==='empty'&&<p>No sessions found.</p>}</>}</>;
  }
  window.UI.SessionList = SessionList;
  function LibraryShelf({
    onClose
  }) {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [family, setFamily] = React.useState('All'),
      [options, setOptions] = React.useState(false);
    const optionsButton = React.useRef(null), optionsMenu = React.useRef(null);
    React.useLayoutEffect(() => {if (options) optionsMenu.current?.querySelector('button')?.focus({preventScroll: true});}, [options]);
    // The owner's tree names and orders the categories. A card category it does not list still shows, under its own name.
    // An agent session is the record of a conversation, not a skill: the shelf never lists one.
    const agentSessions = (s.templates || []).filter(t => t.kind === 'agent-session').map(t => t.id);
    const catalogue = s.catalogue.filter(c => !agentSessions.includes(c.id));
    const tree = s.libraryTree || [];
    const listed = tree.flatMap(row => row.categories);
    const groups = [...tree, ...[...new Set(catalogue.map(c => c.family))].filter(f => !listed.includes(f)).map(f => ({id: f, label: f, icon: 'library', categories: [f]}))]
      .filter(group => catalogue.some(c => group.categories.includes(c.family)));
    const collapsed = s.libraryCollapsed || tree.map(row => row.id);
    const toggleSection = name => u.act(()=>api.setLibraryCollapsed(collapsed.includes(name)?collapsed.filter(value=>value!==name):[...collapsed,name]));
    // Search and the category chips filter the same owner catalogue. Both are view state and change no file.
    // A search reads the card's name and summary, its program (the engine it declares) and the tree row it sits under.
    const found = (c, group) => `${c.name} ${c.description} ${c.descriptor?.engine || ''} ${group.label}`.toLowerCase().includes(query.toLowerCase());
    const add = async c => {const node=await u.act(()=>api.addNode(c.id));if(node?.id)u.setSelectedNodeId(node.id);return node;};
    const sections = groups.filter(group => family === 'All' || family === group.id).map(group => [group, catalogue.filter(c => group.categories.includes(c.family) && found(c, group))]).filter(([, list]) => list.length);
    const open = group => Boolean(query.trim()) || !collapsed.includes(group.id);
    return <aside className="pane library-shelf" data-screen="library" aria-label="Library shelf"><header className="spread"><h2>Library</h2><Btn variant="controls" sm ghost aria-label="Close Library" onClick={event => executeAction("projects.ds_library.CloseLibrary.1", {onClose}, event)}>×</Btn></header><button className="listbutton flex shelf-new-session" onClick={event=>executeAction("projects.ds_library.NewSession.14", {api,u}, event)}><window.AHIcon name="plus" size={16}/>New canvas session</button>
      <div className="shelf-search"><input data-design="library.search" aria-label="Search nodes" placeholder="Search nodes, tools, skills" value={query} onChange={e => { setQuery(e.target.value); if (!e.target.value.trim()) setFamily('All'); }} /><span className="shelf-options-anchor" onBlur={e => {if (!e.currentTarget.contains(e.relatedTarget)) setOptions(false);}}><button type="button" ref={optionsButton} className="shelf-options" aria-label="Library options" aria-haspopup="menu" aria-expanded={options} title="Library & Mods, Community" onClick={event => executeAction('ui.select', () => setOptions(shown => !shown), event)}><window.AHIcon name="more" size={15} /></button>
        {options && <section ref={optionsMenu} className="context-menu shelf-options-menu" role="menu" aria-label="Library options" onClick={() => setOptions(false)} onKeyDown={e => {
          const buttons = [...e.currentTarget.querySelectorAll('button')];
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            buttons[(buttons.indexOf(document.activeElement) + (e.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
          }
          if (e.key === 'Escape') { e.stopPropagation(); setOptions(false); optionsButton.current?.focus(); }
        }}><div className="context-group"><button type="button" role="menuitem" onClick={event => executeAction("projects.ds_library.LibraryMods.15", {u}, event)}><window.AHIcon name="library" size={15} /><span>{'Library & Mods'}</span></button><button type="button" role="menuitem" onClick={event => executeAction("projects.ds_library.Community.16", {u}, event)}><window.AHIcon name="users" size={15} /><span>Community</span></button><button type="button" role="menuitem" onClick={event => executeAction("projects.ds_library.InstallMod.11", {u}, event)}><window.AHIcon name="plus" size={15} /><span>Import a node…</span></button></div></section>}</span></div>
      {query.trim() && <div className="family-chips">{[{id: 'All', label: 'All'}, ...groups].map(group => <button key={group.id} aria-pressed={family === group.id} style={family === group.id ? {background: 'transparent', color: A.ink, borderColor: A.line} : undefined} onClick={event => executeAction("projects.ds_library.SetFamilyF.3", {f:group.id,setFamily}, event)}>{group.label}</button>)}</div>}
      <div className="scroll fill">{sections.map(([group, list]) => <section key={group.id} className="shelf-group" data-library-category={group.id} data-open={open(group) || undefined}><button className="shelf-category" aria-expanded={open(group)} onClick={event=>executeAction("projects.ds_library.ToggleSection.13", {f:group.id,toggleSection}, event)}><window.AHIcon name="arrow" size={10} style={{transform:open(group)?'rotate(90deg)':undefined}}/><window.AHIcon name={group.icon} size={13}/><b>{group.label}</b><em>{list.length}</em></button>{open(group)&&list.map(c => c.soon ? <window.UI.Soon block key={c.id} label={c.name}><div data-design="library.row" data-soon-card={c.id} className="listbutton shelf-node"><span className="flex"><span className="shelf-node-copy"><b>{c.name}</b><small>{c.description}</small></span></span></div></window.UI.Soon> : <button data-design="library.row" className="listbutton shelf-node" key={c.id} disabled={c.unavailable} draggable={!c.unavailable} onDragStart={e => e.dataTransfer.setData('node', c.id)} onClick={event => executeAction("projects.ds_library.AddC.4", {add,c}, event)} title={'Add ' + c.name} aria-label={'Add ' + c.name}><span className="flex"><span className="shelf-node-copy"><b>{c.name}</b><small>{c.reason || c.description}</small></span></span><window.AHIcon name="plus" size={14} /></button>)}</section>)}{query.trim() && !sections.length && <Empty>Nothing matches.</Empty>}</div></aside>;
  }
  window.UI.LibraryShelf = LibraryShelf;
  // Design row 8 (res-064): a check's problems list. No engine reports problems by field path yet, so the area is drawn
  // as designed and held as Coming soon. The line shown is the design's own example, not a result.
  function CheckProblems() {
    return <window.UI.Soon block label="Problems list"><section className="prob-card" data-check-problems="" aria-label="Problems"><span className="prob-eyebrow">Problems</span><p>Each problem names its field, says what is wrong and suggests a fix.</p><ul className="probs"><li><code>$.walls[0].thikness</code><span>unknown field</span><em>Did you mean <b>thickness</b>?</em><span className="prob-acts"><span>Go to field</span><span>Use thickness</span></span></li></ul></section></window.UI.Soon>;
  }
  window.UI.CheckProblems = CheckProblems;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsdslibraryjsxToggleSection13({f,toggleSection}) {return toggleSection(f);}
async function projectsdslibraryjsxNewSession14({api,u}) {const result=await u.act(api.newSession);if(result)u.go('canvas');}

function projectsdslibraryjsxLibraryMods15({u}) {return u.go('settings/Library & Mods');}
function projectsdslibraryjsxCommunity16({u}) {return u.go('community');}
function projectsdslibraryjsxCloseLibrary1({onClose}, event) {
  const handler = onClose;
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
function projectsdslibraryjsxUShowSkillIdT6({api,t,u}, event) {
  const handler = () => u.act(() => api.openSession(t.path));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdslibraryjsxExportRecipe8({u}, event) {
  const handler = () => u.download('Recipe');
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
  "projects.ds_library.SetFamilyF.3": "projectsdslibraryjsxSetFamilyF3",
  "projects.ds_library.AddC.4": "projectsdslibraryjsxAddC4",
  "projects.ds_library.OnClose.5": "projectsdslibraryjsxOnClose5",
  "projects.ds_library.UShowSkillIdT.6": "projectsdslibraryjsxUShowSkillIdT6",
  "projects.ds_library.ExportRecipe.8": "projectsdslibraryjsxExportRecipe8",
  "projects.ds_library.MCPTools.10": "projectsdslibraryjsxMCPTools10",
  "projects.ds_library.InstallMod.11": "projectsdslibraryjsxInstallMod11",
"projects.ds_library.ToggleSection.13":"projectsdslibraryjsxToggleSection13",
"projects.ds_library.NewSession.14":"projectsdslibraryjsxNewSession14",
"projects.ds_library.LibraryMods.15":"projectsdslibraryjsxLibraryMods15",
"projects.ds_library.Community.16":"projectsdslibraryjsxCommunity16"
};
window.registerActions(PROJECT_ACTIONS, {projectsdslibraryjsxToggleSection13,projectsdslibraryjsxNewSession14,projectsdslibraryjsxLibraryMods15,projectsdslibraryjsxCommunity16,projectsdslibraryjsxCloseLibrary1,projectsdslibraryjsxSetFamilyF3,projectsdslibraryjsxAddC4,projectsdslibraryjsxOnClose5,projectsdslibraryjsxUShowSkillIdT6,projectsdslibraryjsxExportRecipe8,projectsdslibraryjsxMCPTools10,projectsdslibraryjsxInstallMod11});
})();
