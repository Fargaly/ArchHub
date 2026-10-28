// DSYS-079: the existing people + agents list, meeting actions and editable
// learned rules. Shares the Workshop task store; never another channel.
(() => {
  // WIRE-social: declarative command bindings consumed by the admission compiler and dispatcher.
  const WIRE_SOCIAL_ACTIONS = {"wire.memory.save":"wire.act","wire.memory.cancel":"wire.act",
  "wire.ds_colleagues.1": "wire.act",
  "wire.ds_colleagues.2": "wire.act",
  "wire.ds_colleagues.3": "wire.act",
  "wire.ds_colleagues.4": "wire.act",
  "wire.ds_colleagues.5": "wire.act",
  "wire.ds_colleagues.6": "wire.act",
  "wire.ds_colleagues.7": "wire.act",
  "wire.ds_colleagues.8": "wire.act",
  "wire.ds_colleagues.9": "wire.act",
  "wire.ds_colleagues.retry": "wire.retry"
};

  const {

    api,
    useData,
    useApp,
    Btn,
    Card,
    Av,
    Heading,
    Composer,
    Empty
  } = window.UI;
  function Colleagues() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData(),
      u = useApp();
    return <div data-screen="colleagues" style={{
      display: 'grid',
      gridTemplateColumns: '340px minmax(0,1fr)',
      minHeight: 0
    }}><aside className="pane" style={{
        padding: 18
      }}><Heading title={s.profile.firm || "Team"} /><div className="label" style={{
          marginBottom: 14
        }}>AGENTS</div>{s.providers.map(p => <button className="listbutton flex" key={p.id} onClick={event => dispatch("wire.ds_colleagues.1", () => (() => u.show('Agent', {
          id: p.id
        }))(event))}><Av id={p.id} /><span><b>{p.name}</b><p className="muted" style={{
              fontSize: 12
            }}>{p.presence || (p.sessions?.length ? 'Session discovered' : p.signedIn ? 'Signed in' : 'No session reported')}</p></span></button>)}<div className="label" style={{
          margin: '22px 0 8px'
        }}>TEAM</div>{s.people.map(p => <button className="listbutton flex" key={p.id} onClick={event => dispatch("wire.ds_colleagues.2", () => (() => u.show('Teammate', {
          id: p.id
        }))(event))}><Av id={p.name} /><span><b>{p.name}</b><p className="muted" style={{
              fontSize: 12
            }}>{p.task}</p></span></button>)}</aside><main className="page"><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Loading team…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.ds_colleagues.retry",wire.retry)}>Retry</Btn></div>}
    </section><Heading title={s.meeting.title} sub="People and agents finish work in the same room"><Btn p onClick={event => dispatch("wire.ds_colleagues.3", () => (() => u.go('meetings'))(event))}>Meetings</Btn><Btn onClick={event => dispatch("wire.ds_colleagues.4", () => (() => u.show('New task'))(event))}>New task</Btn></Heading><div style={{
          maxWidth: 800
        }}><Card style={{
            padding: 20,
            display: 'grid',
            gap: 18
          }}><h2>{s.meeting.title || 'Meetings'}</h2><p className="muted">Decisions and owned actions from the selected meeting.</p>{s.meeting.actions.map((text, index) => <div key={index} className="spread row"><span>{text}</span><Btn sm disabled={!s.meeting.actionOwners?.[index] || !!s.meeting.actionTasks?.[index]} onClick={event => dispatch("wire.ds_colleagues.5", () => (async () => {
                const t = await wire.call(() => api.createMeetingTask(index));
                if (t) {
                  u.setTask(t.id);
                  u.go('workshop');
                }
              })(event))}>Make task</Btn></div>)}<Btn sm ghost onClick={event => dispatch("wire.ds_colleagues.6", () => (() => u.show('Meeting notes'))(event))}>Open notes</Btn></Card><div style={{
            height: 20
          }} /><window.UI.MemoryRules /><div style={{
            height: 20
          }} /><Composer /></div></main></div>;
  }
  function MemoryRules() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData();
    const [editor,setEditor]=React.useState(null);
    React.useEffect(()=>{wire.act(api.refreshSocialMemory);},[s.graph.id]);
    return <Card style={{
      padding: 16
    }}><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Loading learned rules…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.ds_colleagues.retry",wire.retry)}>Retry</Btn></div>}
    </section><div className="spread"><h2>What ArchHub knows about you</h2><Btn sm onClick={event => dispatch("wire.ds_colleagues.7", () => (() => setEditor({id:null,text:''}))(event))}>Remember</Btn></div>{editor && <div><textarea aria-label="Learned rule" value={editor.text} onChange={event=>setEditor({...editor,text:event.target.value})}/><Btn p disabled={!editor.text.trim()} onClick={()=>dispatch('wire.memory.save',async()=>{await wire.call(()=>editor.id?api.editMemory(editor.id,editor.text):api.remember(editor.text));setEditor(null);})}>Save</Btn><Btn sm onClick={()=>dispatch('wire.memory.cancel',()=>setEditor(null))}>Cancel</Btn></div>}{s.brain.map(r => <div className="spread row" key={r.id}><div><p>{r.text}</p><span className="muted" style={{
            fontSize: 11
          }}>{r.source}</span></div><div className="flex"><Btn sm onClick={event => dispatch("wire.ds_colleagues.8", () => (() => setEditor({id:r.id,text:r.text}))(event))}>Edit</Btn><Btn sm ghost onClick={event => dispatch("wire.ds_colleagues.9", () => (() => wire.call(()=>api.forgetMemory(r.id)))(event))}>Forget</Btn></div></div>)}{!s.brain.length && <Empty>No learned rules.</Empty>}</Card>;
  }
  window.UI.Colleagues = Colleagues;
  window.UI.MemoryRules = MemoryRules;
})();
