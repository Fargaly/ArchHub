// The approved Watcher tools operate on the current source-bound graph owner.
(() => {
  const {api,useData,useApp,Btn,Card,Heading} = window.UI;
  const INK = '#ff5a4f';
  function Watcher() {
    const s=useData(),u=useApp(),w=s.watcher,action=window.UI.useAction();
    const [tool,setTool]=React.useState('Edit'),[points,setPoints]=React.useState([]),[wall,setWall]=React.useState(null);
    const svg=React.useRef(),gesture=React.useRef(null);
    function handleWatcherRetry(){return action.retry();}
    function handleWatcherRead(){return run(api.readHostAvailability);}
    function handleWatcherConnections(){return u.go('settings/Connections');}
    function handleWatcherHost(host){return run(()=>api.setWatcherHost(host));}
    function handleWatcherView(view){return run(()=>api.setWatcherView(view));}
    function handleWatcherDiscard(){return run(api.discardWatcherChanges);}
    function handleWatcherTool(name){return setTool(name);}
    function handleWatcherPropose(){return run(async()=>{const card=await api.proposeWatcherEdit();u.show('Approve',{id:card.id});});}
    function handleWatcherComment(comment){return u.show('Comment',{text:comment.text});}
    function handleWatcherWorkshop(){return u.go('workshop');}
    const ACTIONS={"watcher.retry":"handleWatcherRetry","watcher.read":"handleWatcherRead","watcher.connections":"handleWatcherConnections",
      "watcher.host":"handleWatcherHost","watcher.view":"handleWatcherView","watcher.discard":"handleWatcherDiscard",
      "watcher.tool":"handleWatcherTool","watcher.propose":"handleWatcherPropose","watcher.comment":"handleWatcherComment",
      "watcher.workshop":"handleWatcherWorkshop"};
    function dispatch(id,...args){return window.UI.bindActions(ACTIONS,{handleWatcherRetry,handleWatcherRead,handleWatcherConnections,handleWatcherHost,
      handleWatcherView,handleWatcherDiscard,handleWatcherTool,handleWatcherPropose,handleWatcherComment,handleWatcherWorkshop})(id,...args);}
    const available=name=>api.supportsAction(name);
    const run=fn=>action.run(fn);
    const xy=e=>{const p=new window.DOMPoint(e.clientX,e.clientY).matrixTransform(svg.current.getScreenCTM().inverse());return {x:p.x,y:p.y};};
    const down=e=>{
      if(e.button!==0||!w.elementId)return;
      const origin=xy(e);if(tool==='Edit'&&Math.abs(origin.y-w.pendingY)>35)return;
      gesture.current={tool,origin,points:[origin],start:w.pendingY};
      setPoints([origin]);svg.current.setPointerCapture(e.pointerId);
    };
    const move=e=>{
      const g=gesture.current;if(!g)return;
      const p=xy(e);g.points.push(p);
      if(g.tool==='Edit')setWall(g.start+p.y-g.origin.y);else setPoints([...g.points]);
    };
    const up=e=>{
      const g=gesture.current;if(!g)return;
      gesture.current=null;const p=xy(e);
      if(g.tool==='Edit')run(()=>api.editWall(g.start+p.y-g.origin.y));
      else if(g.tool==='Dimension')run(()=>api.addDimension({from:g.origin,to:p}));
      else if(g.tool==='Comment')u.show('Add comment',{...p,element:w.elementId});
      else if(g.points.length>1)run(()=>api.addMark({tool:g.tool,points:g.points}));
      setWall(null);setPoints([]);
    };
    React.useEffect(()=>{
      const key=e=>{if(e.target.matches('input,textarea,select')||e.ctrlKey)return;
        const next={e:'Edit',s:'Sketch',m:'Mark',k:'Mask',c:'Comment',d:'Dimension'}[e.key.toLowerCase()];if(next)setTool(next);};
      window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
    },[]);
    const path=points=>points.map((p,i)=>(i?'L':'M')+p.x+' '+p.y).join(' ');
    const line=w.geometry.walls[0],y=wall??w.pendingY,delta=y-w.wallY;
    const bounds=line?[Math.min(line[0],line[2])-100,Math.min(line[1],line[3])-200,Math.max(Math.abs(line[2]-line[0])+200,400),Math.max(Math.abs(line[3]-line[1])+400,600)]:[0,0,1116,895];
    return <main className="page watcher-page" data-screen="watcher">
      <Heading title="Watcher" sub={w.host||'Host source and operation evidence'}>
        <Btn disabled={action.state==='waiting'} onClick={()=>dispatch("watcher.read")}>Read source</Btn>
        <Btn onClick={()=>dispatch("watcher.connections")}>Connections</Btn>
      </Heading>
      {action.result?.operations?.length>0&&<window.UI.Table rows={action.result.operations} columns={['host','operation','status','reason']}/>}
      <div aria-live="polite" aria-busy={action.state==='waiting'}>
        {action.state==='empty'&&<p className="muted">Select one wall or line in the source, then choose its program.</p>}
        {action.state==='waiting'&&<p role="status">Waiting for the source.</p>}
        {action.state==='loaded'&&<p role="status">{action.result?.approvalKind==='watcher'?'Ready for approval':action.result?.owner?'Watcher saved':'Source availability read'}</p>}
        {action.state==='error'&&<div role="alert"><p>{action.error}</p><Btn onClick={()=>dispatch("watcher.retry")}>Retry action</Btn></div>}
      </div>
      <div className="node-canvas" style={{display:'grid',gridTemplateColumns:'minmax(0,1fr) 304px',gap:24,padding:20,overflow:'auto'}}>
        <div style={{borderRadius:14,background:'linear-gradient(180deg,#1c1c22,#17171c)',boxShadow:'0 0 0 1px #33333b,0 12px 40px #0008',overflow:'hidden'}}>
          <header className="flex" style={{padding:14}}>
            <div className="fill"><h3>Watcher · {w.elementLabel}</h3><span className="muted">{w.host} · {w.applied?'Checked':'Editing'}</span></div>
            {available('setWatcherHost')&&['Revit','AutoCAD'].map(host=><Btn key={host} sm ghost aria-pressed={w.host===host} onClick={()=>dispatch("watcher.host",host)}>{host}</Btn>)}
            {available('setWatcherView')&&<select aria-label="Watcher view" value={w.view} onChange={e=>dispatch("watcher.view",e.target.value)}>{w.views.map(view=><option key={view}>{view}</option>)}</select>}
            {available('discardWatcherChanges')&&<Btn sm onClick={()=>dispatch("watcher.discard")}>Discard changes</Btn>}
          </header>
          <div style={{position:'relative',background:'#e9e6df',minHeight:550}}>
            <svg ref={svg} aria-label="Editable plan" viewBox={bounds.join(' ')} width="100%" height="550" style={{display:'block',touchAction:'none',cursor:tool==='Edit'?'default':'crosshair'}} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={()=>{gesture.current=null;setPoints([]);setWall(null);}}>
              {w.geometry.walls.map(([x1,y1,x2,y2],i)=><line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#2b2b2b" strokeWidth="3" />)}
              {line&&delta!==0&&<line x1={line[0]} y1={line[1]+delta} x2={line[2]} y2={line[3]+delta} stroke={INK} strokeWidth="3" />}
              {w.dimensions.map(d=><g key={d.id} stroke="#765f54"><line x1={d.from.x} y1={d.from.y} x2={d.to.x} y2={d.to.y}/><text x={(d.from.x+d.to.x)/2} y={(d.from.y+d.to.y)/2-12} fill="#765f54" stroke="none">{Math.round(d.valueMm)} mm</text></g>)}
              {w.mask&&<rect x={w.mask.x} y={w.mask.y} width={w.mask.w} height={w.mask.h} fill="none" stroke={INK} strokeDasharray="8 5"/>}
              {w.marks.filter(mark=>mark.tool!=='Mask').map(mark=><path key={mark.id} d={path(mark.points)} fill="none" stroke={INK} strokeWidth={mark.tool==='Mark'?5:3}/>)}
              {points.length>1&&<path d={path(points)} fill="none" stroke={INK} strokeWidth="3"/>}
              {w.comments.map((comment,i)=><g key={comment.id} transform={`translate(${comment.x},${comment.y+(comment.element===w.elementId?delta:0)})`} role="button" tabIndex={0} aria-label={'Comment '+(i+1)} onPointerDown={e=>e.stopPropagation()} onClick={()=>dispatch("watcher.comment",comment)} onKeyDown={e=>{if(e.key==='Enter')u.show('Comment',{text:comment.text});}}><circle r="14" fill="#a088e3"/><text y="5" textAnchor="middle" fill="#fff">{i+1}</text></g>)}
            </svg>
            <div className="flex" style={{position:'absolute',left:'50%',transform:'translateX(-50%)',bottom:22,gap:4,padding:8,borderRadius:18,background:'linear-gradient(180deg,#202027,#1a1a20)'}}>
              {[['Edit','E','editWall'],['Sketch','S','addMark'],['Mark','M','addMark'],['Mask','K','addMark'],['Comment','C','addComment'],['Dimension','D','addDimension']].filter(([, ,name])=>available(name)).map(([name,key])=><button key={name} aria-label={name+' · '+key} aria-pressed={tool===name} title={name+' · '+key} onClick={()=>dispatch("watcher.tool",name)} style={{width:38,height:40,borderRadius:12,display:'grid',placeItems:'center',border:0,color:tool===name?INK:'inherit',background:tool===name?'#2f2f37':'transparent'}}><window.AHIcon name={{Edit:'edit',Sketch:'palette',Mark:'eye',Mask:'shield',Comment:'workshop',Dimension:'fit'}[name]} size={18}/></button>)}
            </div>
            {delta!==0&&available('proposeWatcherEdit')&&<Card style={{position:'absolute',bottom:116,right:18,padding:14,background:'rgba(22,22,28,.96)'}}><h3>{w.elementLabel} · move {Math.round(delta*15)} mm</h3><div className="flex"><Btn p sm onClick={()=>dispatch("watcher.propose")}>Apply to {w.host}</Btn><Btn sm onClick={()=>dispatch("watcher.discard")}>Undo</Btn></div></Card>}
          </div>
        </div>
        <aside className="pane" style={{background:'#141418',padding:14}}>
          <h3>Changes</h3><p className="muted">{w.status}</p>
          {line&&<><p>{w.elementLabel} · {Math.round(delta*15)} mm offset</p><p>{Math.round(w.lengthMm)} mm length · {Math.round(w.thicknessMm)} mm thickness</p></>}
          {w.comments.map((comment,i)=><button className="listbutton" key={comment.id} onClick={()=>dispatch("watcher.comment",comment)}>COMMENT · {i+1}<p>{comment.text}</p></button>)}
          {w.marks.map(mark=><p className="muted" key={mark.id}>{mark.tool} · {mark.points.length} points</p>)}
          <Btn sm onClick={()=>dispatch("watcher.workshop")}>Ask in Workshop</Btn>
        </aside>
      </div>
    </main>;
  }
  window.UI.Watcher=Watcher;
})();
