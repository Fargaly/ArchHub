"""Generic architect-facing canvas for one signed Unified Cell scope lens.

The document is disposable presentation. It owns no semantic state and does
not dispatch on product, domain, definition, or panel names. Every visible
node, property, port, relation, and catalogue entry comes from the accepted
scope-lens payload returned by the signed graph owner.
"""
from __future__ import annotations

import html


# The palette is transcribed from the design system's single source of truth
# (70.HANDOFFS/archhub-design/archhub/project/tokens.jsx). Two things that file
# fixes and this one had not: ink_muted was #5e574f, which that source measures
# at 2.56:1 on our dark surfaces -- failing WCAG AA at every size it is used --
# and on_fill exists because #fff on accent #d97757 measures 3.12:1. Do not
# hand-edit a colour here; change tokens.jsx and re-transcribe.
THEME = {
    "bg": "#0e0e11",
    "bg_panel": "#15151a",
    "bg_soft": "#1c1c23",
    "bg_hover": "#22222a",
    "bg_deep": "#0a0a0d",
    "bg_canvas": "#101015",
    "bg_raised": "#1d1d22",
    "bg_ink": "#18181e",
    "ink": "#ece8e0",
    "ink_soft": "#9b938a",
    "ink_muted": "#8b837a",
    "ink_dim": "#8a837c",
    "on_fill": "#180f08",
    "line": "#26262e",
    "line_soft": "#1e1e24",
    "line_hair": "#1a1a20",
    "accent": "#d97757",
    "accent_soft": "#3a2018",
    "accent_dim": "#2a1812",
    "accent_hi": "#e8896a",
    "accent_press": "#a04832",
    "ok": "#7ec18e",
    "warn": "#e5b25a",
    "err": "#e6705f",
    "cyan": "#5fb3b3",
    "purple": "#a98cd6",
    "blue": "#7898d6",
    "l_bg": "#f7f4ee",
    "l_bg_panel": "#fbf9f4",
    "l_bg_soft": "#efeae0",
    "l_ink": "#1a1612",
    "l_ink_soft": "#6b6256",
    "l_ink_muted": "#9a9183",
    "l_line": "#e3ddd0",
    "l_accent": "#c96442",
}


STYLE = r"""
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif;font-size:13px;letter-spacing:0}button,input,select,textarea{font:inherit;letter-spacing:0}.archhub-app{width:100vw;height:100vh;display:grid;grid-template-columns:252px minmax(0,1fr);grid-template-rows:minmax(0,1fr) 24px;background:var(--bg);overflow:hidden}.library{grid-column:1;grid-row:1;display:flex;flex-direction:column;min-height:0;background:var(--bg-panel);border-right:1px solid var(--line)}.library-head{height:48px;display:flex;align-items:center;padding:0 14px;border-bottom:1px solid var(--line)}.brand{font-size:15px;font-weight:680}.brand strong{color:var(--accent);font-weight:680}.library-search{margin:10px;height:34px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink);padding:6px 9px;outline:0}.library-search:focus{border-color:var(--accent)}.library-list{min-height:0;overflow:auto;padding:0 8px 12px}.library-count{padding:6px 10px 8px;color:var(--ink-muted);font-size:10px}.library-item{width:100%;min-height:52px;margin:3px 0;padding:9px 10px;border:1px solid transparent;border-radius:4px;background:transparent;color:var(--ink);text-align:left;cursor:pointer}.library-item:hover,.library-item:focus-visible{border-color:var(--line);background:var(--bg-hover);outline:0}.library-name{display:block;font-size:12px;font-weight:600}.library-meta{display:block;margin-top:4px;color:var(--ink-muted);font-size:9px}.workspace{grid-column:2;grid-row:1;min-width:0;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 360px;grid-template-rows:42px minmax(0,1fr);overflow:hidden}.workspace-head{grid-column:1/-1;display:flex;align-items:center;gap:8px;padding:0 12px;background:var(--bg-panel);border-bottom:1px solid var(--line)}.scope-back,.scope-fit{height:28px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink-soft);padding:0 9px;cursor:pointer}.scope-back:disabled{opacity:.35;cursor:default}.scope-back:hover:not(:disabled),.scope-fit:hover{border-color:var(--accent);color:var(--ink)}.scope-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:620}.scope-revision{margin-left:auto;color:var(--ink-muted);font-size:10px}.canvas{grid-column:1;grid-row:2;position:relative;overflow:hidden;background-color:var(--bg-canvas);background-image:radial-gradient(circle,var(--line-soft) 1px,transparent 1px);background-size:20px 20px;touch-action:none;cursor:grab}.canvas[data-panning="true"]{cursor:grabbing}.canvas-stage{position:absolute;left:0;top:0;width:1600px;height:1000px;transform-origin:0 0}.wire-layer{position:absolute;inset:0;width:1600px;height:1000px;overflow:visible}.wire-line{fill:none;stroke:var(--cyan);stroke-width:1.5;opacity:.46;pointer-events:none}.wire-hit{fill:none;stroke:rgba(0,0,0,.001);stroke-width:14;pointer-events:stroke;cursor:pointer}.wire-hit:hover+.wire-line,.wire-hit[data-selected="true"]+.wire-line{opacity:1;stroke-width:2.2}.graph-node{position:absolute;width:220px;min-height:112px;padding:0;border:1px solid var(--line);border-radius:6px;background:var(--bg-panel);color:var(--ink);text-align:left;box-shadow:0 3px 12px rgba(0,0,0,.28);cursor:pointer}.graph-node:hover{border-color:var(--accent);box-shadow:0 6px 18px rgba(0,0,0,.36)}.graph-node:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.graph-node[data-selected="true"]{border-color:var(--cyan);box-shadow:0 0 0 1px var(--cyan),0 5px 18px rgba(0,0,0,.36)}.node-head{height:27px;padding:7px 10px 6px;border-bottom:1px solid var(--line-soft);color:var(--ink-muted);font-size:9px;font-weight:650;text-transform:uppercase}.node-title{padding:11px 12px 3px;font-size:13px;font-weight:650;line-height:1.25}.node-state{padding:3px 12px 9px;color:var(--ink-muted);font-size:10px}.node-ports{display:flex;justify-content:space-between;gap:8px;padding:4px 6px 7px}.node-port{position:relative;min-width:24px;max-width:92px;height:24px;border:0;background:transparent;color:var(--ink-muted);font-size:9px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}.node-port::before{content:"";display:inline-block;width:9px;height:9px;margin-right:5px;border:1.5px solid currentColor;border-radius:50%;background:var(--bg-panel)}.node-port[data-side="output"]::before{background:currentColor}.node-port:hover{color:var(--accent)}.inspector{grid-column:2;grid-row:2;min-height:0;overflow:auto;background:var(--bg-panel);border-left:1px solid var(--line);padding:16px 18px 24px}.inspector-empty{height:100%;display:flex;align-items:center;justify-content:center;color:var(--ink-muted);text-align:center}.inspector-kicker{color:var(--accent);font-size:10px;font-weight:650}.inspector-title{margin-top:5px;font-size:17px;font-weight:650}.inspector-meta{margin-top:6px;color:var(--ink-muted);font-size:9px;overflow-wrap:anywhere}.inspector-tabs{display:flex;gap:2px;margin:14px 0 10px;padding:2px;border:1px solid var(--line);border-radius:5px;background:var(--bg);overflow:auto}.inspector-tab{flex:1 0 auto;min-width:72px;height:32px;padding:0 10px;border:0;border-radius:3px;background:transparent;color:var(--ink-muted);font-size:10px;cursor:pointer}.inspector-tab[data-active="true"]{background:var(--bg-hover);color:var(--ink);box-shadow:inset 0 -2px 0 var(--accent)}.inspector-section{display:flex;flex-direction:column;gap:11px;padding-top:12px;border-top:1px solid var(--line-soft)}.property-row{display:flex;flex-direction:column;gap:6px}.property-label{color:var(--ink-muted);font-size:10px}.property-input{width:100%;min-height:34px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink);padding:6px 9px;outline:0}.property-input:focus{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent-soft)}textarea.property-input{min-height:88px;resize:vertical}.relation-row{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink-soft);text-align:left;cursor:pointer;overflow-wrap:anywhere}.relation-row:hover{border-color:var(--accent);color:var(--ink)}.status{grid-column:1/-1;grid-row:2;display:flex;align-items:center;gap:14px;padding:0 9px;background:var(--bg-deep);border-top:1px solid var(--line);color:var(--ink-muted);font-size:9px}.status-live{color:var(--ok)}.status-message{margin-left:auto;max-width:55vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status-message[data-error="true"]{color:var(--err)}*{scrollbar-width:thin;scrollbar-color:var(--line) var(--bg-deep)}@media(max-width:980px){.archhub-app{grid-template-columns:56px minmax(0,1fr)}.library{overflow:hidden}.library-head{padding:0 9px}.library .brand strong,.library .brand span,.library-search,.library-list,.library-count{display:none}.workspace{grid-template-columns:minmax(0,1fr) 320px}}@media(max-width:720px){.workspace{grid-template-columns:1fr}.inspector{display:none}}
"""


SCRIPT = r"""
(() => {
  const state={lens:null,selectedNode:null,selectedRelation:null,trail:[],view:{x:24,y:24,zoom:.86},pan:null};
  const csrf=document.querySelector('meta[name="archhub-csrf"]')?.content||'';
  const canvas=document.querySelector('[data-canvas]');
  const stage=document.querySelector('[data-stage]');
  const status=document.querySelector('[data-status-message]');
  const escapeText=value=>String(value??'');
  function message(text,error=false){status.textContent=text;status.dataset.error=String(error);}
  async function request(path,options={}){
    const headers={'Accept':'application/json',...(options.headers||{})};
    if(options.method&&options.method!=='GET'){headers['Content-Type']='application/json';headers['X-ArchHub-CSRF']=csrf;}
    const response=await fetch(path,{...options,headers,credentials:'same-origin'});
    const payload=await response.json();
    if(!response.ok||payload.ok===false)throw new Error(payload.error||`Request failed (${response.status})`);
    return payload;
  }
  function applyView(){stage.style.transform=`translate(${state.view.x}px,${state.view.y}px) scale(${state.view.zoom})`;}
  function nodePosition(index){const columns=Math.max(2,Math.floor((canvas.clientWidth-80)/270));return{x:70+(index%columns)*270,y:70+Math.floor(index/columns)*190};}
  function visibleNode(root){return state.lens.nodes.find(node=>node.root_id===root);}
  function renderLibrary(){
    const list=document.querySelector('[data-library-list]');
    const query=document.querySelector('[data-library-search]').value.trim().toLowerCase();
    const items=state.lens.catalogue.filter(item=>!query||item.name.toLowerCase().includes(query));
    list.replaceChildren(...items.map(item=>{
      const button=document.createElement('button');button.className='library-item';button.type='button';button.dataset.definitionRoot=item.root_id;
      const name=document.createElement('span');name.className='library-name';name.textContent=item.name;
      const meta=document.createElement('span');meta.className='library-meta';meta.textContent=`${item.lifecycle} / v${item.version}`;
      button.append(name,meta);button.addEventListener('click',()=>message(`${item.name} is available from the graph catalogue.`));return button;
    }));
    document.querySelector('[data-library-count]').textContent=`${items.length} released assemblies`;
  }
  function cardFor(node,index){
    const card=document.createElement('button');card.type='button';card.className='graph-node';card.dataset.root=node.root_id;card.dataset.openable=String(node.openable);card.dataset.selected=String(node.root_id===state.selectedNode);card.style.left=`${nodePosition(index).x}px`;card.style.top=`${nodePosition(index).y}px`;
    const head=document.createElement('div');head.className='node-head';head.textContent=node.structural_role;
    const title=document.createElement('div');title.className='node-title';title.textContent=node.label;
    const value=document.createElement('div');value.className='node-state';value.textContent=node.state??node.definition_name??'Composition';
    const ports=document.createElement('div');ports.className='node-ports';
    node.ports.forEach(port=>{const control=document.createElement('span');control.className='node-port';control.dataset.relationRoot=port.relation_root;control.dataset.side=port.participant_role==='source'?'output':'input';control.title=`${port.connection||'relation'} / ${port.participant_role}`;control.textContent=port.connection||port.participant_role;ports.append(control);});
    card.append(head,title,value,ports);
    card.addEventListener('click',event=>{event.stopPropagation();state.selectedNode=node.root_id;state.selectedRelation=null;renderSelection();renderInspector();});
    card.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();if(node.openable)loadScope(node.root_id,true);});
    return card;
  }
  function renderWires(){
    const svg=document.querySelector('[data-wire-layer]');svg.replaceChildren();
    state.lens.relations.forEach(relation=>{
      const visible=relation.participants.map(([,root])=>root).filter(root=>visibleNode(root));
      if(visible.length<2)return;
      const a=document.querySelector(`[data-root="${CSS.escape(visible[0])}"]`);const b=document.querySelector(`[data-root="${CSS.escape(visible[1])}"]`);if(!a||!b)return;
      const x1=a.offsetLeft+a.offsetWidth,y1=a.offsetTop+a.offsetHeight/2,x2=b.offsetLeft,y2=b.offsetTop+b.offsetHeight/2;
      const d=`M ${x1} ${y1} C ${x1+85} ${y1}, ${x2-85} ${y2}, ${x2} ${y2}`;
      const hit=document.createElementNS('http://www.w3.org/2000/svg','path');hit.setAttribute('d',d);hit.setAttribute('class','wire-hit');hit.dataset.relationRoot=relation.root_id;hit.dataset.selected=String(state.selectedRelation===relation.root_id);
      const line=document.createElementNS('http://www.w3.org/2000/svg','path');line.setAttribute('d',d);line.setAttribute('class','wire-line');
      hit.addEventListener('click',event=>{event.stopPropagation();state.selectedRelation=relation.root_id;state.selectedNode=null;renderSelection();renderInspector();});svg.append(hit,line);
    });
  }
  function renderSelection(){document.querySelectorAll('[data-root]').forEach(card=>card.dataset.selected=String(card.dataset.root===state.selectedNode));document.querySelectorAll('[data-relation-root].wire-hit').forEach(wire=>wire.dataset.selected=String(wire.dataset.relationRoot===state.selectedRelation));}
  function inputFor(property,node){
    let control;if(property.editor==='choice'&&Array.isArray(property.constraints.options)){control=document.createElement('select');property.constraints.options.forEach(value=>{const option=document.createElement('option');option.value=escapeText(value);option.textContent=escapeText(value);option.selected=value===property.value;control.append(option);});}
    else if(property.editor==='multiline'){control=document.createElement('textarea');control.value=escapeText(property.value);}
    else{control=document.createElement('input');control.type=property.constraints.type==='number'?'number':'text';control.value=escapeText(property.value);}
    control.className='property-input';control.dataset.property=property.name;control.addEventListener('change',async()=>{try{const id=crypto.randomUUID();const payload=await request('/api/revise-instance',{method:'POST',body:JSON.stringify({instance_root:node.root_id,scope_root:state.lens.scope_root,changes:{[property.name]:control.value},expected_revision:state.lens.revision,idempotency_key:id})});state.lens=payload.lens;state.selectedNode=node.root_id;renderAll();message(`Accepted revision ${payload.accepted_revision}.`);}catch(error){message(error.message,true);renderInspector();}});return control;
  }
  function renderInspector(){
    const inspector=document.querySelector('[data-inspector]');const node=visibleNode(state.selectedNode);const relation=state.lens?.relations.find(item=>item.root_id===state.selectedRelation);
    if(!node&&!relation){inspector.innerHTML='<div class="inspector-empty">Select a node, port, or wire to inspect its graph-held properties.</div>';return;}
    inspector.replaceChildren();const kicker=document.createElement('div');kicker.className='inspector-kicker';kicker.textContent=relation?'Relation':node.structural_role;const title=document.createElement('div');title.className='inspector-title';title.textContent=relation?(relation.properties.connection||'Relation'):node.label;const meta=document.createElement('div');meta.className='inspector-meta';meta.textContent=relation?relation.root_id:`${node.root_id} / ${node.ports.length} relations`;inspector.append(kicker,title,meta);
    if(relation){const section=document.createElement('section');section.className='inspector-section';relation.participants.forEach(([role,root])=>{const row=document.createElement('button');row.type='button';row.className='relation-row';row.textContent=`${role}: ${visibleNode(root)?.label||root}`;row.addEventListener('click',()=>{if(visibleNode(root)){state.selectedNode=root;state.selectedRelation=null;renderSelection();renderInspector();}});section.append(row);});inspector.append(section);return;}
    const panels=node.panels.length?node.panels:['Properties'];const tabs=document.createElement('div');tabs.className='inspector-tabs';tabs.setAttribute('role','tablist');panels.forEach((panel,index)=>{const tab=document.createElement('button');tab.type='button';tab.className='inspector-tab';tab.textContent=panel;tab.dataset.active=String(index===0);tab.setAttribute('role','tab');tab.addEventListener('click',()=>tabs.querySelectorAll('button').forEach(candidate=>candidate.dataset.active=String(candidate===tab)));tabs.append(tab);});inspector.append(tabs);
    const section=document.createElement('section');section.className='inspector-section';node.properties.forEach(property=>{const row=document.createElement('label');row.className='property-row';const label=document.createElement('span');label.className='property-label';label.textContent=property.name.replaceAll('_',' ');row.append(label,inputFor(property,node));section.append(row);});node.ports.forEach(port=>{const row=document.createElement('button');row.type='button';row.className='relation-row';row.textContent=`${port.connection||'relation'} / ${port.participant_role}`;row.addEventListener('click',()=>{state.selectedRelation=port.relation_root;state.selectedNode=null;renderSelection();renderInspector();});section.append(row);});inspector.append(section);
  }
  function renderCanvas(){const svg=document.querySelector('[data-wire-layer]');stage.querySelectorAll('.graph-node').forEach(node=>node.remove());state.lens.nodes.forEach((node,index)=>stage.append(cardFor(node,index)));requestAnimationFrame(renderWires);document.querySelector('[data-scope-title]').textContent=state.lens.scope_label||'Untitled scope';document.querySelector('[data-revision]').textContent=`revision ${state.lens.revision}`;document.querySelector('[data-back]').disabled=state.trail.length===0;svg.setAttribute('aria-label',`${state.lens.relations.length} graph relations`);}
  function renderAll(){renderLibrary();renderCanvas();renderInspector();applyView();}
  async function loadScope(root,push=false){try{message('Reading the accepted graph…');const query=root?`?scope_root=${encodeURIComponent(root)}`:'';const payload=await request(`/api/scope-lens${query}`);if(push&&state.lens)state.trail.push(state.lens.scope_root);state.lens=payload.lens;state.selectedNode=null;state.selectedRelation=null;state.view={x:24,y:24,zoom:.86};renderAll();message(`${state.lens.nodes.length} nodes / ${state.lens.relations.length} relations`);}catch(error){message(error.message,true);}}
  document.querySelector('[data-library-search]').addEventListener('input',renderLibrary);
  document.querySelector('[data-back]').addEventListener('click',()=>{const root=state.trail.pop();if(root)loadScope(root,false);});
  document.querySelector('[data-fit]').addEventListener('click',()=>{state.view={x:24,y:24,zoom:.86};applyView();});
  canvas.addEventListener('click',()=>{state.selectedNode=null;state.selectedRelation=null;renderSelection();renderInspector();});
  canvas.addEventListener('wheel',event=>{event.preventDefault();const rect=canvas.getBoundingClientRect();const old=state.view.zoom;const next=Math.max(.3,Math.min(2.5,old*Math.exp(-Math.max(-500,Math.min(500,event.deltaY))*.0015)));const x=event.clientX-rect.left,y=event.clientY-rect.top;const worldX=(x-state.view.x)/old,worldY=(y-state.view.y)/old;state.view.x=x-worldX*next;state.view.y=y-worldY*next;state.view.zoom=next;applyView();},{passive:false});
  canvas.addEventListener('pointerdown',event=>{if(event.button!==1&&!(event.button===0&&event.target===canvas))return;canvas.setPointerCapture(event.pointerId);canvas.dataset.panning='true';state.pan={id:event.pointerId,x:event.clientX,y:event.clientY,ox:state.view.x,oy:state.view.y};});
  canvas.addEventListener('pointermove',event=>{if(!state.pan||state.pan.id!==event.pointerId)return;state.view.x=state.pan.ox+event.clientX-state.pan.x;state.view.y=state.pan.oy+event.clientY-state.pan.y;applyView();});
  canvas.addEventListener('pointerup',event=>{if(!state.pan||state.pan.id!==event.pointerId)return;state.pan=null;canvas.dataset.panning='false';canvas.releasePointerCapture(event.pointerId);});
  loadScope(null,false);
})();
"""


def render_clean_application_document(csrf_token: str) -> str:
    if type(csrf_token) is not str or not csrf_token:
        raise ValueError("clean application CSRF token is required")
    variables = "".join(
        "--%s:%s;" % (name.replace("_", "-"), value)
        for name, value in THEME.items()
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        '<meta name="archhub-csrf" content="%s">'
        "<title>ArchHub</title><style>:root{%s}%s</style></head><body>"
        '<main class="archhub-app">'
        '<aside class="library" aria-label="Node Library">'
        '<header class="library-head"><div class="brand"><strong>Arch</strong><span>Hub</span></div></header>'
        '<input class="library-search" data-library-search type="search" autocomplete="off" spellcheck="false" placeholder="Search node library" aria-label="Search node library">'
        '<div class="library-count" data-library-count></div><div class="library-list" data-library-list></div></aside>'
        '<section class="workspace">'
        '<header class="workspace-head"><button class="scope-back" data-back type="button" aria-label="Back to parent scope">Back</button>'
        '<div class="scope-title" data-scope-title></div><button class="scope-fit" data-fit type="button">Fit</button>'
        '<div class="scope-revision" data-revision></div></header>'
        '<section class="canvas" data-canvas aria-label="Universal graph canvas">'
        '<div class="canvas-stage" data-stage><svg class="wire-layer" data-wire-layer role="group"></svg></div></section>'
        '<aside class="inspector" data-inspector aria-label="Properties"></aside></section>'
        '<footer class="status"><span class="status-live">ONE GRAPH</span><span>SIGNED SESSION</span><span data-status-message class="status-message"></span></footer>'
        "</main><script>%s</script></body></html>"
    ) % (html.escape(csrf_token, quote=True), variables, STYLE, SCRIPT)


__all__ = ["render_clean_application_document"]
