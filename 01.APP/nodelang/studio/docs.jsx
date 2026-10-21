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
      [selected, setSelected] = React.useState(s.docs[0]?.id);
    const q = query.toLowerCase(),
      topics = s.docs.filter(d => `${d.category} ${d.title} ${d.summary} ${(d.steps || []).join(' ')}`.toLowerCase().includes(q)),
      article = topics.find(d => d.id === selected) || topics[0];
    const nodes = s.catalogue.filter(c => `${c.name} ${c.description}`.toLowerCase().includes(q));
    return <div className="docs-layout" data-screen="docs"><aside className="pane docs-toc"><div className="flex"><Icon name="docs" /><h2>Documentation</h2></div><input aria-label="Search docs" placeholder="Search the guide…" value={query} onChange={e => setQuery(e.target.value)} /><div className="eyebrow">THE GUIDE</div>{topics.map(d => <button key={d.id} className="listbutton" aria-selected={article?.id === d.id} onClick={event => executeAction("projects.docs.SetSelectedDId.1", {d,setSelected}, event)}>{d.title}</button>)}<button className="listbutton" aria-selected={selected === 'nodes'} onClick={event => executeAction("projects.docs.NodeReference.2", {setSelected}, event)}>Node reference · {s.catalogue.length}</button><button className="listbutton" aria-selected={selected === 'glossary'} onClick={event => executeAction("projects.docs.Glossary.3", {setSelected}, event)}>Glossary · {s.bookGlossary.length}</button><div className="docs-help"><p className="muted">Need a hand?</p><button className="listbutton flex" onClick={event => executeAction("projects.docs.AskBABOOM.4", {u}, event)}><Icon name="voice" size={16} />Ask BABOOM</button></div></aside><main className="page docs-article">{selected === 'nodes' ? <><Heading title="Node reference" sub="The building blocks, from the same Library catalogue" /><div className="reference-grid">{nodes.map(c => <Card key={c.id} style={{
              padding: 20
            }}><div className="spread"><h2>{c.name}</h2><span className="eyebrow">{c.family}</span></div><p className="muted" style={{
                margin: '12px 0'
              }}>{c.description}</p><p className="mono muted" style={{
               fontSize: 11
             }}>{c.family || c.category || 'Catalogue entry'}</p><button className="listbutton flex" onClick={event => executeAction("projects.docs.OpenOnCanvas.5", {api,c,u}, event)}>Open on canvas<Icon name="arrow" size={16} /></button></Card>)}</div></> : selected === 'glossary' ? <><Heading title="Glossary" sub="The words you meet in ArchHub" /><Card>{(s.bookGlossary || []).filter(l => l.toLowerCase().includes(q)).map((l, i) => {
              const parts = l.split('|').filter(Boolean).map(x => x.replaceAll('**', '').trim());
              return <div key={i} className="row"><h3>{parts[0]}</h3><p className="muted">{parts[1]}</p></div>;
            })}</Card></> : article ? <article><span className="eyebrow">ArchHub guide / {article.category}</span><Heading title={article.title} sub={article.summary}><Btn p sm onClick={event => executeAction("projects.docs.OpenInTheApp.6", {article,u}, event)}>Open in the app</Btn></Heading><div className="tutorial-picture"><div className="tutorial-top"><Icon name={article.route.includes('settings') ? 'settings' : article.route === 'brain' ? 'brain' : article.route === 'workshop' ? 'workshop' : 'canvas'} size={18} /><span>{article.category}</span><span className="fill" /><i /><i /><i /></div>{article.route === 'watcher' || article.route === 'home' ? <window.UI.Sheet large mark /> : <div className="tutorial-flow">{article.steps.map((step, i) => <React.Fragment key={i}>{i > 0 && <Icon name="arrow" />}<div><span>{String(i + 1).padStart(2, '0')}</span><b>{step.split('.')[0].slice(0, 48)}</b></div></React.Fragment>)}</div>}</div><h2 style={{
             margin: '32px 0 18px'
            }}>Guide</h2><ol className="tutorial-steps">{(article.steps || []).map((step, i) => <li key={i}><span>{i + 1}</span><p>{step.replace(/^#+\s*/, '')}</p></li>)}</ol><Card style={{
            padding: 20,
            margin: '26px 0'
           }}><div className="flex"><Icon name="voice" /><h3>BABOOM can help</h3></div><p className="muted" style={{
             marginTop: 8
           }}>These instructions are projected from this build’s catalogue and docs owner.</p><button className="listbutton flex" onClick={event => executeAction("projects.docs.AskBABOOM.7", {u}, event)}>Ask BABOOM<Icon name="arrow" size={16} /></button></Card><footer className="spread muted"><span>{article.bookSource || 'ArchHub documentation'}</span><button className="button-reset" onClick={event => executeAction("projects.docs.NextTopic.8", {article,s,setSelected}, event)}>Next topic →</button></footer></article> : <div className="empty-search"><Icon name="search" size={30} /><h2>No guide matches “{query}”</h2><button className="listbutton" onClick={event => executeAction("projects.docs.ClearSearch.9", {setQuery}, event)}>Clear search</button></div>}</main></div>;
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
function projectsdocsjsxAskBABOOM4({u}, event) {
  const handler = () => u.setCompanion(true);
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
function projectsdocsjsxAskBABOOM7({u}, event) {
  const handler = () => u.setCompanion(true);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdocsjsxNextTopic8({article,s,setSelected}, event) {
  const handler = () => {
              const i = s.docs.findIndex(d => d.id === article.id);
              setSelected(s.docs[(i + 1) % s.docs.length].id);
            };
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
  "projects.docs.AskBABOOM.4": "projectsdocsjsxAskBABOOM4",
  "projects.docs.OpenOnCanvas.5": "projectsdocsjsxOpenOnCanvas5",
  "projects.docs.OpenInTheApp.6": "projectsdocsjsxOpenInTheApp6",
  "projects.docs.AskBABOOM.7": "projectsdocsjsxAskBABOOM7",
  "projects.docs.NextTopic.8": "projectsdocsjsxNextTopic8",
  "projects.docs.ClearSearch.9": "projectsdocsjsxClearSearch9"
};
window.registerActions(PROJECT_ACTIONS, {projectsdocsjsxSetSelectedDId1,projectsdocsjsxNodeReference2,projectsdocsjsxGlossary3,projectsdocsjsxAskBABOOM4,projectsdocsjsxOpenOnCanvas5,projectsdocsjsxOpenInTheApp6,projectsdocsjsxAskBABOOM7,projectsdocsjsxNextTopic8,projectsdocsjsxClearSearch9});
})();
