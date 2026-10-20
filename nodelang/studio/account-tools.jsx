(() => {
  const WIRE_ACCOUNT_TOOLS_JSX_ACTIONS = {
  "settings.account-tools.AccountIdentityAction0": "AccountIdentityAction0",
  "settings.account-tools.AccountIdentityAction1": "AccountIdentityAction1",
  "settings.account-tools.AccountIdentityAction2": "AccountIdentityAction2",
  "settings.account-tools.BillingAccountAction0": "BillingAccountAction0",
  "settings.account-tools.BillingAccountAction1": "BillingAccountAction1",
  "settings.account-tools.BillingAccountAction2": "BillingAccountAction2",
  "settings.account-tools.BillingAccountAction3": "BillingAccountAction3",
  "settings.account-tools.BillingAccountAction4": "BillingAccountAction4",
  "settings.account-tools.BillingAccountAction5": "BillingAccountAction5",
  "settings.account-tools.BillingAccountAction6": "BillingAccountAction6",
  "settings.account-tools.BillingAccountAction7": "BillingAccountAction7",
  "settings.account-tools.BillingAccountAction8": "BillingAccountAction8",
  "settings.account-tools.BillingAccountAction9": "BillingAccountAction9"
};
  const {
    A,
    api,
    useData,
    useApp,
    Btn,
    Card,
    Chip,

  } = window.UI;
  function AccountIdentity() {
    const s = useData(),
      u = useApp();
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_ACCOUNT_TOOLS_JSX_ACTIONS, {AccountIdentityAction0: (event) => (() => u.show('Invite'))(event),
AccountIdentityAction1: (r, event) => (() => u.act(() => api.acceptOfficeInvitation(r.id)))(event),
AccountIdentityAction2: (r, event) => (() => u.act(() => api.declineOfficeInvitation(r.id)))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><section className="account-office"><div className="spread"><div><span className="eyebrow">YOUR OFFICE</span><h2>{s.firms.find(f => f.id === s.activeFirm)?.name}</h2><p className="muted">Your team, shared work and membership.</p></div><div className="flex"><select aria-label="Active office" value={s.activeFirm} onChange={e => u.act(() => api.selectFirm(e.target.value))}>{s.firms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select><Btn sm ghost onClick={event => runAction('settings.account-tools.AccountIdentityAction0', event)}>Invite</Btn></div></div><details style={{
        marginTop: 18
      }}><summary>Office invitations</summary>{s.officeInvitations.map(r => <div className="row" key={r.id}><div className="spread"><h3>{r.office}</h3><Chip c={r.status === 'Accepted' ? A.ok : A.inkSoft}>{r.status}</Chip></div><p className="muted">{r.email} · {r.role}</p><div className="flex" style={{
            marginTop: 12
          }}><Btn sm disabled={['Accepted', 'Declined', 'Expired'].includes(r.status)} onClick={event => runAction('settings.account-tools.AccountIdentityAction1', r, event)}>Accept invitation</Btn><Btn sm disabled={['Accepted', 'Declined', 'Expired'].includes(r.status)} onClick={event => runAction('settings.account-tools.AccountIdentityAction2', r, event)}>Decline invitation</Btn></div>{r.reason && <p className="muted">{r.reason}</p>}</div>)}</details></section></>;
  }
  function BillingAccount() {
    const s = useData(),
      u = useApp(),
      b = s.billing,
      m = api.getUsageSummary();
    const {runAction, actionState, retryAction} = window.UI.useRegisteredActions(WIRE_ACCOUNT_TOOLS_JSX_ACTIONS, {BillingAccountAction0: (event) => (() => u.act(api.prepareCheckout))(event),
BillingAccountAction1: (event) => (() => u.act(api.completeCheckout))(event),
BillingAccountAction2: (event) => (() => u.act(() => api.setBilling({
                checkout: null
              })))(event),
BillingAccountAction3: (event) => (() => u.act(api.retryPayment))(event),
BillingAccountAction4: (event) => (() => u.act(api.downgradeBilling))(event),
BillingAccountAction5: (event) => (() => u.act(api.prepareCheckout))(event),
BillingAccountAction6: (event) => (() => u.go('routing'))(event),
BillingAccountAction7: (r, event) => (() => u.download('Invoice ' + r.id))(event),
BillingAccountAction8: (event) => (() => u.act(api.refreshBilling))(event),
BillingAccountAction9: (event) => (() => u.go('access'))(event)});
    return <><window.UI.RegisteredActionStatus state={actionState} retry={retryAction} /><Card style={{
      padding: 22,
      marginTop: 20
    }}><div className="spread"><h2>Billing &amp; usage</h2><Chip>{b.status}</Chip></div><p className="muted" style={{
        margin: '12px 0'
      }}>Your account’s billing owner confirms your plan, usage and payments.</p><div className="settings-grid">{Object.entries(m).map(([key, value]) => <div className="row spread" key={key}><span>{key}</span><b>{value}</b></div>)}</div><details style={{
        marginTop: 18
      }}><summary>Plan &amp; checkout</summary><div className="grid" style={{
          marginTop: 14
        }}><label className="spread">Plan<select aria-label="Billing plan" value={b.requestedPlan} onChange={e => u.act(() => api.setBilling({
              requestedPlan: e.target.value
            }))}>{['Personal', 'Office', 'Team'].map(x => <option key={x}>{x}</option>)}</select></label><label className="spread">Billing cycle<select aria-label="Billing cycle" value={b.cycle} onChange={e => u.act(() => api.setBilling({
              cycle: e.target.value
            }))}>{['Monthly', 'Annual'].map(x => <option key={x}>{x}</option>)}</select></label><div className="spread"><span>Due today</span><b>{b.checkout?.amount ?? b.status}</b></div><Btn p onClick={event => runAction('settings.account-tools.BillingAccountAction0', event)}>Review plan</Btn>{b.checkout && <Card style={{
            padding: 16
          }}><h3>{b.checkout.plan} · {b.checkout.cycle}</h3><p className="muted">Your billing provider handles payment in your browser. Refresh to read the confirmed plan.</p><Chip>{b.checkout.status}</Chip><div className="flex" style={{
              marginTop: 12
            }}><Btn p onClick={event => runAction('settings.account-tools.BillingAccountAction1', event)}>Refresh payment confirmation</Btn><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction2', event)}>Cancel checkout</Btn></div></Card>}</div></details>{b.status === 'Past due' && <div className="row"><h3>Payment needs attention</h3><p className="muted">Your data stays available during the grace period. Retry or return to the free plan.</p><div className="flex" style={{
          marginTop: 14
        }}><Btn p onClick={event => runAction('settings.account-tools.BillingAccountAction3', event)}>Retry payment</Btn><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction4', event)}>Use free plan</Btn></div></div>}{b.limitReached && <div className="row"><h3>Usage limit reached</h3><p className="muted">Free work remains available. Choose a plan or adjust your usage cap.</p><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction5', event)}>Review upgrade</Btn><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction6', event)}>Adjust usage cap</Btn></div>}<details style={{
        marginTop: 18
      }}><summary>Invoices</summary>{b.invoices.length ? b.invoices.map(r => <div className="spread row" key={r.id}><span>{r.number} · {r.plan} · ${r.amount}</span><Chip>{r.status}</Chip><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction7', r, event)}>Download invoice</Btn></div>) : <p className="muted">No invoices were returned. Open the billing provider to view your invoice history.</p>}</details><div className="flex" style={{
        marginTop: 18
      }}><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction8', event)}>Refresh billing</Btn><Btn sm onClick={event => runAction('settings.account-tools.BillingAccountAction9', event)}>Plan &amp; access</Btn></div></Card></>;
  }
  function TurnUsage({
    message
  }) {
    if (!message.usage) return null;
    const r = message.usage;
    return <small className="muted mono" style={{
      display: 'block',
      fontSize: 10,
      marginTop: 8
    }}>{r.inputTokens} in · {r.outputTokens} out · ${r.cost.toFixed(2)} · {r.connectorCalls} program calls</small>;
  }
  Object.assign(window.UI, {
    AccountIdentity,
    BillingAccount,
    TurnUsage
  });
})();
