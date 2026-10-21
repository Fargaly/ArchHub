(() => {
  function bindActions(registry, handlers) {
    for (const name of Object.values(registry)) {
      if (typeof handlers[name] !== 'function') throw Error('Missing action handler: ' + name);
    }
    return (id, ...args) => {
      if (!Object.hasOwn(registry, id)) throw Error('Unknown action: ' + id);
      return handlers[registry[id]](...args);
    };
  }
  function useAction() {
    const [request, setRequest] = React.useState({
      state: 'empty',
      result: null,
      error: ''
    });
    const pending = React.useRef(false),
      last = React.useRef(null);
    const run = async (fn) => {
      if (pending.current) return null;
      last.current = fn;
      pending.current = true;
      setRequest({
        state: 'waiting',
        result: null,
        error: ''
      });
      return Promise.resolve().then(fn).then((result) => {
        if (result?.ok === false) throw Error(result.error || result.message || result.reason || 'Owner refused the action. Review its parameters and retry.');
        setRequest({
          state: result == null ? 'empty' : 'loaded',
          result,
          error: ''
        });
        return result;
      }).catch((failure) => {
        setRequest({
          state: 'error',
          result: null,
          error: failure.message || String(failure)
        });
        return null;
      }).finally(() => {
        pending.current = false;
      });
    };
    return {
      ...request,
      run,
      retry: () => last.current && run(last.current)
    };
  }
  function ActionStatus({
    action,
    empty = 'No result yet. Run an action to read its owner.'
  }) {
    const ACTIONS = {
      "wire-rest.retry": "retry"
    };
    function dispatch(id, ...args) {
      return bindActions(ACTIONS, {
        retry: action.retry
      })(id, ...args);
    }
    return <div aria-live="polite" aria-busy={action.state === 'waiting'}>
      {action.state === 'waiting' && <p role="status">Waiting for the owner…</p>}
      {action.state === 'empty' && <p className="muted">{empty}</p>}
      {action.state === 'loaded' && <details><summary>Owner result</summary><pre>{JSON.stringify(action.result, null, 2)}</pre></details>}
      {action.state === 'error' && <div role="alert"><p>{action.error}</p><button onClick={() => dispatch('wire-rest.retry')}>Retry action</button></div>}
    </div>;
  }
  Object.assign(window.UI, {
    bindActions,
    useAction,
    ActionStatus
  });
  const {
      D,
      api,
      useData,
      useApp,
      Btn,
      Card
    } = window.UI,
    Icon = window.AHIcon;
  function AnswerWidget({
    message
  }) {
    const actionState = window.UI.useAction(),
      w = message.widget;
    if (!w) return null;
    function handleAnswerwidgetsjsx1(option) {
      return actionState.run(() => api.setAnswerWidget(message.id, {
        selected: option
      }));
    }
    function handleAnswerwidgetsjsx2() {
      return actionState.run(() => api.setAnswerWidget(message.id, {
        applied: true
      }));
    }
    const ACTIONS = {
      "answer-widgets.1": "handleAnswerwidgetsjsx1",
      "answer-widgets.2": "handleAnswerwidgetsjsx2"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleAnswerwidgetsjsx1,
        handleAnswerwidgetsjsx2
      })(id, ...args);
    }
    return <Card style={{
      padding: 16,
      borderColor: '#49413c'
    }}><window.UI.ActionStatus action={actionState} /><div className="spread"><h3>{w.title}</h3><Icon name="canvas" size={16} /></div><div className="flex" style={{
        margin: '14px 0'
      }}>{w.options.map((option) => <button className="tab-button" key={option} aria-pressed={w.selected === option} onClick={(event) => dispatch("answer-widgets.1", option, event)}>{option}</button>)}</div><label className="spread">Confidence threshold<input aria-label="Answer confidence threshold" type="range" min="0" max="1" step=".05" value={w.threshold} onChange={(e) => actionState.run(() => api.setAnswerWidget(message.id, {
          threshold: Number(e.target.value)
        }))} /><span className="mono muted">{Math.round(w.threshold * 100)}%</span></label><div className="spread row"><span>Keep hosted elements</span><D.Toggle label="Answer keep hosted elements" checked={w.keepHosted} onCheckedChange={(v) => actionState.run(() => api.setAnswerWidget(message.id, {
          keepHosted: v
        }))} /></div><div className="spread"><small className="muted">{w.applied ? 'Selection applied to the plan' : 'Your choice remains editable'}</small><Btn p sm onClick={(event) => dispatch("answer-widgets.2", event)}>Use selection</Btn></div></Card>;
  }
  function ActionEvidence({
    id
  }) {
    const s = useData(),
      u = useApp(),
      actionState = window.UI.useAction(),
      c = s.approvals.find((c) => c.id === id);
    function handleAnswerwidgetsjsx3() {
      return u.show('Approve', {
        id
      });
    }
    function handleAnswerwidgetsjsx4() {
      return u.show('Contest decision', {
        title: c.title
      });
    }
    const ACTIONS = {
      "answer-widgets.3": "handleAnswerwidgetsjsx3",
      "answer-widgets.4": "handleAnswerwidgetsjsx4"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleAnswerwidgetsjsx3,
        handleAnswerwidgetsjsx4
      })(id, ...args);
    }
    return c ? <div className="grid"><window.UI.ActionStatus action={actionState} /><h2>{c.title}</h2><p className="muted">This decision uses the reviewed inputs and the proposed differences shown in the card.</p><div className="row spread"><b>Target</b><span>{c.target || s.files.find((f) => f.id === s.activeFile)?.name}</span></div><div className="row spread"><b>Changes</b><span>{c.rows.length} reviewed rows</span></div><h3>Evidence and source</h3>{c.rows.map((r, i) => <div className="row" key={i}><b>{r.element}</b><p className="muted">{r.before} → {r.after}</p></div>)}<div className="flex"><Btn p onClick={(event) => dispatch("answer-widgets.3", event)}>Back to review</Btn>{api.supportsAction?.('contestDecision') !== false && <Btn sm onClick={(event) => dispatch("answer-widgets.4", event)}>Request another review</Btn>}</div></div> : null;
  }
  Object.assign(window.UI, {
    AnswerWidget,
    ActionEvidence
  });
})();
