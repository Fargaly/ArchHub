// Documentation projection of the Book topics and the same node catalogue.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
    api,
    useData,
    useApp,
    Btn,
    Card,
    Heading
  } = window.UI;
  const Icon = window.AHIcon;
  function Docs() {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [selected, setSelected] = React.useState('getting-started');
    const [guide, setGuide] = React.useState(null);
    const [load,setLoad]=React.useState({status:s.docs.length?'loaded':'waiting'}),[attempt,setAttempt]=React.useState(0);
    React.useEffect(()=>{let current=true;setLoad({status:'waiting'});api.refreshDocs().then(pages=>{if(current){setGuide(pages);setLoad({status:pages.length?'loaded':'empty'});}},error=>{if(current)setLoad({status:'error',message:error.message});});return()=>{current=false;};},[attempt]);
    const source = guide || s.docs;
    const q = query.trim().toLowerCase(),
      topics = (q ? source.filter(d => `${d.category} ${d.title} ${d.summary} ${(d.steps || []).join(' ')}`.toLowerCase().includes(q)) : source),
      article = q ? (topics.find(d => d.id === selected) || null) : (source.find(d => d.id === selected) || source.find(d => d.id === 'getting-started') || source[0]);
    const nodes = s.catalogue.filter(c => `${c.name} ${c.description}`.toLowerCase().includes(q));
    const groupOf=doc=>/^(getting-started|home|composer-canvas|account-web)$/.test(doc.id)?'START':/brain|model|routing|privacy|setting|approv|updat/.test(doc.id)?'CONFIGURE':'WORK';
    const glossary=s.bookGlossary.filter(line=>line.toLowerCase().includes(q));
    return <div className="docs-layout penpot-docs" data-screen="docs"><header className="docs-header"><h1>Documentation</h1><label><Icon name="search" size={16}/><span><span className="visually-hidden">Search the guide</span><input aria-label="Search docs" placeholder="Search the guide" value={query} onChange={e=>setQuery(e.target.value)}/><small>Files, nodes, programs…</small></span></label></header><div className="docs-body"><aside className="docs-toc" aria-label="Guide topics">{['START','WORK','CONFIGURE'].map(group=><section key={group}><h2>{group}</h2>{topics.filter(doc=>groupOf(doc)===group).map(d=><button key={d.id} className="listbutton" aria-current={article?.id===d.id&&!['nodes','glossary'].includes(selected)?'page':undefined} onClick={event=>executeAction('projects.docs.SetSelectedDId.1',{d,setSelected},event)}>{d.title}</button>)}</section>)}<section><h2>REFERENCE</h2><button className="listbutton" aria-current={selected==='nodes'?'page':undefined} onClick={event=>executeAction('projects.docs.NodeReference.2',{setSelected},event)}>Node reference</button><button className="listbutton" aria-current={selected==='glossary'?'page':undefined} onClick={event=>executeAction('projects.docs.Glossary.3',{setSelected},event)}>Glossary{load.status==='loaded'?' · '+s.bookGlossary.length:''}</button></section></aside><main className="docs-article">{load.status==='waiting'?<p role="status">Opening the guide…</p>:load.status==='error'?<div role="alert">{load.message}<Btn onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(value=>value+1)},event)}>Retry guide</Btn></div>:load.status==='empty'?<div className="empty-search"><p>No guide pages are available.</p><Btn onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(value=>value+1)},event)}>Retry guide</Btn></div>:load.status==='loaded'?<>{selected==='nodes'?<><Heading title="Node reference" sub="The building blocks, from the same Library catalogue"/><div className="reference-grid">{nodes.map(c=><Card key={c.id} style={{padding:20}}><h2>{c.name}</h2><p>{c.description}</p><button className="listbutton flex" onClick={event=>executeAction('projects.docs.OpenOnCanvas.5',{api,c,u},event)}>Open on canvas<Icon name="arrow" size={16}/></button></Card>)}</div></>:selected==='glossary'?<><Heading title="Glossary" sub="The words you meet in ArchHub"/><dl className="docs-glossary">{glossary.map((line,i)=>{const parts=line.split('|').filter(Boolean).map(part=>part.replaceAll('**','').trim());return <div key={i}><dt>{parts[0]}</dt><dd><window.UI.Prose text={parts[1]}/></dd></div>;})}</dl>{!glossary.length&&<p>No glossary entries match “{query}”.</p>}</>:article?<article><Heading title={article.title} sub={article.summary}/><div className="docs-guide-content">{article.steps.map((line,i)=>/^#{1,3} /.test(line)?<h2 key={i}>{line.replace(/^#+\s*/,'')}</h2>:/^\d+\. /.test(line)?<div className="docs-guide-step" key={i}><span>{line.match(/^\d+/)[0].padStart(2,'0')}</span><window.UI.Prose text={line.replace(/^\d+\. /,'')}/></div>:<window.UI.Prose key={i} text={line}/>)}</div><div className="docs-open"><Btn p sm onClick={event=>executeAction('projects.docs.OpenInTheApp.6',{article,u},event)}>Open</Btn></div></article>:q?<div className="empty-search"><Icon name="search" size={30}/><h2>No guide matches “{query}”</h2><button className="listbutton" onClick={event=>executeAction('projects.docs.ClearSearch.9',{setQuery},event)}>Clear search</button></div>:<div className="empty-search"><p>Opening the guide…</p></div>}</>:null}</main></div></div>;
  }
  window.UI.Docs = Docs;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsdocsjsxSetSelectedDId1({d,setSelected}, event) {
  const handler = () => setSelected(d.id);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdocsjsxNodeReference2({setSelected}, event) {
  const handler = () => setSelected('nodes');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdocsjsxGlossary3({setSelected}, event) {
  const handler = () => setSelected('glossary');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdocsjsxOpenOnCanvas5({api,c,u}, event) {
  const handler = async () => { const node = await u.act(() => api.addNode(c.id)); if (node) { u.setSelectedNodeId(node.id); u.go('canvas'); } };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdocsjsxOpenInTheApp6({article,u}, event) {
  const handler = () => u.go(article.route);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdocsjsxClearSearch9({setQuery}, event) {
  const handler = () => setQuery('');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
const PROJECT_ACTIONS = {
  "projects.docs.SetSelectedDId.1": "projectsdocsjsxSetSelectedDId1",
  "projects.docs.NodeReference.2": "projectsdocsjsxNodeReference2",
  "projects.docs.Glossary.3": "projectsdocsjsxGlossary3",
  "projects.docs.OpenOnCanvas.5": "projectsdocsjsxOpenOnCanvas5",
  "projects.docs.OpenInTheApp.6": "projectsdocsjsxOpenInTheApp6",
  "projects.docs.ClearSearch.9": "projectsdocsjsxClearSearch9"
};
window.registerActions(PROJECT_ACTIONS, {projectsdocsjsxSetSelectedDId1,projectsdocsjsxNodeReference2,projectsdocsjsxGlossary3,projectsdocsjsxOpenOnCanvas5,projectsdocsjsxOpenInTheApp6,projectsdocsjsxClearSearch9});
})();
