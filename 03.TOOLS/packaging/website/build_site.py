"""Build the public static site without importing the application runtime."""
import argparse
import ast
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from links import load_links

ROOT = Path(__file__).resolve().parents[3]
BRAND = ROOT / "01.APP/nodelang/data/website"
HERE = Path(__file__).resolve().parent


def markdown(text):
    """Render the headings, plain paragraphs, lists and code used by these sources."""
    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        heading = re.match(r"^(#{1,3}) ([^\n]+)(?:\n(.*))?$", block, re.S)
        if heading:
            level = len(heading[1])
            blocks.append(f"<h{level}>{html.escape(heading[2])}</h{level}>")
            if heading[3]:
                blocks.append(markdown(heading[3]))
            continue
        safe = html.escape(block)
        safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
        lines = safe.splitlines()
        if all(line.startswith("- ") for line in lines):
            blocks.append("<ul>" + "".join("<li>" + line[2:] + "</li>" for line in lines) + "</ul>")
        elif all(re.match(r"\d+\. ", line) for line in lines):
            blocks.append("<ol>" + "".join("<li>" + re.sub(r"^\d+\. ", "", line) + "</li>" for line in lines) + "</ol>")
        else:
            blocks.append("<p>" + safe + "</p>")
    return "\n".join(blocks)


def changelog_entries():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = []
    for part in text.split("\n## ")[1:]:
        title, body = part.split("\n", 1)
        body = "\n".join(line for line in body.splitlines() if not line.startswith("Source:"))
        body = re.sub(r"\b[0-9a-f]{7,40}\b", "", body).strip()
        if body:
            # Build identity lives in the release record; release headings are dates.
            date = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", title)
            title = f"{date[1]}-{date[2]}-{date[3]} · {date[4]}:{date[5]}" if date else title
            entries.append((title, body))
    return entries


# Your account (design v61): the five sections of Settings > Account in ArchHub, read from the cloud
# account. Name and firm save here (PATCH /v1/me); the rest is shown read-only until the cloud stores it.
ACCOUNT_SECTIONS = (
    ("acc-me", "Account", (("full_name", "Name", "edit"), ("email", "Email", ""), ("role", "Role", ""), ("firm_name", "Firm", "edit"),
                           ("language", "App language", ""), ("replyLang", "Agents reply in", ""), ("timezone", "Time zone", ""))),
    ("acc-plan", "Plan & access", (("plan", "Plan", ""), ("devices", "Signed in on", ""), ("office", "Active office", ""))),
    ("acc-comm", "Community", (("commProfile", "Public profile", ""), ("commHandle", "Profile address", ""),
                               ("commPublished", "What you published", ""), ("commNotify", "Tell me about installs and comments", ""))),
    ("acc-social", "Social media", (("socialAutoSend", "Send replies without asking", ""), ("socialDigest", "Inbox digest", ""))),
    ("acc-brain", "Brain and cloud sync", (("memory", "What agents remember about you", ""), ("brainContext", "Memories in each request", ""),
                                          ("syncBrain", "Brain follows your account", ""), ("syncSettings", "Settings follow your account", ""),
                                          ("syncFiles", "Sync .archhub files", ""))),
)
ACCOUNT_API = "https://api.archhub.io"
ACCOUNT_SCRIPT = """<script>(()=>{const A='%s',O={credentials:'include'},m=document.getElementById('accmsg'),P={trial:'Solo',solo:'Solo',studio:'Studio',firm:'Firm'};
const say=t=>m.textContent=t,j=(u,o)=>fetch(A+u,Object.assign({},O,o)).then(r=>r.json().then(b=>r.ok?b:Promise.reject(b.detail||r.status)));
const show=(k,x)=>{const e=document.querySelector('.rov[data-k="'+k+'"]');if(e)e.textContent=x===true?'On':x===false?'Off':Array.isArray(x)?(x.join('\\n')||'None'):(x==null||x===''?'\u2014':x)};
function paint(v){document.getElementById('accname').textContent=v.full_name||v.email;document.getElementById('accav').textContent=(v.full_name||v.email||'A')[0].toUpperCase();
document.querySelectorAll('input[data-k]').forEach(e=>{e.value=v[e.dataset.k]||'';e.disabled=false});
Object.entries(Object.assign({},v.settings||{},{email:v.email,role:v.role,plan:P[v.plan]||v.plan})).forEach(([k,x])=>show(k,x))}
document.querySelectorAll('input[data-k]').forEach(e=>e.onchange=()=>j('/v1/me',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({[e.dataset.k]:e.value})})
.then(v=>{paint(v);say('Saved. ArchHub shows it too.')}).catch(d=>say('Not saved: '+d)));
j('/v1/me').then(v=>{paint(v);document.getElementById('accin').hidden=true;
j('/v1/devices').then(d=>show('devices',(d.devices||[]).map(x=>x.name+(x.online?' \\u00b7 online':'')))).catch(()=>{});
j('/v1/companies/mine').then(d=>show('office',((d.companies||[]).find(c=>c.is_current)||{}).name||'Personal')).catch(()=>{});
j('/v1/memory/facts').then(d=>show('memory',(d.facts||d.items||[]).map(f=>f.text||f.fact||String(f)))).catch(()=>{})})
.catch(()=>say('Sign in to see your account.'))})()</script>""" % ACCOUNT_API


CATALOGUE = ROOT / ".cache" / "site" / "catalogue.json"  # written by export_catalogue.py at build time


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "item"


def catalogue():
    """Nodes and starters as this release ships them (export_catalogue.py)."""
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def table(head, rows):
    esc = html.escape
    return ('<div class="tw"><table><tr>' + "".join(f"<td>{esc(h)}</td>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table></div>")


def node_page(node, label):
    esc = html.escape
    kind = ('<p class="ok">Pure: it re-solves on every edit and changes nothing outside the file.</p>' if node["pure"] else
            '<p class="warn">Effect: it runs only when you press Run, and asks for Approve where it changes something.</p>')
    sockets = [(x["name"], x["type"] or "Any", "Input") for x in node["inputs"]] + [(x["name"], x["type"] or "Any", "Output") for x in node["outputs"]]
    body = (f'<p class="sub" style="font-size:12px;letter-spacing:.06em;text-transform:uppercase">Node reference · {esc(label)}</p>'
            f'<h1>{esc(node["title"])}</h1><p class="sub">{esc(node["sub"])}</p>' + kind)
    if sockets:
        body += "<h3>Sockets</h3>" + table(("Socket", "Type", "Side"), sockets)
    if node["params"]:
        body += "<h3>Parameters</h3>" + table(("Parameter", "Type", "Default"), [(x["name"], x["type"], "" if x["default"] in (None, "") else x["default"]) for x in node["params"]])
    body += '<p class="foot">Generated from the node’s own definition when ArchHub is published. ArchHub › Library shows the same node.</p>'
    return body


def nodes_index(data):
    esc = html.escape
    by_cat = {}
    for node in data["nodes"]:
        by_cat.setdefault(node["cat"], []).append(node)
    body = '<h1>Node reference</h1><p class="sub">Every node in the ArchHub Library, with its sockets and parameters.</p><div class="res">'
    for cat in data["categories"]:
        rows = by_cat.get(cat["id"], [])
        if rows:
            body += f'<h2>{esc(cat["label"])}</h2>' + "".join(f'<a class="r" href="/docs/nodes/{slug(n["id"])}/">{esc(n["title"])}<em>{esc(n["sub"])}</em></a>' for n in rows)
    return body + "</div>"


def starter_page(starter):
    esc = html.escape
    flow = '<span class="fw"></span>'.join(f'<span class="fn"><span class="tile fam-list"></span>{esc(step)}</span>' for step in starter["steps"])
    needs = ", ".join(starter["needs"]) or "Nothing beyond ArchHub"
    return (f'<div class="item"><div><div class="ih"><span class="tile fam-check"></span><div><h1>{esc(starter["title"])}</h1>'
            '<div class="by"><span class="av">A</span>ArchHub <span class="verif">✓ Built in</span><span>Starter</span></div></div></div>'
            f'<div class="flow" aria-label="Its nodes">{flow}</div>'
            f'<h3>When you run it</h3><p class="sub">Open it from Home in ArchHub: the steps are placed on a new canvas. Nothing runs until you press Run. {esc(starter["stops_at"])}.</p></div>'
            f'<aside class="side" aria-label="Open"><a class="open" href="archhub://starter/{slug(starter["id"])}">Open in ArchHub</a>'
            '<p class="sub" style="margin:0;font-size:12px">ArchHub opens the starter on a new canvas. Nothing runs until you press Run there.</p>'
            f'<dl class="facts"><dt>Author</dt><dd>ArchHub</dd><dt>Needs</dt><dd>{esc(needs)}</dd><dt>Steps</dt><dd>{len(starter["steps"])}</dd></dl></aside></div>')


def search_page():
    return ('<section class="res"><h1 id="sq">Search</h1><label class="sbox" style="margin:14px 0 0;width:100%"><input id="sin" placeholder="Search the starters and the node reference" aria-label="Search"></label>'
            '<div id="sout"></div><p class="foot">One index, built when ArchHub is published, over the starters and the node reference.</p></section>'
            """<script>(()=>{const i=document.getElementById('sin'),o=document.getElementById('sout');let ix=[];
const e=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function show(){const q=i.value.trim().toLowerCase();document.getElementById('sq').textContent=q?'Results for \\u201c'+i.value.trim()+'\\u201d':'Search';
const hits=q?ix.filter(x=>(x.t+' '+x.s).toLowerCase().includes(q)).slice(0,60):[];const g={};hits.forEach(x=>(g[x.g]=g[x.g]||[]).push(x));
o.innerHTML=Object.entries(g).map(([k,v])=>'<h2>'+e(k)+'</h2>'+v.map(x=>'<a class="r" href="'+x.u+'">'+e(x.t)+'<em>'+e(x.s)+'</em></a>').join('')).join('')||(q?'<p class="sub">Nothing matches.</p>':'')}
fetch('/search.json').then(r=>r.json()).then(d=>{ix=d;const q=new URLSearchParams(location.search).get('q');if(q)i.value=q;show()});i.oninput=show})()</script>""")


def search_index(data):
    return ([{"g": "Starters", "t": x["title"], "s": "Starter", "u": f"/community/{slug(x['id'])}/"} for x in data["starters"]]
            + [{"g": "Node reference", "t": n["title"], "s": n["sub"], "u": f"/docs/nodes/{slug(n['id'])}/"} for n in data["nodes"]])


DESIGN = HERE / "data" / "design.json"
# Routes of the design that are not part of this build (717, 18 Nov): one door for accounts (sign-in creates it),
# no public contact or people pages yet, the design's own reference boards, and BABOOM's pages, which live on
# baboom.archhub.io (one source); links to them go to the page that stands in for them.
DESIGN_SKIP = {"/signup", "/contact", "/community/people/sam-rivera", "/_brand", "/_states", "/docs/*", "/account"}
DESIGN_MOVED = {"/signup": "/signin/", "/contact": "/download/", "/pricing": "/download/", "/cloud": "/download/"}
COMPONENT_CSS = """
.tw{border-radius:10px;border:1px solid var(--line);background:var(--bgPanel);overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}td{padding:8px 10px;border-top:1px solid var(--lineSoft);vertical-align:top}tr:first-child td{border-top:0;color:var(--ink3);font-size:12px}
.r{display:flex;gap:12px;align-items:center;padding:12px 14px;border-radius:8px;background:var(--bgPanel);border:1px solid var(--line);margin-bottom:6px;text-decoration:none}.r em{font-style:normal;color:var(--ink3);font-size:12px;margin-left:auto;text-align:right}
.item{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px;align-items:start}.ih{display:flex;gap:14px;align-items:flex-start}.tile{width:36px;height:36px;border-radius:8px;display:grid;place-items:center;flex:none;background:var(--accent)}.fam-list{background:#a98cd6}.fam-check{background:#e5b25a}
.by{display:flex;align-items:center;gap:8px;color:var(--ink2);font-size:13px;margin-top:6px;flex-wrap:wrap}.verif,.ok{color:#7ec18e}.flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:18px;border-radius:10px;background:var(--bgPanel);border:1px solid var(--line);margin-top:18px}
.fn{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;background:var(--bgSoft);border:1px solid var(--line);font-size:13px}.fn .tile{width:20px;height:20px;border-radius:5px}.fw{width:24px;height:2px;background:var(--ink3)}
.sbox{display:flex;align-items:center;gap:8px;height:40px;padding:0 12px;border-radius:8px;background:var(--bgPanel);border:1px solid var(--line)}.sbox input{flex:1;min-width:0;background:none;border:0;color:var(--ink);font:inherit;outline:none}
@media(max-width:760px){.item{grid-template-columns:minmax(0,1fr)}}
.accmsg{min-height:20px;font-size:12.5px;color:var(--ink3)}.acch [hidden]{display:none}.acch>div{flex:1;min-width:260px}.accr input{height:32px;padding:0 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit;width:100%}.accr .rov{color:var(--ink);line-height:1.6;padding:6px 0;overflow-wrap:anywhere}
.ft>*,.ft-big{min-width:0}.shot img{width:100%;height:auto}
.bbm-bub:not(.fits){display:none!important}
@media(max-width:1400px){.wrap,.foot-in,.foot-bar{padding-right:100px}}
.soon-form{padding:14px 16px;border:1px dashed var(--line);border-radius:10px;color:var(--ink2)}
"""
UI_SCRIPT = """<script>(()=>{const T=document.documentElement,K='archhub-theme';const set=v=>{if(v==='system')T.removeAttribute('data-theme');else T.setAttribute('data-theme',v);
document.querySelectorAll('[data-theme-set]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.themeSet===v))};try{set(localStorage.getItem(K)||'system')}catch(e){}
document.querySelectorAll('[data-theme-set]').forEach(b=>b.onclick=()=>{set(b.dataset.themeSet);try{localStorage.setItem(K,b.dataset.themeSet)}catch(e){}});
document.querySelectorAll('.dd > button,.acct > button').forEach(b=>b.onclick=e=>{e.stopPropagation();const d=b.parentElement,o=!d.classList.contains('open');document.querySelectorAll('.dd,.acct').forEach(x=>x.classList.remove('open'));d.classList.toggle('open',o);b.setAttribute('aria-expanded',o)});
document.addEventListener('click',()=>document.querySelectorAll('.dd,.acct').forEach(x=>x.classList.remove('open')));
document.querySelectorAll('[role=tablist] [role=tab]').forEach(t=>t.addEventListener('click',()=>{t.parentElement.querySelectorAll('[role=tab]').forEach(x=>{const on=x===t;x.setAttribute('aria-selected',on);const pn=document.getElementById(x.getAttribute('aria-controls'));if(pn)pn.hidden=!on})}));
fetch('https://api.github.com/repos/Fargaly/ArchHub').then(r=>r.ok?r.json():null).then(g=>{if(!g)return;const v={stars:g.stargazers_count,issues:g.open_issues_count};document.querySelectorAll('[data-gh]').forEach(e=>{if(e.dataset.gh in v)e.textContent=v[e.dataset.gh]})}).catch(()=>{});
(()=>{const q=document.getElementById('cmq'),pr=document.getElementById('cmprog'),k=document.getElementById('cmk');if(!q)return;
const run=()=>{const t=q.value.trim().toLowerCase();document.querySelectorAll('.cm-jobs .job').forEach(el=>{const h=el.querySelector('.job-h');el.hidden=!((!t||el.textContent.toLowerCase().includes(t))&&(!pr||pr.value.startsWith('All')||(h&&h.textContent.includes(pr.value)))&&(!k||k.value!=='Skills'))})};
q.addEventListener('input',run);if(pr)pr.addEventListener('change',run);if(k)k.addEventListener('change',run)})();
// BABOOM's greeting shows only while it covers no text (founder: nothing may cover the work).
const fits=b=>{const r=b.getBoundingClientRect();const tw=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;while(n=tw.nextNode()){if(!n.textContent.trim()||n.parentElement.closest('.bbm-ask,.bbm-bub,.bbm-chat'))continue;const g=document.createRange();g.selectNodeContents(n);for(const t of g.getClientRects())if(t.right>r.left&&t.left<r.right&&t.bottom>r.top&&t.top<r.bottom)return false}return true};
const place=()=>document.querySelectorAll('.bbm-bub').forEach(b=>{b.classList.add('fits');b.classList.toggle('fits',fits(b))});
setInterval(place,400);addEventListener('scroll',place,{passive:true});
const mb=document.getElementById('menubtn');if(mb)mb.onclick=()=>{const o=document.getElementById('top').classList.toggle('sheet-open');mb.setAttribute('aria-expanded',o)};
const here=location.pathname;document.querySelectorAll('#top .nav > a,#top .nav .dd > button').forEach(a=>{const h=a.getAttribute('href')||'/baboom/';if(h==='/'?here==='/':here.startsWith(h))a.setAttribute('aria-current','page')});
const paintRel=v=>{document.querySelectorAll('[data-rel]').forEach(e=>{const k=e.dataset.rel;if(!(k in v))return;if(k==='url')e.href=v.url;else e.textContent=v[k]});
document.querySelectorAll('a[data-dl]').forEach(e=>e.href=v.url);document.querySelectorAll('[data-build]').forEach(e=>e.textContent=v.tag);
const meta=document.querySelector('meta[name="archhub-build"]');if(meta)meta.setAttribute('content',v.tag);
const note=document.querySelector('[data-rel-note]');if(note)note.hidden=true};
const installer='ArchHub-Setup-0.exe', repo='https://github.com/Fargaly/ArchHub/releases/download/build-';
function releaseFacts(id,sha,bytes,date){
 if(typeof id!=='string'||!/^[A-Za-z0-9._-]{1,128}$/.test(id)||typeof sha!=='string'||!/^[0-9a-f]{64}$/i.test(sha)||!Number.isSafeInteger(bytes)||bytes<=0)return null;
 return {tag:id,sha:sha.toLowerCase(),url:repo+id+'/'+installer,size:installer+', '+Math.round(bytes/1048576)+' MB',
  date:Number.isFinite(Date.parse(date))?new Date(date).toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'}):''};
}
function fromOffer(d){
 return d?.asset_name===installer?releaseFacts(d.build_id,d.asset_sha256,d.asset_bytes,d.built_at):null;
}
function fromGitHub(r){
 if(r?.draft!==false||r.prerelease!==false||!r.tag_name?.startsWith('build-')||!Array.isArray(r.assets))return null;
 const id=r.tag_name.slice(6), asset=r.assets.find(a=>a.name===installer);
 if(!asset)return null;
 const notes=r.body||'', bodyId=/^BUILD_ID: (\\S+)\\s*$/m.exec(notes)?.[1];
 const bodySha=/^SHA256 ArchHub-Setup-0\\.exe: ([0-9a-f]{64})(?: \\([0-9]+ bytes\\))?\\s*$/im.exec(notes)?.[1]?.toLowerCase();
 const assetSha=/^sha256:([0-9a-f]{64})$/i.exec(asset.digest||'')?.[1]?.toLowerCase();
 if((bodyId&&bodyId!==id)||(asset.digest&&!assetSha)||(bodySha&&assetSha&&bodySha!==assetSha))return null;
 const facts=releaseFacts(id,assetSha||bodySha,asset.size,r.published_at);
 return facts&&facts.url===asset.browser_download_url?facts:null;
}
async function readRelease(url,parse){
 try{const response=await fetch(url);return response.ok?parse(await response.json()):null;}
 catch{return null;}
}
if(document.querySelector('[data-rel]')){
 (async()=>{
  const facts=await readRelease('https://api.github.com/repos/Fargaly/ArchHub/releases/latest',fromGitHub)||await readRelease('/download.json',fromOffer);
  if(facts)paintRel(facts);
  else{const note=document.querySelector('[data-rel-note]');if(note)note.hidden=false;}
 })();
}
})()</script>"""


def design():
    return json.loads(DESIGN.read_text(encoding="utf-8"))


def from_design(markup):
    """Turn the design's one-page prototype markup into this site's real addresses and honest states."""
    def route(match):
        path = match.group(1).split("?")[0]
        if path in DESIGN_MOVED:
            return f'href="{DESIGN_MOVED[path]}'
        if path.startswith("/community/people/"):
            return 'href="/community/'
        if path.startswith("/docs/tutorial-"):
            return 'href="/docs/'  # the design's tutorials follow retired starters; the Docs index stands in
        if path.startswith("/baboom/"):
            return f'href="https://baboom.archhub.io/{path.split("/")[2]}/index.html'
        return 'href="' + (path.rstrip("/") + "/" if path not in ("", "/") else "/")
    markup = re.sub(r'href="#(/[^"#]*)', route, markup)
    markup = markup.replace('src="site-assets/', 'src="/assets/')
    markup = re.sub(r'<nav([^>]*) data-sidenav></nav>', lambda m: f'<nav{m.group(1)}>' + side_nav() + '</nav>', markup)
    markup = re.sub(r'(<section class="page"[^>]*?) hidden>', r'\1>', markup)
    markup = re.sub(r'\s*<a href="https://api\.archhub\.io/founder"[^>]*>.*?</a>', "", markup)
    markup = re.sub(r'<a href="/community/">Public profile</a>', "", markup)
    markup = re.sub(r'<nav class="sub-bar".*?</nav>', "", markup, flags=re.S)
    # No people page yet (717, 18 Nov): the People tab, its panel and the footer link stay out.
    markup = re.sub(r'<button[^>]*aria-controls="cm-people"[^>]*>.*?</button>', "", markup, flags=re.S)
    markup = re.sub(r'\s*<div class="cm-panel" id="cm-people".*?</p>\s*</div>', "", markup, flags=re.S)
    markup = markup.replace('<li><a href="/community/">People</a></li>', "")
    def form(match):
        label = re.search(r"<label[^>]*>(.*?)</label>", match.group(0), re.S)
        title = re.sub(r"<[^>]+>", "", label.group(1)).strip() if label else "This form"
        return f'<div class="soon-form">{html.escape(title)} {soon_chip()}</div>'
    markup = re.sub(r'<form class="[^"]*lead-f[^"]*".*?</form>', form, markup, flags=re.S)
    return re.sub(r'<b class="soonchip">[^<]*</b>', soon_chip(), markup)


def release_facts(markup):
    """The stable download works even when its current metadata cannot be verified."""
    facts = {"tag": "Latest stable release", "sha": "Checksum unavailable", "date": "", "size": "ArchHub-Setup-0.exe"}
    markup = re.sub(r'(<p[^>]*data-rel-note[^>]*>)[^<]*', r'\g<1>Current release details are unavailable.', markup)
    markup = re.sub(r'(<[^>]*data-rel="(tag|sha|date|size)"[^>]*>)[^<]*', lambda m: m.group(1) + html.escape(facts[m.group(2)]), markup)
    markup = re.sub(r'(<a[^>]*data-rel="url"[^>]*href=")[^"]*', r'\g<1>' + LATEST_INSTALLER, markup)
    markup = re.sub(r'(<a[^>]*href=")[^"]*("[^>]*data-rel="url")', r'\g<1>' + LATEST_INSTALLER + r'\g<2>', markup)
    return re.sub(r'\s*<a href="/download/">Plans</a>', "", markup)


def guides():
    """The design's docs guides (tutorials follow starters that this release does not ship)."""
    return [d for d in design()["docs"] if d[2] == "Guides"]


def side_nav():
    esc = html.escape
    return ("<h4>Guides</h4>" + "".join(f'<a href="/docs/{d[0]}/">{esc(d[1].split(":")[0])}</a>' for d in guides())
            + '<h4>Reference</h4><a href="/docs/nodes/">Node reference</a><a href="/search/">Search</a>'
            + '<h4>Office standard (BABOOM)</h4><a href="https://baboom.archhub.io/">BABOOM home</a>'
            + '<a href="https://baboom.archhub.io/libraries/index.html">Libraries</a>')


def app_guides():
    """The in-app guides (site_export._DOCS_TEMPLATES), read from the source's syntax tree, never imported."""
    tree = ast.parse((ROOT / "01.APP/nodelang/site_export.py").read_text(encoding="utf-8"))
    value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and getattr(node.targets[0], "id", "") == "_DOCS_TEMPLATES")
    return ast.literal_eval(value.args[0])


def doc_article(template, index, build_id):
    esc = html.escape
    rows = guides()
    row = rows[index]
    official = app_guides().get(row[0])
    if official:
        title, lede, text = official
        group = row[2]
        where = row[-1] if len(row) > 3 else "Open ArchHub from the Start menu."
        lede = lede.replace("{build}", build_id)
        text = re.sub(r"(?m)^\{(?:connectors|operations|catalogue)\}[ \t]*$", "", text)
        # Drop headings whose entire body is generated by the installed package.
        parts = text.replace("{build}", build_id).split("\n## ")
        body = markdown("\n## ".join(part for offset, part in enumerate(parts)
                                      if not offset or "\n" in part.strip()))
        if row[0] == "getting-started":
            issues_url = next(link["url"] for link in load_links() if link["kind"] == "issues")
            body += ('<p><a href="/download/">Download ArchHub</a> · <a href="/account/">Your account</a> · '
                     '<a href="/security/">Account privacy</a> · '
                     f'<a href="{esc(issues_url, quote=True)}">Report a problem</a></p>')
    else:
        _, title, group, lede, paragraphs, where = row
        body = "<h2>How it works</h2>" + "".join(f"<p>{esc(t)}</p>" for t in paragraphs)
    following = rows[(index + 1) % len(rows)]
    fill = {"crumb": esc(group), "title": esc(title), "lede": esc(lede), "body": body, "app": esc(where)}
    markup = template
    for key, value in fill.items():
        markup = re.sub(rf'(<[^>]*data-a="{key}"[^>]*>)(</)', lambda m: m.group(1) + value + m.group(2), markup, count=1)
    markup = re.sub(r'<a data-a="next" href="[^"]*"></a>', f'<a data-a="next" href="/docs/{following[0]}/">{esc(following[1])}</a>', markup)
    return from_design(markup)


def soon_chip():
    """The one place the site marks a part that is not built yet (founder rule: show it, mark it, never fake it)."""
    return '<b class="soonchip">Coming soon</b>'


def account_page():
    esc = html.escape
    def row(key, label, kind):
        if kind == "edit":
            value = f'<input data-k="{key}" aria-label="{esc(label)}" disabled>'
            return f'<div class="accr"><span>{esc(label)}</span>{value}</div>'
        return f'<div class="accr ro"><span>{esc(label)}</span><span class="rov" data-k="{key}" style="white-space:pre-line">—</span></div>'
    nav = "".join(f'<a href="#{sid}">{esc(title)}</a>' for sid, title, _ in ACCOUNT_SECTIONS)
    body = "".join(f'<section class="accs" id="{sid}"><h2>{esc(title)}</h2>' + "".join(row(*r) for r in rows) + "</section>"
                   for sid, title, rows in ACCOUNT_SECTIONS)
    return ('<section class="acc"><div class="acch"><span class="av big" id="accav">A</span><div><h1 id="accname">Your account</h1>'
            '<p class="sub" style="margin:2px 0 0">The same values as Settings › Account in ArchHub. Name and firm change here or in the app. '
            + soon_chip() + ' the rest edits here too; for now change it in ArchHub.</p></div>'
            '<a class="open" id="accin" href="https://api.archhub.io/signin">Sign in</a><a class="open" href="archhub://settings/account">Open in ArchHub</a></div>'
            '<p class="accmsg" id="accmsg" role="status"></p>'
            f'<div class="accg"><nav class="accn" aria-label="Account sections">{nav}</nav><div>{body}</div></div>'
            '<p class="foot">This PC’s settings (workspaces, files, privacy, programs) stay in the app on that PC and are not shown here.</p></section>' + ACCOUNT_SCRIPT)


# BABOOM, the companion: one source on baboom.archhub.io, loaded by every page (no copy here).
COMPANION = '<link rel="stylesheet" href="https://baboom.archhub.io/companion/baboom-companion.css"><script src="https://baboom.archhub.io/companion/baboom-pages.js" defer></script>'
# GitHub serves the newest release's installer at this fixed address, so the link follows every release.
LATEST_INSTALLER = "https://github.com/Fargaly/ArchHub/releases/latest/download/ArchHub-Setup-0.exe"
# Changelog: baked CHANGELOG.md is the fallback; at load time GitHub releases replace the list so a
# redeploy is not required for every published build. Release bodies that only carry the Build block
# are shown as published-build rows (no invented product notes).
CHANGELOG_SCRIPT = """<script>(()=>{const root=document.getElementById('changelog-live');if(!root)return;
const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const bid=tag=>String(tag||'').replace(/^build-/,'');
const text=body=>String(body||'').replace(/\\r\\n/g,'\\n');
const section=(body,name)=>{
  const lines=text(body).split('\\n');
  const start=lines.findIndex(line=>line.trimEnd()==='## '+name);
  if(start<0)return [];
  const rest=lines.slice(start+1),end=rest.findIndex(line=>line.startsWith('## '));
  return end<0?rest:rest.slice(0,end);
};
const bullets=(body,name)=>section(body,name).filter(line=>line.startsWith('- ')).map(line=>line.slice(2).trim());
const meta=body=>{const o={};text(body).split(/\\n/).forEach(line=>{const m=/^(BUILD_ID|BUILT_AT|SOURCE_REVISION):\\s*(.+)$/.exec(line);if(m)o[m[1]]=m[2].trim();const s=/^SHA256 ArchHub-Setup-0\\.exe:\\s*([0-9a-fA-F]{64})/.exec(line);if(s)o.SHA256=s[1].toLowerCase()});return o};
const title=id=>{const d=/^(\\d{4})(\\d{2})(\\d{2})-(\\d{2})(\\d{2})/.exec(id);return d?d[1]+'-'+d[2]+'-'+d[3]+' \\u00b7 '+d[4]+':'+d[5]:id};
const entry=(id,body)=>{
  const original=bullets(body,'What changed');
  const items=original.length?original:bullets(body,'Changes');
  if(items.length){
    const gaps=bullets(body,'Known gaps');
    if(gaps.length)items.push('Known gaps: '+gaps.join('; '));
  }else{
    const m=meta(body);
    items.push('Published build '+id+(m.SOURCE_REVISION?' (source '+m.SOURCE_REVISION.slice(0,7)+').':''));
    if(m.SHA256)items.push('Installer SHA-256: '+m.SHA256+'.');
    if(m.BUILT_AT)items.push('Built at '+m.BUILT_AT+'.');
  }
  const verification=section(body,'Verification scope').map(line=>line.trim().replace(/^- /,'')).filter(Boolean).join(' ');
  if(verification)items.push('Verification scope: '+verification);
  return '<h2>'+esc(title(id))+'</h2><ul>'+items.map(item=>'<li>'+esc(item)+'</li>').join('')+'</ul>';
};
let page=1,rows=[];const load=()=>fetch('https://api.github.com/repos/Fargaly/ArchHub/releases?per_page=100&page='+page).then(r=>r.ok?r.json():Promise.reject(r.status)).then(batch=>{rows.push(...(batch||[]).filter(x=>!x.draft&&!x.prerelease));if(batch&&batch.length===100){page+=1;return load()}return rows});
load().then(list=>{if(!list.length)return;root.innerHTML=list.map(r=>entry(bid(r.tag_name),r.body||'')).join('')}).catch(()=>{})})()</script>"""


def build_site(output, build_id, installer_url, sha256):
    parsed = urlsplit(installer_url)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", build_id):
        raise ValueError("Invalid build id")
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or build_id not in parsed.path:
        raise ValueError("Installer must be an HTTPS address pinned to the given build id")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256):
        raise ValueError("Installer SHA-256 must contain 64 hexadecimal characters")
    links = load_links()
    by_kind = {row["kind"]: row for row in links}
    esc = html.escape
    entries = changelog_entries()
    if not entries:
        raise ValueError("Changelog has no release notes")
    data = catalogue()
    look = design()
    pages = {"account/index.html": ("Your account", account_page()),
             "docs/nodes/index.html": ("Node reference", nodes_index(data)),
             "search/index.html": ("Search", search_page())}
    pages["changelog/index.html"] = ("Changelog", '<section class="page"><h1>Changelog</h1><p class="lede">Every released build, newest first. This page follows GitHub releases when they answer.</p>'
                                     + '<div id="changelog-live">' + "".join(markdown("## " + title + "\n\n" + body) for title, body in entries) + "</div>"
                                     + CHANGELOG_SCRIPT + "</section>")
    for route, markup in look["pages"].items():
        if route in DESIGN_SKIP or route.startswith("/baboom/") or route == "/changelog":
            continue
        name = "404.html" if route == "404" else route.strip("/") + "/index.html" if route != "/" else "index.html"
        if route == "/download":
            guide = app_guides()["account-web"][2]
            answer = guide.split("## What needs an account\n\n", 1)[1].split("\n\n", 1)[0]
            markup, count = re.subn(r"(<summary>Do I need an account\?</summary>\s*<p>)[^<]+(?=<a )",
                                    lambda match: match[1] + html.escape(answer) + " ", markup)
            if count != 1:
                raise ValueError("Expected one account FAQ on the download page")
        title = re.search(r'aria-label="([^"]+)"', markup)
        pages[name] = (title.group(1) if title and route != "/" else "ArchHub", release_facts(from_design(markup)))
    for index, row in enumerate(guides()):
        pages[f"docs/{row[0]}/index.html"] = (row[1], doc_article(look["pages"]["/docs/*"], index, build_id))
    labels = {c["id"]: c["label"] for c in data["categories"]}
    for node in data["nodes"]:
        pages[f"docs/nodes/{slug(node['id'])}/index.html"] = (node["title"], node_page(node, labels.get(node["cat"], node["cat"])))
    for starter in data["starters"]:
        pages[f"community/{slug(starter['id'])}/index.html"] = (starter["title"], starter_page(starter))
    output = Path(output)
    for path, (title, body) in pages.items():
        description = "A visual node application where people, AI agents and programs work together across engineering work."
        document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="archhub-build" content="' + esc(build_id, quote=True) + '"><title>' + esc(title) + ' | ArchHub</title><meta name="description" content="' + description + '"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="any"><meta property="og:type" content="website"><meta property="og:title" content="' + esc(title, quote=True) + ' | ArchHub"><meta property="og:description" content="' + description + '"><meta property="og:image" content="' + esc(by_kind["site"]["url"].rstrip("/") + '/og.png', quote=True) + '"><meta property="og:url" content="' + esc(by_kind["site"]["url"].rstrip("/") + ('/' if path == 'index.html' else '/' + path.removesuffix('index.html')), quote=True) + '"><style>' + look['css'] + COMPONENT_CSS + '</style></head><body><a class="skip" href="#main">Skip to content</a>' + from_design(look["header"]) + '<main id="main" class="wrap">' + body + '</main>' + from_design(look["footer"]) + COMPANION + UI_SCRIPT + '</body></html>'
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
    (output / "search.json").write_text(json.dumps(search_index(data), ensure_ascii=False), encoding="utf-8")
    for name in ("favicon.svg", "favicon.ico", "og.png"):
        shutil.copyfile(HERE / "static" / name, output / name)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    for name in ("home", "canvas", "library", "settings", "bbm-wave", "bbm-sprite"):
        shutil.copyfile(HERE / "assets" / (name + ".png"), assets / (name + ".png"))
    fonts = output / "assets/fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    for name in ("inter-variable.woff2", "jetbrains-mono-regular.woff2", "OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
        shutil.copyfile(BRAND / "fonts" / name, fonts / name)
    print(f"Static site: {output.resolve()} (build {build_id})")


def prepare_deploy_context(output, build_id, installer_url, sha256):
    """Build the public files and the serving configuration for the existing Fly app."""
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a new website output folder")
    site = output / "site"
    build_site(site, build_id, installer_url, sha256)
    identity = re.compile(r"fargool|ahmed|api\.archhub\.io/founder|founder of archhub", re.I)
    pages = list(site.rglob("*.html"))
    if not pages or any(identity.search(page.read_text(encoding="utf-8")) for page in pages):
        raise ValueError("Public identity scan did not pass")

    # These files are generated for the host, outside the public site's root.
    (output / "Dockerfile").write_text(
        'FROM caddy:2.8.4-alpine@sha256:af32e97399febea808609119bb21544d0265c58a02836576e32a2d082c262c17\n'
        'COPY Caddyfile /etc/caddy/Caddyfile\n'
        'COPY site/ /srv/\n', encoding="utf-8")
    (output / ".dockerignore").write_text(
        '*\n!Dockerfile\n!Caddyfile\n!site/\n!site/**\n', encoding="utf-8")
    (output / "Caddyfile").write_text(''':3000 {
	header Cache-Control "no-cache"
	@baboom path /api/chat /api/auth/* /signin
	handle @baboom {
		reverse_proxy https://baboom.archhub.io {
			header_up Host baboom.archhub.io
			header_up X-BBM-Site archhub.io
		}
	}
	redir /baboom* https://baboom.archhub.io/ 302
	redir /download.json https://github.com/Fargaly/ArchHub/releases/latest/download/release.json 302
	handle {
		root * /srv
		file_server
	}
	handle_errors {
		@missing expression {err.status_code} == 404
		handle @missing {
			root * /srv
			rewrite * /404.html
			file_server
		}
	}
}
''', encoding="utf-8")
    (output / "fly.toml").write_text('''app = "archhub-web"
primary_region = "ord"

[build]
  dockerfile = "Dockerfile"
  ignorefile = ".dockerignore"

[http_service]
  internal_port = 3000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0
  processes = ["app"]

  [http_service.concurrency]
    type = "requests"
    hard_limit = 200
    soft_limit = 150

  [[http_service.checks]]
    interval = "30s"
    timeout = "5s"
    grace_period = "5s"
    method = "GET"
    path = "/"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
''', encoding="utf-8")
    print(f"Fly context: {output.resolve()} ({len(pages)} HTML pages passed identity scan)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--installer-url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deploy-context", action="store_true", help="prepare the static Fly deployment context")
    args = parser.parse_args()
    prepare = prepare_deploy_context if args.deploy_context else build_site
    prepare(args.output, args.build_id, args.installer_url, args.sha256)


if __name__ == "__main__":
    main()
