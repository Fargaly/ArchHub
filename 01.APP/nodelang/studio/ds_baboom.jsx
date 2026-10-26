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
        }}>Availability · not agent activity</span></div>{s.providers.map(p => <div key={p.id} className="flex row"><Av id={p.id} /><div className="fill"><h3>{p.name}</h3><span className="provider-state"><i className={'status-dot ' + (p.signedIn===false ? 'off' : '')} />{p.availability||p.presence||'Availability not reported'}{!p.availability?.includes(p.authentication||'Sign-in not checked')&&<> · {p.authentication||'Sign-in not checked'}</>}</span></div>{typeof p.enabled==='boolean'&&api.supportsAction?.('setProviderEnabled')===true ? <window.AH_DS.Toggle variant="settings" label={p.name + ' enabled'} checked={p.enabled} onCheckedChange={v => u.act(() => api.setProviderEnabled(p.id, v))} /> : <small className="muted">Availability not reported</small>}</div>)}</Card>;
  }
  window.UI.Providers = Providers;
})();
