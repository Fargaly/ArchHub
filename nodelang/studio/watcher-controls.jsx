// Precision controls for the existing Watcher node; edits stay pending until Approve.
(() => {
  const {
    api,
    useData,
    D,
    Btn
  } = window.UI;
  function WatcherDimensions() {
    const s = useData(),
      actionState = window.UI.useAction(),
      w = s.watcher;
    function handleWatchercontrolsjsx1(d) {
      return actionState.run(() => api.removeDimension(d.id));
    }
    const ACTIONS = {
      "watcher-controls.1": "handleWatchercontrolsjsx1"
    };
    function dispatch(id, ...args) {
      return window.UI.bindActions(ACTIONS, {
        handleWatchercontrolsjsx1
      })(id, ...args);
    }
    return <section className="watcher-dimensions" aria-label="Wall dimensions"><window.UI.ActionStatus action={actionState} />
      <div className="spread"><h3>{w.elementLabel || w.host || 'Selected wall'}</h3><span className="eyebrow">Dimensions</span></div>
      <label className="precision-row"><span>Offset</span><span className="flex"><input aria-label="Wall offset" type="number" step="50" value={Math.round((w.pendingY - w.wallY) * 15)} onChange={(e) => actionState.run(async () => await api.setWatcherDimension('offset', Number(e.target.value)))} /><small>mm</small></span></label>
      <label className="precision-row"><span>Length</span><span className="flex"><input aria-label="Wall length" type="number" min="300" step="100" value={w.lengthMm} onChange={(e) => actionState.run(async () => await api.setWatcherDimension('length', Number(e.target.value)))} /><small>mm</small></span></label>
      <label className="precision-row"><span>Thickness</span><span className="flex"><select aria-label="Wall thickness" value={w.thicknessMm} onChange={(e) => actionState.run(async () => await api.setWatcherDimension('thickness', Number(e.target.value)))}>{[100, 150, 200, 250, 300, 400].map((v) => <option key={v} value={v}>{v}</option>)}</select><small>mm</small></span></label>
      <label className="precision-row"><span>Dimension</span><select aria-label="Dimension alignment" value={w.dimensionAlignment} onChange={(e) => actionState.run(() => api.setWatcherOptions({
          dimensionAlignment: e.target.value
        }))}>{['Aligned', 'Horizontal', 'Vertical'].map((v) => <option key={v}>{v}</option>)}</select></label>
      <div className="precision-row"><span>Snap to grid</span><D.Toggle label="Snap to grid" checked={w.snap} onCheckedChange={(v) => actionState.run(() => api.setWatcherOptions({
          snap: v
        }))} /></div>
      <label className="precision-row"><span>Grid spacing</span><span className="flex"><input aria-label="Grid spacing" type="number" min="1" step="10" value={w.gridMm} onChange={(e) => actionState.run(() => api.setWatcherOptions({
            gridMm: Number(e.target.value)
          }))} /><small>mm</small></span></label>
      <div className="precision-row"><span>Orthogonal</span><D.Toggle label="Orthogonal" checked={w.orthogonal} onCheckedChange={(v) => actionState.run(() => api.setWatcherOptions({
          orthogonal: v
        }))} /></div>
      <div className="precision-row"><span>Show dimensions</span><D.Toggle label="Show dimensions" checked={w.showDimensions} onCheckedChange={(v) => actionState.run(() => api.setWatcherOptions({
          showDimensions: v
        }))} /></div>
      {w.dimensions.length > 0 && <div className="dimension-list">{w.dimensions.map((d) => <div className="spread" key={d.id}><span className="mono">{Math.round(d.valueMm)} mm</span><Btn sm ghost aria-label={'Remove dimension ' + d.id} title="Remove dimension" onClick={(event) => dispatch("watcher-controls.1", d, event)}><window.AHIcon name="trash" size={13} /></Btn></div>)}</div>}
    </section>;
  }
  window.UI.WatcherDimensions = WatcherDimensions;
})();
