# -*- coding: utf-8 -*-
"""Self-hosting map, INTERACTIVE node language:
  - top view: 15 domains as GROUP-NODES. click one -> it OPENS into its real inner
    nodes, wired (a group is a node you open). back returns.
  - inner node: click it -> it's a node (cat, status, params you can pull out).
  - wire: click it -> it's a node too (add a gate/logic).
  - the map's OWN UI (title/accent/buttons) is nodes; the WATCHER edits them and the
    bar + canvas re-run from the graph.
Not a dashboard. You drive nodes."""
import json, os

GM = os.environ.get("ARCHHUB_GRAND_MAP_PATH")
if not GM:
    raise RuntimeError(
        "ARCHHUB_GRAND_MAP_PATH is required; private Grand Map data is "
        "never embedded in the public product tree")
D = json.load(open(GM, encoding="utf-8"))
domains = [{
    "key": d["key"], "title": d["title"],
    "nodes": [{"id": n["id"], "title": n.get("title", ""), "cat": n.get("cat", "note"),
               "status": n.get("status", "vision"),
               "params": [{"k": str(p["k"]), "v": str(p["v"])} for p in n.get("params", [])][:3]}
              for n in d["nodes"]],
    "wires": [w for w in d.get("wires", []) if len(w) == 2],
    "crossTo": [c.get("to_domain") for c in d.get("cross", [])],
} for d in D]
chrome = {"title": {"id": "ui_title", "text": "ArchHub - the map - its UI is nodes"},
          "accent": {"id": "ui_accent", "color": "#d97757"},
          "buttons": [{"id": "tb_run", "label": "Run"}, {"id": "tb_wire", "label": "Wire"},
                      {"id": "tb_fit", "label": "Fit"}, {"id": "tb_save", "label": "Save"}]}
GRAPH = {"chrome": chrome, "domains": domains}

TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>ArchHub - node language map</title>
<style>
:root{--bg:#0e0e11;--panel:#15151a;--line:#26262e;--ink:#ece8e0;--soft:#9b938a;--muted:#5e574f;--acc:#d97757;}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif;overflow:hidden}
#topbar{position:fixed;top:0;left:0;right:0;height:50px;display:flex;align-items:center;gap:8px;padding:0 14px;background:#0e0e11ee;border-bottom:1px solid var(--line);z-index:5}
.title{font-family:'Instrument Serif',Georgia,serif;font-size:18px;margin-right:12px;white-space:nowrap}
.tb{border:0;border-radius:7px;padding:7px 13px;color:#1a0e08;font-weight:700;font-size:12px;cursor:pointer;font-family:inherit}
.tb.ghost{background:#1c1c23;color:var(--ink);border:1px solid var(--line);font-weight:400;margin-left:auto}
#stage{position:fixed;inset:50px 0 0 0}svg{width:100%;height:100%;cursor:default}
.gnode{cursor:pointer}.gnode .gc{transition:stroke .1s}.gnode:hover .gc{stroke:var(--acc);stroke-width:2}
.panel{position:fixed;top:50px;right:0;bottom:0;width:300px;background:#121216;border-left:1px solid var(--line);padding:14px;overflow:auto;transform:translateX(100%);transition:transform .16s;z-index:6}
.panel.open{transform:none}.panel h3{margin:0 0 4px;font-size:14px}.panel .x{position:absolute;top:10px;right:12px;cursor:pointer;color:var(--soft)}
.panel .note{color:var(--soft);font-size:11px;margin:6px 0;line-height:1.5}
.panel label{display:block;font-size:10px;letter-spacing:.6px;color:var(--acc);font-weight:700;margin:12px 0 4px}
.panel input{width:100%;background:#1c1c23;border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:6px 9px;font-size:12px;font-family:inherit}
.panel input[type=color]{height:34px;padding:2px}
.panel .row{display:flex;gap:6px;margin-bottom:6px}.panel .row input{flex:1}
.panel .row button,.panel .add{background:#1c1c23;border:1px solid var(--line);color:var(--ink);border-radius:6px;cursor:pointer;font-size:12px;padding:6px 9px}.panel .add{width:100%;margin-top:4px}
.prow{display:flex;justify-content:space-between;gap:8px;font-size:11px;font-family:ui-monospace,monospace;border-bottom:1px solid #1c1c23;padding:5px 0}
.prow .pull{color:var(--acc);cursor:pointer;white-space:nowrap}
.hint{position:fixed;left:14px;bottom:10px;color:var(--muted);font-size:11px;z-index:5;max-width:62%}
</style></head><body>
<div id="topbar"></div>
<div id="stage"><svg id="svg"></svg></div>
<aside id="watcher" class="panel"></aside>
<aside id="insp" class="panel"></aside>
<div class="hint" id="hint"></div>
<script>
const GRAPH = __GRAPH__;
const NS='http://www.w3.org/2000/svg';
let view='top';
const svg=document.getElementById('svg');
function esc(s){return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function save(){try{localStorage.setItem('archhub_nl',JSON.stringify(GRAPH.chrome));}catch(e){}}
(function(){try{const s=localStorage.getItem('archhub_nl');if(s)GRAPH.chrome=JSON.parse(s);}catch(e){}})();
function E(t,a){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
function clear(){while(svg.firstChild)svg.removeChild(svg.firstChild);}
function stcol(s){return s==='live'?'#7ec18e':(s==='partial'?'#e5b25a':'#d97757');}
function evalAccent(){return GRAPH.chrome.accent.color;}
function domainVal(d){let s=0;d.nodes.forEach(n=>s+=(n.status==='live'?1:(n.status==='partial'?0.5:0)));return Math.round(s/(d.nodes.length||1)*100);}
function fit(){const b=svg.getBBox();svg.setAttribute('viewBox',(b.x-24)+' '+(b.y-24)+' '+(b.width+48)+' '+(b.height+48));}

// ---- the map's own UI, from nodes ----
function renderTopbar(){
  const acc=evalAccent();document.documentElement.style.setProperty('--acc',acc);
  const btns=GRAPH.chrome.buttons.map(b=>'<button class="tb">'+esc(b.label)+'</button>').join('');
  document.getElementById('topbar').innerHTML='<span class="title">'+esc(GRAPH.chrome.title.text)+'</span>'+btns+'<button class="tb ghost" id="wbtn">watcher</button>';
  document.querySelectorAll('#topbar .tb:not(.ghost)').forEach(b=>b.style.background=acc);
  document.getElementById('wbtn').onclick=()=>{closePanels();document.getElementById('watcher').classList.add('open');renderWatcher();};
}
function closePanels(){document.getElementById('watcher').classList.remove('open');document.getElementById('insp').classList.remove('open');}
function renderWatcher(){
  const c=GRAPH.chrome;
  let h='<span class="x" onclick="closePanels()">x</span><h3>watcher</h3><div class="note">the map\'s OWN UI, as nodes. edit one -> the bar + canvas re-run from it.</div>';
  h+='<label>accent - a node (buttons + meters read it)</label><input type="color" value="'+c.accent.color+'" oninput="setAccent(this.value)">';
  h+='<label>toolbar buttons - each a node</label>';
  c.buttons.forEach((b,i)=>{h+='<div class="row"><input value="'+esc(b.label)+'" oninput="setBtn('+i+',this.value)"><button onclick="delBtn('+i+')">x</button></div>';});
  h+='<button class="add" onclick="addBtn()">+ add button (a new node)</button>';
  h+='<label>title - a node</label><input value="'+esc(c.title.text)+'" oninput="setTitle(this.value)">';
  document.getElementById('watcher').innerHTML=h;
}
function setAccent(v){GRAPH.chrome.accent.color=v;renderTopbar();render();save();}
function setBtn(i,v){GRAPH.chrome.buttons[i].label=v;renderTopbar();save();}
function delBtn(i){GRAPH.chrome.buttons.splice(i,1);renderTopbar();renderWatcher();save();}
function addBtn(){GRAPH.chrome.buttons.push({id:'b'+Date.now(),label:'New'});renderTopbar();renderWatcher();save();}
function setTitle(v){GRAPH.chrome.title.text=v;renderTopbar();save();}

// ---- the canvas: domains are openable group-nodes ----
function render(){view==='top'?renderTop():renderDomain(view);}
function renderTop(){
  clear();const acc=evalAccent(),COLS=5,W=200,H=92,GX=240,GY=150,OX=30,OY=30,pos={};
  document.getElementById('hint').innerHTML='15 domains, each a <b>group-node</b>. click one -> it opens into its inner nodes. open <b>watcher</b> to edit the map\'s own UI.';
  GRAPH.domains.forEach((d,i)=>{pos[d.key]={x:OX+(i%COLS)*GX,y:OY+Math.floor(i/COLS)*GY};});
  const seen={};GRAPH.domains.forEach(d=>{(d.crossTo||[]).forEach(t=>{if(!pos[t])return;const k=d.key+'>'+t;if(seen[k])return;seen[k]=1;
    const a=pos[d.key],b=pos[t],x1=a.x+W,y1=a.y+H/2,x2=b.x,y2=b.y+H/2,mx=(x1+x2)/2;
    svg.appendChild(E('path',{d:'M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2,fill:'none',stroke:'#23232b','stroke-width':.8}));});});
  GRAPH.domains.forEach(d=>{const p=pos[d.key],v=domainVal(d),g=E('g',{class:'gnode',transform:'translate('+p.x+','+p.y+')'});
    g.appendChild(E('rect',{class:'gc',width:W,height:H,rx:10,fill:'#15151a',stroke:'#26262e','stroke-width':1.4}));
    let t=E('text',{x:14,y:26,fill:'#ece8e0','font-size':13,'font-weight':700});t.textContent=d.title.slice(0,24);g.appendChild(t);
    t=E('text',{x:14,y:44,fill:'#9b938a','font-size':10});t.textContent='open -> '+d.nodes.length+' nodes inside';g.appendChild(t);
    g.appendChild(E('rect',{x:14,y:H-22,width:W-28,height:5,rx:2.5,fill:'#1c1c23'}));
    g.appendChild(E('rect',{x:14,y:H-22,width:(W-28)*v/100,height:5,rx:2.5,fill:acc}));
    t=E('text',{x:W-14,y:H-26,fill:'#9b938a','font-size':9.5,'text-anchor':'end'});t.textContent=v+'%';g.appendChild(t);
    g.appendChild(E('circle',{cx:0,cy:H/2,r:5,fill:'#1c1c23',stroke:acc,'stroke-width':1.4}));
    g.appendChild(E('circle',{cx:W,cy:H/2,r:5,fill:'#1c1c23',stroke:acc,'stroke-width':1.4}));
    g.onclick=()=>{view=d.key;closePanels();render();};svg.appendChild(g);});
  fit();
}
function renderDomain(key){
  const d=GRAPH.domains.find(x=>x.key===key);clear();const acc=evalAccent();
  document.getElementById('hint').innerHTML='inside <b>'+esc(d.title)+'</b> - real nodes, wired. click a node = it\'s a node. click a wire = it\'s a node too.';
  const back=E('g',{class:'gnode',transform:'translate(20,14)'});
  back.appendChild(E('rect',{width:122,height:30,rx:7,fill:'#1c1c23',stroke:'#26262e'}));
  let bt=E('text',{x:14,y:20,fill:'#ece8e0','font-size':12});bt.textContent='← all domains';back.appendChild(bt);
  back.onclick=()=>{view='top';closePanels();render();};svg.appendChild(back);
  bt=E('text',{x:152,y:34,fill:acc,'font-size':15,'font-weight':700});bt.textContent=d.title+'  -  group opened';svg.appendChild(bt);
  const COLS=5,W=158,H=76,GX=184,GY=110,OX=20,OY=60,pos={},idx={};
  d.nodes.forEach((n,i)=>{pos[n.id]={x:OX+(i%COLS)*GX,y:OY+Math.floor(i/COLS)*GY};idx[n.id]=i;});
  (d.wires||[]).forEach(w=>{const a=pos[w[0]],b=pos[w[1]];if(!a||!b)return;const x1=a.x+W,y1=a.y+H/2,x2=b.x,y2=b.y+H/2,mx=(x1+x2)/2;
    const pth=E('path',{d:'M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2,fill:'none',stroke:acc,'stroke-opacity':.4,'stroke-width':1.4});
    pth.style.cursor='pointer';pth.onclick=ev=>{ev.stopPropagation();inspectWire(d.nodes[idx[w[0]]],d.nodes[idx[w[1]]]);};svg.appendChild(pth);});
  d.nodes.forEach(n=>{const p=pos[n.id],g=E('g',{class:'gnode',transform:'translate('+p.x+','+p.y+')'});
    g.appendChild(E('rect',{class:'gc',width:W,height:H,rx:8,fill:'#15151a',stroke:'#26262e','stroke-width':1.3}));
    g.appendChild(E('rect',{x:0,y:8,width:3,height:H-16,rx:1.5,fill:stcol(n.status)}));
    let t=E('text',{x:13,y:21,fill:'#9b938a','font-size':7.5,'letter-spacing':.6});t.textContent=(n.cat||'').toUpperCase();g.appendChild(t);
    t=E('text',{x:13,y:39,fill:'#ece8e0','font-size':11,'font-weight':700});t.textContent=(n.title||'').slice(0,20);g.appendChild(t);
    t=E('text',{x:13,y:56,fill:'#5e574f','font-size':8.5});t.textContent=n.status+(n.params&&n.params.length?'  -  '+n.params.length+' params':'');g.appendChild(t);
    g.appendChild(E('circle',{cx:0,cy:H/2,r:4.5,fill:'#1c1c23',stroke:acc,'stroke-width':1.3}));
    g.appendChild(E('circle',{cx:W,cy:H/2,r:4.5,fill:'#1c1c23',stroke:acc,'stroke-width':1.3}));
    g.onclick=ev=>{ev.stopPropagation();inspect(n);};svg.appendChild(g);});
  fit();
}
function inspect(n){closePanels();const ip=document.getElementById('insp');
  let h='<span class="x" onclick="closePanels()">x</span><h3>'+esc(n.title)+'</h3><div class="note">a node - category <b>'+esc(n.cat)+'</b>, status <b>'+esc(n.status)+'</b></div>';
  h+='<label>params - each is a node you can pull out</label>';
  (n.params||[]).forEach(p=>{h+='<div class="prow"><span>'+esc(p.k)+': '+esc(p.v)+'</span><span class="pull">pull out &#9656;</span></div>';});
  if(!(n.params&&n.params.length))h+='<div class="note">(no params)</div>';
  ip.innerHTML=h;ip.classList.add('open');}
function inspectWire(a,b){closePanels();const ip=document.getElementById('insp');
  ip.innerHTML='<span class="x" onclick="closePanels()">x</span><h3>wire</h3><div class="note">'+esc(a.title)+' &#8594; '+esc(b.title)+'</div><div class="note">a wire is a node too - open it, give it a <b>gate</b> or <b>logic</b>.</div><button class="add">+ add gate</button>';
  ip.classList.add('open');}
svg.addEventListener('click',e=>{if(e.target===svg||e.target.tagName==='svg'){if(view!=='top'){return;}}});
renderTopbar();render();
</script></body></html>"""

html = TEMPLATE.replace("__GRAPH__", json.dumps(GRAPH, ensure_ascii=False))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self-hosting-map.html")
open(out, "w", encoding="utf-8").write(html)
inner = sum(len(d["nodes"]) for d in domains)
print("WROTE", os.path.basename(out), "·", len(html), "bytes ·", len(domains),
      "openable group-nodes ·", inner, "inner nodes total")
