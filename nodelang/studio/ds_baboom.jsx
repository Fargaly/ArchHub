// DSYS-085/079: the one companion; full-page conversation uses the existing
// colleagues/message/composer grammar. Routing controls remain in Settings.
(() => {
  const {

    api,
    useData,
    useApp,

    Card,
    Av,

  } = window.UI;
  function Providers() {
    const s = useData(),
      u = useApp();
    return <Card className="providers-grid"><div className="spread" style={{
        padding: '14px 16px'
      }}><h2>Providers</h2><span className="muted" style={{
          fontSize: 12
        }}>Signed in · Enabled</span></div>{s.providers.map(p => <div key={p.id} className="flex row"><Av id={p.id} /><div className="fill"><h3>{p.name}</h3><span className="provider-state"><i className={'status-dot ' + (!p.signedIn ? 'off' : '')} />{p.signedIn ? 'Signed in' : 'Signed out'} · {p.model}</span></div><window.AH_DS.Toggle variant="settings" label={p.name + ' signed in'} checked={p.signedIn} onCheckedChange={v => u.act(() => api.signInProvider(p.id, v))} /><window.AH_DS.Toggle variant="settings" label={p.name + ' enabled'} checked={p.enabled} onCheckedChange={v => u.act(() => api.setProviderEnabled(p.id, v))} /></div>)}</Card>;
  }
  window.UI.Providers = Providers;
})();
