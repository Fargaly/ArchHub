// DSYS-082 Home evolved into the founder-selected B+C material work stream.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {

    useData,
    useApp,
    Btn,
    Card,

    Av,

  } = window.UI;
  function Sheet({
    mark = false,
    large = false
  }) {
    const s = useData(),
      w = s.watcher;
    const points = w.geometry.walls.flatMap(line => [[line[0],line[1]],[line[2],line[3]]]);
    const xs = points.map(p=>p[0]), ys=points.map(p=>p[1]);
    const bounds = points.length ? [Math.min(...xs),Math.min(...ys),Math.max(1,Math.max(...xs)-Math.min(...xs)),Math.max(1,Math.max(...ys)-Math.min(...ys))] : [0,0,1,1];
    return <svg width={large ? '100%' : 86} height={large ? 112 : 60} viewBox={bounds.join(' ')} aria-label={w.host || 'Source preview'} style={{
      borderRadius: 6,
      background: '#e7e3db',
      display: 'block'
    }}><g fill="none" stroke={mark ? '#bc5a45' : '#6d695e'} strokeWidth="1" vectorEffect="non-scaling-stroke">{w.geometry.walls.map(([x1, y1, x2, y2], i) => <path key={i} d={`M${x1} ${y1}L${x2} ${y2}`} />)}</g></svg>;
  }
  function Tpl({
    template: t
  }) {
    const u = useApp();
    const [menu, setMenu] = React.useState(false);
    const start = async () => {
      const done = await u.act(() => window.ArchHubAPI.startTemplate(t.id));
      if (done) u.go('canvas');
    };
    return <Card className="template-card" data-starter={t.id}><div className="spread"><b>{t.title}</b><span className="flex">{(t.needs || []).map(n => <span key={n} className="chip" data-needs={n}>Needs {n}</span>)}{t.runs > 0 && <span className="mono muted">{t.runs + '×'}</span>}<button className="icon-button" aria-label={'More for ' + t.title} aria-expanded={menu} onClick={event => executeAction("projects.ds_home2.StarterMenu.11", {menu,setMenu}, event)}>⋯</button></span></div><span className="template-chain">{t.chain.slice(0, 6).map((c, i) => <React.Fragment key={c + i}>{i > 0 && <i />}<span>{c}</span></React.Fragment>)}{t.chain.length > 6 && <small>+{t.chain.length - 6}</small>}</span>{t.stops_at && <small className="muted">{t.stops_at}</small>}{menu && <div className="template-menu" role="menu"><Btn sm ghost role="menuitem" onClick={event => executeAction("projects.ds_home2.AsyncAwaitUActWindow.2", {t,u}, event)}>Open on canvas</Btn><Btn sm ghost role="menuitem" onClick={event => executeAction("projects.ds_home2.UScheduleTTitle.3", {t,u}, event)}>Run every day</Btn></div>}<Btn sm p aria-label={'Start ' + t.title} onClick={event => executeAction("projects.ds_home2.Start.1", {start}, event)}>Start</Btn></Card>;
  }
  function Home() {
    const s = useData(), u = useApp();
    const pending = s.approvals.filter(c => c.status === 'pending');
    const working = [...s.tasks.filter(t => t.status === 'WIP'),...(s.declaredTasks||[])];
    const finished = s.tasks.filter(t => t.status === 'DONE');
    const reviewTask = s.tasks.find(t => t.id === pending[0]?.taskId);
    const reviewOwner = (s.agents||[]).find(a=>(reviewTask?.declarations||[]).some(d=>a.sessions?.some(row=>row.root===d.root))) || s.providers.find(p => p.id === reviewTask?.owner);
    const reviewContext = pending[0]?.target || reviewTask?.project || s.graph.name;
    const [showTemplates, setShowTemplates] = React.useState(false);
    const openTask = t => { u.setTask(t.declaration?'':t.id); u.go('workshop'); };
    return <main className="page home-page" data-screen="home" data-home-page="">
      <div className="home-content">
        <header className="home-intro">
          <div className="eyebrow">Your workspace · {s.profile.firm}</div>
          <h1>{working.length ? `Your agents are finishing ${working.length} thing${working.length === 1 ? '' : 's'} for you` : 'Nothing is running. Start something below.'}</h1>
          <div className="spread"><p className="muted">{pending.length ? `${pending.length} decision${pending.length === 1 ? '' : 's'} ready for you.` : 'Tell BABOOM what you want to do.'} {(s.agents||[]).some(p=>p.presence==='working') ? 'Your agents have the rest.' : ''}</p>
            <button className="button-reset flex home-team" onClick={event => executeAction("projects.ds_home2.AgentsAtWork.4", {u}, event)} aria-label="Agents at work">{(s.agents||[]).filter(p => p.presence==='working').slice(0,3).map(p => <Av key={p.id} id={p.id} size={24} />)}<span title={(s.agents||[]).map(p=>p.name+' · '+p.task).join(' · ')}>{s.agentSummary||'Checking running agents…'}</span><window.AHIcon name="arrow" size={15} /></button>
          </div>
        </header>
        <section className="work-stream" aria-label="Your work stream">
          {pending.length || s.lastResult ? <article className="stream-review">
            <span className="stream-marker attention" />
            <div className="spread"><span className="eyebrow">{pending.length ? 'Needs your eye' : 'Latest result'}</span><span className="mono muted">{pending.length ? 'Ready to review' : s.lastResult?.status}</span></div>
            <div className="review-focus"><div className="review-copy"><h2>{pending[0]?.title || s.lastResult?.title || 'Your latest results'}</h2><p className="muted">{reviewContext}</p><p className="review-detail">{pending.length ? 'The proposed change is ready. Take a look before it is written.' : 'Open the recorded result to inspect its node outputs.'}</p><div className="flex"><Av id={reviewOwner?.id} size={23} /><span className="muted">{reviewOwner?.name || "Your agents"}</span><span className="fill" />{pending[0] ? <Btn p onClick={event => executeAction("projects.ds_home2.ReviewAndApprove.5", {pending,u}, event)}>Review and approve</Btn> : <Btn p onClick={event => executeAction("projects.ds_home2.OpenResults.6", {u}, event)}>Open results</Btn>}</div></div>
            <button className="preview-button focus-preview" title="Open sheets" aria-label="Open sheets" onClick={event => executeAction("projects.ds_home2.OpenSheets.7", {u}, event)}><Sheet mark large /></button></div>
          </article> : <window.UI.Empty>Ask BABOOM below or start a template. Your results will appear here.</window.UI.Empty>}
          <div className="stream-activity">
            {working.slice(0,2).map(t => <button key={t.id} className="stream-task" onClick={event => executeAction("projects.ds_home2.OpenTaskT.8", {openTask,t}, event)}><span className="stream-marker working" /><Av id={t.owner} size={25} /><span className="fill"><b>{t.title}</b><small>In progress</small></span><window.AHIcon name="arrow" size={16} /></button>)}
            {finished.slice(0,1).map(t => <button key={t.id} className="stream-task" onClick={event => executeAction("projects.ds_home2.OpenTaskT.9", {openTask,t}, event)}><span className="stream-marker complete" /><Av id={t.owner} size={25} /><span className="fill"><b>{t.title}</b><small>Finished</small></span><window.AHIcon name="check" size={16} /></button>)}
          </div>
        </section>
        <section className="home-start"><div className="spread"><h2>Start something</h2><button className="tab-button" aria-expanded={showTemplates} onClick={event => executeAction("projects.ds_home2.SetShowTemplatesShowTemplates.10", {setShowTemplates,showTemplates,u}, event)}>{s.templateError ? 'Retry templates' : showTemplates ? 'Fewer' : 'More (' + Math.max(0, s.templates.length - 6) + ')'}<window.AHIcon name="arrow" size={13} /></button></div><div className="home-templates">{s.templates.slice().sort((a,b) => (b.runs??0)-(a.runs??0)).slice(0,showTemplates ? s.templates.length : 6).map(t => <Tpl key={t.id} template={t} />)}</div>{(s.templateError||!s.templates.length) && <window.UI.Empty>{s.templateError||'Save a workflow from Canvas to add your first template.'}</window.UI.Empty>}</section>
      </div>
    </main>;
  }
  window.UI.Home = Home;
  window.UI.Sheet = Sheet;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsdshome2jsxStart1({start}, event) {
  const handler = start;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxAsyncAwaitUActWindow2({t,u}, event) {
  const handler = async () => {
          const result = await u.act(() => t.id.startsWith('starter:') ? window.ArchHubAPI.openStarter(t.id) : window.ArchHubAPI.openTemplateGraph(t.id));
          if (result) u.go('canvas');
        };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxUScheduleTTitle3({t,u}, event) {
  const handler = () => u.schedule(t.title);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxAgentsAtWork4({u}, event) {
  const handler = () => u.go('colleagues');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxReviewAndApprove5({pending,u}, event) {
  const handler = () => u.show('Approve', {id:pending[0].id});
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxStarterMenu11({menu,setMenu}, event) {
  const handler = () => setMenu(!menu);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxOpenResults6({u}, event) {
  const handler = () => u.go('runs');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxOpenSheets7({u}, event) {
  const handler = () => u.go('watcher');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxOpenTaskT8({openTask,t}, event) {
  const handler = () => openTask(t);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxOpenTaskT9({openTask,t}, event) {
  const handler = () => openTask(t);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdshome2jsxSetShowTemplatesShowTemplates10({setShowTemplates,showTemplates,u}, event) {
  const handler = () => {setShowTemplates(!showTemplates);if(window.ArchHubAPI.getSnapshot().templateError)return u.act(()=>window.ArchHubAPI.refreshProjects());return undefined;};
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
const PROJECT_ACTIONS = {
  "projects.ds_home2.Start.1": "projectsdshome2jsxStart1",
  "projects.ds_home2.AsyncAwaitUActWindow.2": "projectsdshome2jsxAsyncAwaitUActWindow2",
  "projects.ds_home2.UScheduleTTitle.3": "projectsdshome2jsxUScheduleTTitle3",
  "projects.ds_home2.AgentsAtWork.4": "projectsdshome2jsxAgentsAtWork4",
  "projects.ds_home2.ReviewAndApprove.5": "projectsdshome2jsxReviewAndApprove5",
  "projects.ds_home2.OpenResults.6": "projectsdshome2jsxOpenResults6",
  "projects.ds_home2.OpenSheets.7": "projectsdshome2jsxOpenSheets7",
  "projects.ds_home2.OpenTaskT.8": "projectsdshome2jsxOpenTaskT8",
  "projects.ds_home2.OpenTaskT.9": "projectsdshome2jsxOpenTaskT9",
  "projects.ds_home2.SetShowTemplatesShowTemplates.10": "projectsdshome2jsxSetShowTemplatesShowTemplates10",
"projects.ds_home2.StarterMenu.11": "projectsdshome2jsxStarterMenu11"
};
window.registerActions(PROJECT_ACTIONS, {projectsdshome2jsxStarterMenu11,projectsdshome2jsxStart1,projectsdshome2jsxAsyncAwaitUActWindow2,projectsdshome2jsxUScheduleTTitle3,projectsdshome2jsxAgentsAtWork4,projectsdshome2jsxReviewAndApprove5,projectsdshome2jsxOpenResults6,projectsdshome2jsxOpenSheets7,projectsdshome2jsxOpenTaskT8,projectsdshome2jsxOpenTaskT9,projectsdshome2jsxSetShowTemplatesShowTemplates10});
})();
