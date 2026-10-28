(() => {
  // WIRE-social: declarative command bindings consumed by the admission compiler and dispatcher.
  const WIRE_SOCIAL_ACTIONS = {
  "wire.research.surfaces.1": "wire.act",
  "wire.research.surfaces.2": "wire.act",
  "wire.research.surfaces.3": "wire.act",
  "wire.research.surfaces.4": "wire.act",
  "wire.research.surfaces.5": "wire.act",
  "wire.research.surfaces.6": "wire.act",
  "wire.research.surfaces.7": "wire.act",
  "wire.research.surfaces.8": "wire.act",
  "wire.research.surfaces.9": "wire.act",
  "wire.research.surfaces.10": "wire.act",
  "wire.research.surfaces.retry": "wire.retry"
};

  const {
      A,
      D,
      api,
      useData,
      useApp,
      Btn,
      Card,
      Chip,
      Heading,
      Table
    } = window.UI,
    Icon = window.AHIcon;
  function PrototypeReview() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData(),
      u = useApp(),
      p = s.prototype;
    return <Card style={{
      padding: 22,
      marginTop: 22
    }}><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.research.surfaces.retry",wire.retry)}>Retry</Btn></div>}
    </section><Heading title="Reference & deviation" sub="Compare against approved examples, with a visible threshold." /><div className="settings-grid"><label className="grid">Prototype<input aria-label="Prototype name" value={p.name} onChange={event => wire.act(() => (e => wire.call(() => api.setPrototype({
            name: e.target.value
          })))(event))} /></label><label className="grid">Deviation threshold<input aria-label="Prototype deviation threshold" type="number" min="0" max="1" step=".01" value={p.threshold ?? ''} onChange={event => wire.act(() => (e => wire.call(() => api.setPrototype({
            threshold: Number(e.target.value)
          })))(event))} /></label></div><label className="grid">Approved sample measurements (0–1, comma separated)<textarea aria-label="Approved sample measurements" defaultValue={p.measurements || ''} onBlur={event => { const value=event.target.value; if(value.trim())wire.act(()=>api.setPrototype({measurements:value})); }} /></label><div className="row spread"><span>{p.samples} approved samples · baseline {p.baseline}</span><Btn sm onClick={event => dispatch("wire.research.surfaces.1", () => (() => wire.call(api.rebaselinePrototype))(event))}>Re-baseline</Btn></div><div className="row spread"><span>Use linked model</span><D.Toggle label="Use linked model" checked={p.linkedModel} onCheckedChange={event => wire.act(() => (v => wire.call(() => api.setPrototype({
          linkedModel: v
        })))(event))} /></div><div className="spread"><Chip>{p.status}</Chip><Btn p onClick={event => dispatch("wire.research.surfaces.2", () => (async () => {
          const result = await wire.call(api.checkVerdictPattern);
          if (result?.approvalId) u.show('Approve', {
            id: result.approvalId
          });
        })(event))}>Inspect pattern</Btn></div>{p.pattern && <div style={{
        marginTop: 18
      }}><h3 style={{
          color: p.pattern.startsWith('INCONCLUSIVE') ? A.warn : A.ink
        }}>{p.pattern}</h3><Table rows={p.features} /></div>}</Card>;
  }
  function Present() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData(),
      u = useApp(),
      slides = s.presentation.slides,
      [id, setId] = React.useState(slides[0]?.id),
      [mode, setMode] = React.useState('Deck');
    const slide = slides.find(r => r.id === id) || slides[0],
      index = slides.indexOf(slide);
    if(!slide)return <main className="page" data-screen="present"><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.research.surfaces.retry",wire.retry)}>Retry</Btn></div>}
    </section><Heading title="Present"><Btn p onClick={event => dispatch("wire.research.surfaces.3", () => (async()=>{const row=await wire.call(api.addSlide);if(row)setId(row.id);})(event))}>Add slide</Btn></Heading><window.UI.Empty>No slides in this workflow. Add the first slide.</window.UI.Empty></main>;
    return <main className="page" data-screen="present"><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.research.surfaces.retry",wire.retry)}>Retry</Btn></div>}
    </section><Heading title="Present" sub="Edit the story and walk through the reviewed result."><select aria-label="Presentation mode" value={mode} onChange={event => wire.act(() => (e => setMode(e.target.value))(event))}><option>Deck</option><option>Walkthrough</option></select><Btn sm onClick={event => dispatch("wire.research.surfaces.4", () => (() => u.download('Presentation'))(event))}>Export</Btn><Btn p onClick={event => dispatch("wire.research.surfaces.5", () => (async () => {
          const r = await wire.call(api.addSlide);
          if (r) setId(r.id);
        })(event))}>Add slide</Btn></Heading><div className="present-grid"><Card className="present-list">{slides.map((r, i) => <button key={r.id} className="listbutton" aria-pressed={r.id === slide.id} draggable onDragStart={e => e.dataTransfer.setData('slide', r.id)} onDragOver={e => e.preventDefault()} onDrop={e => {
            e.preventDefault();
            wire.call(() => api.reorderSlide(e.dataTransfer.getData('slide'), r.id));
          }} onClick={event => dispatch("wire.research.surfaces.6", () => (() => setId(r.id))(event))}><small className="muted">{String(i + 1).padStart(2, '0')} · {r.layout}</small><h3>{r.title}</h3></button>)}</Card><div className="grid"><Card className="present-preview" style={{
            background: slide.layout === 'Title' ? 'linear-gradient(135deg,#29221e,#141418)' : '#17171d'
          }}><span className="eyebrow">{s.graph.name}</span><h1>{slide.title}</h1><p>{slide.body}</p>{slide.artifactUrl && <img src={slide.artifactUrl} alt={slide.title} />}<div className="spread"><span className="muted">{index + 1} / {slides.length} · {mode}</span><div className="flex"><Btn sm disabled={index === 0} aria-label="Previous slide" onClick={event => dispatch("wire.research.surfaces.7", () => (() => setId(slides[index - 1].id))(event))}><Icon name="back" size={16} /></Btn><Btn sm disabled={index === slides.length - 1} aria-label="Next slide" onClick={event => dispatch("wire.research.surfaces.8", () => (() => setId(slides[index + 1].id))(event))}><Icon name="arrow" size={16} /></Btn></div></div></Card><Card style={{
            padding: 20
          }}><div className="settings-grid"><label className="grid">Title<input aria-label="Slide title" value={slide.title} onChange={event => wire.act(() => (e => wire.call(() => api.editSlide(slide.id, {
                  title: e.target.value
                })))(event))} /></label><label className="grid">Layout<select aria-label="Slide layout" value={slide.layout} onChange={event => wire.act(() => (e => wire.call(() => api.editSlide(slide.id, {
                  layout: e.target.value
                })))(event))}>{['Title', 'Plan', 'Result'].map(x => <option key={x}>{x}</option>)}</select></label></div><label className="grid" style={{
              marginTop: 14
            }}>Story<textarea aria-label="Slide story" value={slide.body} onChange={event => wire.act(() => (e => wire.call(() => api.editSlide(slide.id, {
                body: e.target.value
              })))(event))} /></label><Btn sm disabled={slides.length === 1} onClick={event => dispatch("wire.research.surfaces.9", () => (() => wire.call(() => api.removeSlide(slide.id)))(event))}>Remove slide</Btn></Card></div></div></main>;
  }
  function ModelAvailability() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData();
    return <Card style={{
      padding: 20,
      marginTop: 22
    }}><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.research.surfaces.retry",wire.retry)}>Retry</Btn></div>}
    </section><div className="spread"><div><h3>Model availability</h3><p className="muted">Check changes without replacing your chosen default.</p></div><Btn sm onClick={event => dispatch("wire.research.surfaces.10", () => (() => wire.call(api.refreshModelRoster))(event))}>Refresh models</Btn></div>{s.modelNotice && <p role="status" style={{
        marginTop: 14
      }}>{s.modelNotice}</p>}</Card>;
  }
  Object.assign(window.UI, {
    PrototypeReview,
    Present,
    ModelAvailability
  });
})();
