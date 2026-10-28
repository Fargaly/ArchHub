// Social is a node surface; accounts, inbox, drafts and approvals share api.js.
(() => {
  // WIRE-social: declarative command bindings consumed by the admission compiler and dispatcher.
  const WIRE_SOCIAL_ACTIONS = {"wire.social.account":"wire.act",
  "wire.social.1": "wire.act",
  "wire.social.2": "wire.act",
  "wire.social.3": "wire.act",
  "wire.social.4": "wire.act",
  "wire.social.5": "wire.act",
  "wire.social.6": "wire.act",
  "wire.social.7": "wire.act",
  "wire.social.8": "wire.act",
  "wire.social.9": "wire.act",
  "wire.social.10": "wire.act",
  "wire.social.11": "wire.act",
  "wire.social.12": "wire.act",
  "wire.social.13": "wire.act",
  "wire.social.14": "wire.act",
  "wire.social.15": "wire.act",
  "wire.social.16": "wire.act",
  "wire.social.17": "wire.act",
  "wire.social.18": "wire.act",
  "wire.social.19": "wire.act",
  "wire.social.20": "wire.act",
  "wire.social.21": "wire.act",
  "wire.social.22": "wire.act",
  "wire.social.23": "wire.act",
  "wire.social.24": "wire.act",
  "wire.social.25": "wire.act",
  "wire.social.26": "wire.act",
  "wire.social.27": "wire.act",
  "wire.social.retry": "wire.retry"
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
      Empty
    } = window.UI,
    Icon = window.AHIcon;
  const tabs = ['Office page', 'Inbox', 'Drafts', 'Scheduled', 'Rules', 'Digest', 'Read', 'Tutorials'];
  function Social() {
    const wire = window.UI.useWireSocial();
    function dispatch(id, callback) {
      if (WIRE_SOCIAL_ACTIONS[id] === 'wire.retry') return callback();
      if (WIRE_SOCIAL_ACTIONS[id] !== 'wire.act') throw Error('Refresh this screen to reload its action registry.');
      return wire.act(callback);
    }
    const s = useData(),
      u = useApp(),
      social = s.social;
    const [tab, setTab] = React.useState('Office page'),
      [platform, setPlatform] = React.useState('All'),
      [selected, setSelected] = React.useState(social.inbox[0]?.id),
      [reply, setReply] = React.useState(''),
      [editor, setEditor] = React.useState(null),
      [officeEdit, setOfficeEdit] = React.useState(false),
      [source, setSource] = React.useState(''),
      [kind, setKind] = React.useState('Web'),
      [tutorial, setTutorial] = React.useState({
        title: '',
        description: '',
        playlist: ''
      });
    const platforms = ['LinkedIn', 'Instagram', 'Facebook', 'WhatsApp Business', 'X', 'TikTok', 'YouTube'],
      inbox = social.inbox.filter(m => platform === 'All' || m.platform === platform),
      drafts = social.drafts.filter(d => d.status !== 'Archived' && (platform === 'All' || d.platform === platform)),
      message = social.inbox.find(m => m.id === selected);
    const begin = () => {
      setEditor({
        platform: platform === 'All' ? 'LinkedIn' : platform,
        kind: 'post',
        title: '',
        text: '',
        schedule: ''
      });
      setTab('Drafts');
    };
    const review = async id => {
      const card = await wire.call(() => api.proposeSocialDraft(id));
      if (card) { u.setTask(card.id); u.go('workshop'); }
    };
    const select = m => {
      setSelected(m.id);
      setReply('');
      wire.call(() => api.readSocialMessage(m.id));
    };
    return <div className="social-layout" data-screen="social"><section aria-label="Action result" aria-live="polite">
      {wire.status === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {wire.status === 'empty' && <p>No saved content in this workflow.</p>}
      {wire.status === 'loaded' && <p role="status">{wire.result?.title || wire.result?.message || wire.result?.status || wire.result?.phase || wire.result?.id || ''}</p>}
      {wire.status === 'error' && <div role="alert"><p>{wire.message}</p><Btn onClick={() => dispatch("wire.social.retry",wire.retry)}>Retry</Btn></div>}
    </section><aside className="pane social-side"><div className="flex"><Icon name="workshop" /><h2>Social media</h2></div><button className="office-chip" onClick={event => dispatch("wire.social.1", () => (() => {
          setTab('Office page');
          setPlatform('All');
        })(event))}><span className="source-icon"><Icon name="canvas" /></span><span><b>{social.office.name}</b><small>Your office page</small></span></button><div className="spread label"><span>ACCOUNTS</span><button className="icon-button" title="Connection settings" aria-label="Social connection settings" onClick={event => dispatch("wire.social.2", () => (() => u.go('settings/Connections'))(event))}><Icon name="settings" size={15} /></button></div><button className="listbutton spread" aria-selected={platform === 'All'} onClick={event => dispatch("wire.social.3", () => (() => setPlatform('All'))(event))}><span>All accounts</span><span className="mono muted">{platforms.length}</span></button>{platforms.map(name => {
          const c = s.connections.find(c => c.name === name);
          const provider = {LinkedIn:'linkedin',Instagram:'instagram',Facebook:'facebook','WhatsApp Business':'whatsapp',X:'x',TikTok:'tiktok',YouTube:'youtube'}[name];
          return <div className="account-row" key={name}><button className="listbutton flex" aria-selected={platform === name} onClick={event => dispatch("wire.social.4", () => (() => setPlatform(name))(event))}><i className={'status-dot ' + (!c?.connected ? 'off' : '')} /><span>{name}</span></button><button className="icon-button" aria-label={(c?.connected ? 'Manage ' : 'Connect ') + name} title={c?.connected ? 'Manage account' : 'Connect with your account'} onClick={event => dispatch("wire.social.5", () => (() => c?.connected ? u.show('Connection', {
              id: c.id
            }) : wire.call(() => api.setConnection(c?.id || provider, {
              connected: true
            })))(event))}><Icon name={c?.connected ? 'more' : 'plus'} size={14} /></button>{c && <small role="status">{c.state}{c.blocker ? ' · '+c.blocker : ''}</small>}{c?.state==='choosing' && <div role="group" aria-label={'Choose '+name+' account'}>{(c.accounts||[]).map(account=><Btn sm key={account.id} onClick={()=>dispatch('wire.social.account',()=>wire.call(()=>api.finishSocialConnection(provider,account.id)))}>{account.name||account.id}</Btn>)}</div>}</div>;
        })}<div className="social-side-bottom"><span className="status-dot" /> Your review comes before sending<button className="listbutton flex" onClick={event => dispatch("wire.social.6", () => (async () => {
            await wire.call(() => api.addNode('Social media'));
            u.go('canvas');
          })(event))}><Icon name="canvas" size={16} />Open as a node</button></div></aside><main className="page social-main"><Heading title={social.office.name + ' · social'} sub={platform === 'All' ? 'One view of your office page, conversations and content.' : platform + ' · ' + (s.connections.find(c => c.name === platform)?.connected ? 'Connected' : 'Ready to connect')}><Btn sm ghost aria-label="New social post" title="New post" onClick={event => dispatch("wire.social.7", () => (begin)(event))}><Icon name="plus" /></Btn><Btn sm onClick={event => dispatch("wire.social.8", () => (() => u.go('settings/Connections'))(event))}>Settings</Btn></Heading><div className="social-tabs">{tabs.map(t => <button className="tab-button" key={t} aria-pressed={tab === t} onClick={event => dispatch("wire.social.9", () => (() => setTab(t))(event))}>{t}{t === 'Inbox' && social.inbox.some(m => m.unread) && <i />}</button>)}</div>
  {tab === 'Office page' && <><Card className="office-cover"><div className="eyebrow">Architecture · Engineering · Design</div><h1>{social.office.name}</h1><p>{social.office.headline}</p><div className="flex"><span className="status-dot" /><span>Your office, across {platforms.length} channels</span></div></Card><div className="social-stats">{[['Inbox', social.inbox.filter(m => m.unread).length, 'Unread conversations'], ['Drafts', social.drafts.filter(d => d.status === 'Draft').length, 'Ready for review'], ['Scheduled', social.drafts.filter(d => d.status === 'Scheduled').length, 'Scheduled posts']].map(([name, value, label]) => <button key={name} onClick={event => dispatch("wire.social.10", () => (() => setTab(name))(event))}><span className="mono">{value}</span><span>{label}</span><Icon name="arrow" size={16} /></button>)}</div><Card style={{
            padding: 22
          }}><div className="spread"><h2>Office profile</h2><Btn sm onClick={event => dispatch("wire.social.11", () => (() => setOfficeEdit(v => !v))(event))}>{officeEdit ? 'Close' : 'Edit'}</Btn></div>{officeEdit ? <div className="grid" style={{
              marginTop: 18
            }}>{[['name', 'Office name'], ['headline', 'Headline'], ['bio', 'About the office'], ['website', 'Website']].map(([key, label]) => <label className="grid" key={key}>{label}<input aria-label={label} value={social.office[key]} onChange={event => wire.act(() => (e => wire.call(() => api.updateOfficePage({
                  [key]: e.target.value
                })))(event))} /></label>)}</div> : <><p className="muted" style={{
                margin: '16px 0'
              }}>{social.office.bio}</p><span className="mono muted">{social.office.website}</span></>}</Card></>}
  {tab === 'Inbox' && <><div className="spread section-heading"><span className="muted">{inbox.length} conversations {social.triaged ? '· triaged' : ''}</span><Btn sm title="Triage inbox" aria-label="Triage inbox" onClick={event => dispatch("wire.social.12", () => (() => wire.call(api.triageSocialInbox))(event))}><Icon name="arrange" size={16} /></Btn></div><div className="social-inbox"><Card>{inbox.map(m => <button className="inbox-message" key={m.id} aria-selected={selected === m.id} onClick={event => dispatch("wire.social.13", () => (() => select(m))(event))}><div className="spread"><b>{m.from}</b>{m.unread && <i className="status-dot" />}</div><span className="muted">{m.platform} · {m.priority}</span><p>{m.text}</p></button>)}{!inbox.length && <Empty>No conversations in this account.</Empty>}</Card><Card className="reply-card">{message ? <><div className="spread"><h2>{message.from}</h2><Chip>{message.platform}</Chip></div><p>{message.text}</p><div className="reply-context"><Icon name="shield" size={16} /><span>Reply follows this group’s rules. Review before sending.</span></div><textarea aria-label="Social reply" rows={5} placeholder="Write your reply…" value={reply} onChange={event => wire.act(() => (e => setReply(e.target.value))(event))} /><Btn p disabled={!reply.trim()} onClick={event => dispatch("wire.social.14", () => (async () => {
                  const d = await wire.call(() => api.replySocialMessage(message.id, reply));
                  if (d) {
                    setReply('');
                    await review(d.id);
                  }
                })(event))}>Review reply</Btn></> : <Empty>Choose a conversation.</Empty>}</Card></div></>}
  {(tab === 'Drafts' || tab === 'Scheduled') && <>{editor ? <Card className="social-editor"><div className="spread"><h2>{editor.id ? 'Edit draft' : 'New post'}</h2><Btn sm ghost aria-label="Close post editor" onClick={event => dispatch("wire.social.15", () => (() => setEditor(null))(event))}>×</Btn></div><div className="social-editor-meta"><label className="grid">Account<select aria-label="Post account" value={editor.platform} onChange={event => wire.act(() => (e => setEditor({
                  ...editor,
                  platform: e.target.value
                }))(event))}>{platforms.map(name => <option key={name}>{name}</option>)}</select></label><label className="grid">When<input aria-label="Post schedule" type="datetime-local" value={editor.schedule || ''} onChange={event => wire.act(() => (e => setEditor({
                  ...editor,
                  schedule: e.target.value
                }))(event))} /></label></div><label className="grid">Title<input aria-label="Post title" placeholder="A clear title for this post" value={editor.title || ''} onChange={event => wire.act(() => (e => setEditor({
                ...editor,
                title: e.target.value
              }))(event))} /></label><textarea aria-label="Post text" rows={6} placeholder="Tell the story…" value={editor.text} onChange={event => wire.act(() => (e => setEditor({
              ...editor,
              text: e.target.value
            }))(event))} />{editor.platform === 'YouTube' && <Chip c={A.warn}>Uploads stay private until Google audit</Chip>}<div className="spread"><span className="muted" style={{
                fontSize: 12
              }}>Nothing is posted until you approve it.</span><Btn p disabled={!editor.text.trim()} onClick={event => dispatch("wire.social.16", () => (async () => {
                const d = await wire.call(() => api.saveSocialDraft(editor));
                if (d) {
                  setEditor(null);
                  await review(d.id);
                }
              })(event))}>Review {editor.schedule ? 'schedule' : 'post'}</Btn></div></Card> : <div className="draft-grid">{drafts.filter(d => tab === 'Drafts' ? ['Draft', 'Private upload'].includes(d.status) : d.status === 'Scheduled').map(d => <Card className="social-draft" key={d.id}><div className="spread"><Chip>{d.platform}</Chip><span className="eyebrow">{d.status}</span></div><h2>{d.title || 'Reply'}</h2><p>{d.text}</p>{d.schedule && <span className="muted mono">{d.schedule.replace('T', ' · ')}</span>}{d.platform === 'YouTube' && <span className="muted" style={{
                fontSize: 11
              }}>Uploads stay private until Google audit</span>}<footer className="spread"><span className="muted">{d.kind === 'reply' ? 'Reply' : 'Office post'}</span><div className="flex"><Btn sm title="Edit draft" aria-label={'Edit ' + d.id} onClick={event => dispatch("wire.social.17", () => (() => setEditor({
                    ...d
                  }))(event))}><Icon name="edit" size={16} /></Btn><Btn sm title="Review draft" aria-label={'Review ' + d.id} onClick={event => dispatch("wire.social.18", () => (() => review(d.id))(event))}><Icon name="eye" size={16} /></Btn><Btn sm title="Archive draft" aria-label={'Archive ' + d.id} onClick={event => dispatch("wire.social.19", () => (() => wire.call(() => api.discardSocialDraft(d.id)))(event))}><Icon name="trash" size={16} /></Btn></div></footer></Card>)}<button className="new-draft-card" onClick={event => dispatch("wire.social.20", () => (begin)(event))}><Icon name="plus" size={24} /><span>New post</span></button></div>}</>}
  {tab === 'Rules' && <div className="social-rules">{social.groups.map(g => <Card key={g.id} style={{
            padding: 22
          }}><div className="spread"><div><h2>{g.name}</h2><p className="muted">{g.platform}</p></div><Icon name="shield" /></div><label className="grid" style={{
              margin: '18px 0'
            }}>Group instructions<textarea aria-label={'Rules ' + g.name} rows={3} value={g.rule} onChange={event => wire.act(() => (e => wire.call(() => api.setSocialGroupRule(g.id, {
                rule: e.target.value
              })))(event))} /></label><label className="spread">Reply style<select aria-label={'Reply style ' + g.name} value={g.replyStyle} onChange={event => wire.act(() => (e => wire.call(() => api.setSocialGroupRule(g.id, {
                replyStyle: e.target.value
              })))(event))}><option>Concise</option><option>Warm</option><option>Formal</option></select></label><div className="spread row"><span>Auto-send replies</span><D.Toggle label={'Auto-send ' + g.name} checked={g.autoSend} onCheckedChange={event => wire.act(() => (v => wire.call(() => api.setSocialGroupRule(g.id, {
                autoSend: v
              })))(event))} /></div><div className="spread row"><span>Include in digest</span><D.Toggle label={'Digest ' + g.name} checked={g.digest} onCheckedChange={event => wire.act(() => (v => wire.call(() => api.setSocialGroupRule(g.id, {
                digest: v
              })))(event))} /></div><p className="muted" style={{
              fontSize: 11,
              marginTop: 12
            }}>{g.autoSend ? 'Your auto-send rule is on for this group.' : 'Replies are drafted for your approval.'}</p></Card>)}</div>}
  {tab === 'Digest' && <Card style={{
          padding: 26,
          maxWidth: 850
        }}><div className="spread"><div className="flex"><Icon name="docs" /><h2>Your daily digest</h2></div><D.Toggle label="Daily social digest" checked={social.digest.enabled} onCheckedChange={event => wire.act(() => (v => wire.call(() => api.setSocialDigest({
              enabled: v
            })))(event))} /></div><p className="muted" style={{
            margin: '16px 0'
          }}>Project conversations, enquiries and content that need your attention.</p><label className="flex" style={{
            marginBottom: 24
          }}>Prepare at<input aria-label="Digest time" type="time" value={social.digest.time} onChange={event => wire.act(() => (e => wire.call(() => api.setSocialDigest({
              time: e.target.value
            })))(event))} /></label>{social.digest.summary && <div className="digest-summary">{social.digest.summary}</div>}<Btn p onClick={event => dispatch("wire.social.21", () => (() => wire.call(api.generateSocialDigest))(event))}>Prepare digest</Btn></Card>}
  {tab === 'Read' && <div className="grid"><Card style={{
            padding: 22
          }}><Heading title="Read the source" sub="Read-only connections for video, mail and project files." /><label>Read timeout (seconds)<input type="number" min="1" max="60" aria-label="Source read timeout" value={social.sourceReadSeconds ?? ''} onChange={event=>wire.act(()=>api.setSourceReadSeconds(Number(event.target.value)))}/></label><div className="flex"><select aria-label="Content kind" value={kind} onChange={event => wire.act(() => (e => setKind(e.target.value))(event))}>{['Web', 'Video', 'Mail', 'File'].map(v => <option key={v}>{v}</option>)}</select><input aria-label="Content source" className="fill" placeholder={kind === 'Video' ? 'Video link or topic' : 'Project file or message topic'} value={source} onChange={event => wire.act(() => (e => setSource(e.target.value))(event))} /><Btn p disabled={!source.trim()} onClick={event => dispatch("wire.social.22", () => (() => wire.call(() => api.readContentSource({
                kind,
                url: source
              })))(event))}>Read</Btn></div><div className="flex" style={{
              marginTop: 14
            }}>{['Search', 'Details', 'Comments'].map(operation => <Btn sm disabled={!source.trim()} key={operation} onClick={event => dispatch("wire.social.23", () => (() => wire.call(() => api.readYoutubeData(source, operation)))(event))}>{operation}</Btn>)}</div>{social.videoData && <div style={{
              marginTop: 15
            }}><h3>{social.videoData.operation}</h3>{social.videoData.rows.map((r, i) => <div className="row" key={i}><b>{r.title}</b><p className="muted">{r.detail}</p><small>{r.source}</small></div>)}</div>}<p className="muted" style={{
              fontSize: 11,
              marginTop: 14
            }}>YouTube understanding and read-only data · Gmail, Drive and Calendar use the same Google sign-in · social feeds use your signed-in browser connection.</p></Card>{social.research.map(r => <Card key={r.id} style={{
            padding: 22
          }}><div className="spread"><h2>{r.title}</h2><Chip c={A.ok}>{r.status}</Chip></div><p style={{
              margin: '15px 0'
            }}>{r.summary}</p><div className="read-result"><section><h3>Source text</h3>{r.transcript.map((t, i) => <p key={i}><span className="mono muted">{String(i + 1).padStart(2, '0')}</span> {t}</p>)}</section><section><h3>Source frames</h3>{r.keyFrames.map((t, i) => <div key={t} className="read-keyframe"><Icon name={['canvas', 'eye', 'check'][i]} />{t}</div>)}</section></div><button className="listbutton flex" onClick={event => dispatch("wire.social.24", () => (async () => {
              await wire.call(() => api.addNode(kind === 'Video' ? 'Read video' : kind === 'Mail' ? 'Read mail' : 'Read file'));
              u.go('canvas');
            })(event))}>Open as a node<Icon name="arrow" size={16} /></button></Card>)}</div>}
  {tab === 'Tutorials' && <div className="grid"><Card className="social-editor"><Heading title="Tutorial video" sub="A guided recording, captions and one reviewed upload." /><label className="grid">Title<input aria-label="Tutorial title" value={tutorial.title} onChange={event => wire.act(() => (e => setTutorial({
                ...tutorial,
                title: e.target.value
              }))(event))} /></label><label className="grid">Description<textarea aria-label="Tutorial description" rows={3} value={tutorial.description} onChange={event => wire.act(() => (e => setTutorial({
                ...tutorial,
                description: e.target.value
              }))(event))} /></label><label className="grid">Playlist<input aria-label="Tutorial playlist" value={tutorial.playlist} onChange={event => wire.act(() => (e => setTutorial({
                ...tutorial,
                playlist: e.target.value
              }))(event))} /></label><div className="flex"><Chip c={A.warn}>Uploads stay private until Google audit</Chip><span className="fill" /><Btn p disabled={!tutorial.title.trim() || !tutorial.description.trim()} onClick={event => dispatch("wire.social.25", () => (() => wire.call(() => api.prepareTutorial(tutorial)))(event))}>Prepare video draft</Btn></div></Card>{social.tutorials.map(t => <Card key={t.id} style={{
            padding: 22
          }}><div className="spread"><h2>{t.title}</h2><Chip>{t.status}</Chip></div><div className="pipeline-steps">{t.stages.map((stage, i) => <span key={stage}><i>{i + 1}</i>{stage}</span>)}</div><div className="flex"><Btn sm onClick={event => dispatch("wire.social.26", () => (() => u.download('Captions', t.id))(event))}>Export</Btn><button className="listbutton" onClick={event => dispatch("wire.social.27", () => (() => {
                setPlatform('YouTube');
                setTab('Drafts');
              })(event))}>Review YouTube draft →</button></div></Card>)}</div>}
  </main></div>;
  }
  window.UI.Social = Social;
})();
