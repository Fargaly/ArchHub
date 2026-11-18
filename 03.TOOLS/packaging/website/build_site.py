"""Build the public static site without importing the application runtime."""
import argparse
import ast
import html

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


def documentation_sections(page, wanted):
    # Read literal documentation only: importing site_export would load catalogues.
    tree = ast.parse((ROOT / "01.APP/nodelang/site_export.py").read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "_DOCS_TEMPLATES"
                              for target in node.targets))
    pages = ast.literal_eval(assignment.value.args[0])
    body = pages[page][2]
    sections = dict((part.split("\n", 1)[0], part.split("\n", 1)[1])
                    for part in body.split("## ")[1:])
    return "\n\n".join("## " + title + "\n" + sections[title].strip() for title in wanted)


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


# BABOOM, the companion: one source on baboom.archhub.io, loaded by every page (no copy here).
COMPANION = '<link rel="stylesheet" href="https://baboom.archhub.io/companion/baboom-companion.css"><script src="https://baboom.archhub.io/companion/baboom-pages.js" defer></script>'
# GitHub serves the newest release's installer at this fixed address, so the link follows every release.
LATEST_INSTALLER = "https://github.com/Fargaly/ArchHub/releases/latest/download/ArchHub-Setup-0.exe"
# Follow the latest GitHub release at load time; the pinned build stays when GitHub does not answer.
LATEST = """<script>fetch('https://api.github.com/repos/Fargaly/ArchHub/releases/latest').then(r=>r.ok?r.json():null).then(r=>{if(!r)return;var a=(r.assets||[]).find(x=>x.name==='ArchHub-Setup-0.exe'),b=/^BUILD_ID: ([A-Za-z0-9._-]+)$/m.exec(r.body||'');if(!a||!b||a.browser_download_url.indexOf(b[1])<0)return;document.querySelectorAll('a[data-dl]').forEach(e=>e.href=a.browser_download_url);document.querySelectorAll('[data-build]').forEach(e=>e.textContent=b[1])}).catch(()=>{})</script>"""
LOGO = '<svg viewBox="0 0 64 64" width="28" height="28" aria-hidden="true"><path d="M10 56 V32 a22 22 0 0 1 44 0 V56" fill="none" stroke="#d97757" stroke-width="4.5" stroke-linecap="square"/><circle cx="32" cy="22" r="5.2" fill="none" stroke="#d97757" stroke-width="2.4"/><circle cx="32" cy="22" r="1.8" fill="#d97757"/><path d="M6 58 H58" stroke="#d97757" stroke-width="1.5" stroke-linecap="round"/></svg>'
CSS = '''
@font-face{font-family:Inter;src:url('/assets/fonts/inter-variable.woff2') format('woff2');font-weight:100 900;font-display:swap}
@font-face{font-family:'JetBrains Mono';src:url('/assets/fonts/jetbrains-mono-regular.woff2') format('woff2');font-display:swap}

/* archhub.io boards (res-022): the same tokens as the app (Penpot r1968), the same item card and node page as in ArchHub */
:root{color-scheme:dark;--bg:#0e0e11;--bgPanel:#15151a;--bgSoft:#1c1c23;--bgRaised:#1d1d22;--bgHover:#22222a;--line:#26262e;--lineSoft:#1e1e24;--ink:#ece8e0;--ink2:#9b938a;--ink3:#8b837a;--onFill:#180f08;
 --accent:#d97757;--accentSoft:#3a2018;--ok:#7ec18e;--warn:#e5b25a;--err:#e6705f;--cyan:#5fb3b3;--blue:#7898d6;--purple:#a98cd6;--f-ui:"Inter",system-ui,sans-serif;--f-mono:"JetBrains Mono",ui-monospace,monospace;
 --e1:inset 0 1px 0 rgba(255,255,255,.04),0 1px 2px rgba(0,0,0,.4)}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){color-scheme:light;--bg:#f7f4ee;--bgPanel:#fbf9f4;--bgSoft:#efebe3;--bgRaised:#fbf9f4;--bgHover:#e9e4da;--line:#e3ddd0;--lineSoft:#ebe6dc;--ink:#1a1612;--ink2:#6b6256;--ink3:#6b6256;--accent:#c96442;--accentSoft:#f6dfd5}}
:root[data-theme="dark"]{color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--f-ui);-webkit-font-smoothing:antialiased}
a{color:inherit}button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:20px;height:60px;padding:0 24px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--lineSoft)}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;text-decoration:none}.top nav{display:flex;gap:4px}.top nav a{padding:6px 10px;border-radius:6px;text-decoration:none;color:var(--ink2)}.top nav a[aria-current=true]{color:var(--ink);background:var(--bgSoft)}
.sbox{margin-left:auto;display:flex;align-items:center;gap:8px;width:min(340px,40vw);height:34px;padding:0 10px;border-radius:8px;background:var(--bgPanel);border:1px solid var(--line);color:var(--ink3)}.sbox input{flex:1;min-width:0;background:none;border:0;color:var(--ink);font:inherit;outline:none}
.wrap{max-width:1080px;margin:0 auto;padding:28px 24px 64px}
.tabs{display:flex;gap:6px;margin:0 0 22px}.tabs button{padding:6px 12px;border-radius:999px;border:1px solid var(--line);color:var(--ink2)}.tabs button[aria-pressed=true]{color:var(--ink);border-color:var(--accent);background:var(--accentSoft)}
section[hidden]{display:none}
h1{margin:0;font-size:28px;letter-spacing:-.01em}h2{margin:0 0 6px;font-size:18px}h3{margin:22px 0 8px;font-size:14px}.sub{color:var(--ink2);margin:4px 0}
.item{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px;align-items:start}
.tile{width:36px;height:36px;border-radius:8px;display:grid;place-items:center;color:var(--onFill);flex:none}.fam-effect{background:var(--accent)}.fam-list{background:var(--purple)}.fam-model{background:var(--blue)}.fam-check{background:var(--warn)}
.ih{display:flex;gap:14px;align-items:flex-start}.by{display:flex;align-items:center;gap:8px;color:var(--ink2);font-size:13px;margin-top:6px;flex-wrap:wrap}.av{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:var(--bgHover);font-size:11px;font-weight:600}
.verif{color:var(--ok)}.chip{display:inline-block;padding:2px 8px;border-radius:999px;font:500 12px var(--f-mono);box-shadow:inset 0 0 0 1px var(--line)}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:18px;border-radius:10px;background:var(--bgPanel);border:1px solid var(--line);margin-top:18px}
.fn{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;background:var(--bgSoft);border:1px solid var(--line);font-size:13px}.fn .tile{width:20px;height:20px;border-radius:5px}.fw{width:24px;height:2px;background:var(--ink3)}
.side{position:sticky;top:84px;display:grid;gap:12px;padding:18px;border-radius:10px;background:var(--bgPanel);border:1px solid var(--line);box-shadow:var(--e1)}
.open{display:flex;align-items:center;justify-content:center;gap:8px;height:40px;border-radius:8px;background:var(--accent);color:var(--onFill);font-weight:600;text-decoration:none}
.facts{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:13px}.facts dt{color:var(--ink3)}.facts dd{margin:0}
.ok{color:var(--ok)}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:13px}td{padding:8px 10px;border-top:1px solid var(--lineSoft);vertical-align:top}tr:first-child td{border-top:0;color:var(--ink3);font-size:12px}
.tw{border-radius:10px;border:1px solid var(--line);background:var(--bgPanel);overflow:auto}
.sk{display:inline-block;width:10px;height:10px;border-radius:50%;border:2px solid var(--c);vertical-align:-1px;margin-right:6px}.sk.l{border-radius:3px;transform:rotate(45deg) scale(.86)}.t-file{--c:var(--ok)}.t-elements{--c:var(--accent)}.t-text{--c:var(--ink2)}
.res h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink3);margin:22px 0 8px}
.r{display:flex;gap:12px;align-items:center;padding:12px 14px;border-radius:8px;background:var(--bgPanel);border:1px solid var(--line);margin-bottom:6px;text-decoration:none}.r em{font-style:normal;color:var(--ink3);font-size:12px;margin-left:auto}
.foot{margin-top:28px;color:var(--ink3);font-size:12px}
@media (max-width:760px){.top{gap:10px;padding:0 16px}.top nav{display:none}.sbox{width:auto;flex:1}.wrap{padding:20px 16px 48px}.item{grid-template-columns:minmax(0,1fr)}.side{position:static}}

.top{height:auto;min-height:60px;flex-wrap:wrap}.top nav a[aria-current=page]{color:var(--ink);background:var(--bgSoft)}
.top .open{margin-left:auto;height:34px;padding:0 14px;font-size:13px}.top nav{flex-wrap:wrap}
.wrap{padding-top:48px}.intro{max-width:760px;margin-bottom:32px}.intro h1{font-size:clamp(30px,4vw,46px);line-height:1.15;letter-spacing:-.035em}.lede{font-size:18px;line-height:1.65;color:var(--ink2);max-width:68ch}
.section{margin-top:60px}.section>h2{font-size:24px;margin-bottom:12px}.section>p{color:var(--ink2);max-width:72ch}
figure{margin:24px 0 0}figure img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:10px;background:var(--bgPanel)}figcaption{font-size:12px;color:var(--ink2);margin-top:10px;line-height:1.6}
.screen-pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}.screen-pair figure{min-width:0}.screen-pair h3{font-size:18px;margin-bottom:10px}
.steps{display:grid;grid-template-columns:1fr 1fr;gap:22px 40px;padding-left:24px}.steps li{padding-left:6px}.steps h3{margin:0 0 6px;font-size:16px}.steps p{margin:0;color:var(--ink2)}
.prose h2{margin:32px 0 10px;font-size:20px}.prose p,.prose li{color:var(--ink2);line-height:1.8}.prose li{margin-bottom:8px}.prose code{font:12px var(--f-mono);color:var(--ink);overflow-wrap:anywhere}
.side .sub{font-size:13px}.side a:not(.open){color:var(--ink)}.side .facts{margin:4px 0}.facts dd{overflow-wrap:anywhere}
.programs{margin-top:22px}.programs td:first-child{color:var(--ink);font-size:14px;width:28%}.programs tr:first-child td{font-size:14px;color:var(--ink2)}.programs tr:first-child td:first-child{color:var(--ink)}
.agents{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}.agents span{padding:8px 14px;background:var(--bgPanel);border:1px solid var(--line);border-radius:6px}
.release{padding:20px 24px;border:1px solid var(--line);border-radius:10px;background:var(--bgPanel)}.release h3{margin-top:0}.release ul{padding-left:20px;color:var(--ink2)}
footer{border-top:1px solid var(--lineSoft);padding:28px 24px 36px;max-width:1080px;margin:auto}footer nav{display:flex;flex-wrap:wrap;gap:12px 24px;font-size:12px;color:var(--ink2)}footer .brand{margin-bottom:18px}a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:4px}a:hover{color:var(--accent)}.open:hover{background:var(--ink);color:var(--onFill)}
.skip{position:absolute;left:24px;top:-80px;z-index:10}.skip:focus{top:4px;background:var(--bgPanel);padding:8px}.community .r{padding:18px;margin:14px 0}.community .r strong{display:block;font-size:16px}.community .r p{margin:4px 0 0;color:var(--ink2)}
@media(max-width:760px){.top nav{display:flex;gap:0;order:3;width:100%;padding-bottom:8px}.top nav a{padding:6px 9px}.wrap{padding-top:28px}.screen-pair,.steps{grid-template-columns:1fr}.item{gap:22px}.side{position:static}.section{margin-top:40px}.community .r{align-items:flex-start}.community .r em{display:none}}
'''


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
    def link(kind):
        row = by_kind[kind]
        return f'<a href="{esc(row["url"], quote=True)}">{esc(row["name"])}</a>' + (" (not enabled)" if row.get("available") is False else "")
    footer = "".join("<span>" + link(row["kind"]) + "</span>" for row in links)
    entries = changelog_entries()
    if not entries:
        raise ValueError("Changelog has no release notes")
    top_title, top_notes = entries[0]
    download = f'<a class="open" data-dl href="{LATEST_INSTALLER}">Download for Windows</a>'
    install_panel = '<aside class="side" aria-label="Download">' + download + '<p class="sub">Build <span data-build>' + esc(build_id) + '</span>, the latest release.</p><dl class="facts"><dt>Platform</dt><dd>Windows</dd><dt>Files</dt><dd>.archhub workflows</dd><dt>Runs</dt><dd>On your PC</dd></dl><a href="https://github.com/Fargaly/ArchHub/releases/latest/download/release.json">Build and download verification</a><a href="/docs/getting-started/">Read the getting-started guide</a></aside>'
    def screen(name, caption, eager=False):
        return f'<figure><a href="/assets/{name}.png" aria-label="View {name} design at full size"><img src="/assets/{name}.png" width="1600" height="1000" alt="ArchHub {name.title()} design" loading="{"eager" if eager else "lazy"}"></a><figcaption>{caption} Design of the current app, rendered from frozen v48; example data, not a live project or a completed run.</figcaption></figure>'
    docs = documentation_sections("getting-started", ("Install", "First open"))
    docs += "\n\n## First session\n\nOpen Home and choose a starter, then choose Start. Start places the wired nodes on the canvas. It does not run them.\n\n## The Canvas\n\n"
    docs += "## Connect nodes\n\nConnect an output socket to a compatible input socket. Select a node to inspect its parameters and results.\n\n## Properties\n\nChange the node parameters for your task. Use Save or Ctrl S to save the workflow; use Save as to keep a separate .archhub file."
    docs += "\n\n## Run and Approve\n\nCheck the source connection and parameters before Run. Read each node's result. A missing host, account, or engine is a blocker, not a completed result. Outside changes still need the existing Approve flow.\n\nPress Run in the Canvas toolbar. If an Approve card appears, review the action before approving it."
    home = '''<div class="item"><div class="intro"><h1>People, AI agents and programs.<br>One place to work together.</h1>
<p class="lede">ArchHub is a visual node app for engineering work. Connect blocks on a canvas, then save the workflow as a <code>.archhub</code> file you can share.</p>
<p class="sub">The connectors, harness, hooks, guardrails and orchestration layer bring the work into one application.</p></div>''' + install_panel + '</div>'
    home += screen("canvas", "Canvas: wire nodes, change parameters and inspect each step.", eager=True)
    home += '''<section class="section"><h2>Work it out once. Run the workflow again.</h2><p>An agent can help work out the steps. Save those steps as nodes and run or change them again. Workflows made of program and data nodes run without an agent. Model steps still use their configured provider.</p>
<ol class="steps"><li><h3>Start a task</h3><p>Each task has its own canvas and thread. Open a starter from Home or continue an existing session.</p></li>
<li><h3>Connect the steps</h3><p>Choose nodes from the Library. Wire their sockets and set the parameters for your work.</p></li>
<li><h3>Run and review</h3><p>Pure steps re-solve when an input changes. Effects wait for Run and the Approve flow where required. Opening a file does not run it.</p></li>
<li><h3>Save and reuse</h3><p>Keep the workflow in a .archhub file. Share it, open it again, or change an input for the next job.</p></li></ol></section>'''
    home += '<div class="screen-pair"><section><h3>Home</h3>' + screen("home", "Home: sessions and the work that needs your attention.") + '</section><section><h3>Library</h3>' + screen("library", "Library: nodes organised by the work they do.") + '</section></div>'
    home += '''<section class="section"><h2>Inside the programs you use</h2><p>Host nodes connect to programs on your PC. The program and its connector must be available; a listed node is not a connected session.</p>
<div class="tw"><table class="programs"><tbody>
<tr><td>Revit</td><td>Find live sessions, read elements and export sheets to PDF.</td></tr>
<tr><td>AutoCAD</td><td>Read line work from the live drawing.</td></tr>
<tr><td>Excel</td><td>Read open workbooks and their sheets.</td></tr>
<tr><td>Outlook</td><td>Read the inbox and save an email draft for you to send.</td></tr>
</tbody></table></div></section>
<section class="section"><h2>Your agents, in the same work</h2><p>Connect installed agents through the shared agent interface. The work is not tied to one model vendor.</p><div class="agents"><span>Claude Code</span><span>Codex</span><span>OpenCode</span><span>Gemini CLI</span><span>Goose</span></div>'''
    home += screen("session", "Session node: the agent, its parameters and its task thread.") + '</section>'
    home += '<section class="section item"><div><h2>BABOOM, your companion</h2><p class="lede">An assistant alongside your engineering work.</p><p>' + link("baboom") + '</p></div><div><h2>Private by default</h2><p class="sub">ArchHub runs on your PC. Account sign-in uses Windows Credential Manager. Connected agents and services use their own network connections.</p></div></section>'
    home += '<section class="section"><h2>What’s new</h2><div class="release">' + markdown("### " + top_title + "\n\n" + top_notes) + '<a href="/changelog/">Read the changelog</a></div></section>'
    community = '<div class="item community"><div><div class="ih"><span class="tile fam-list">' + LOGO + '</span><div><h1>Community</h1><p class="sub">Questions, shared experience and problems to resolve.</p></div></div><p class="lede">Talk about how you use ArchHub, or report something that did not work.</p>'
    for kind, title, description in (("discuss", "Discussions", "Ask questions and share how you work with ArchHub."), ("issues", "Issues", "Report a reproducible problem. Include the build, the steps and what happened.")):
        community += f'<a class="r" href="{esc(by_kind[kind]["url"], quote=True)}"><div><strong>{title}</strong><p>{description}</p></div><em>GitHub ↗</em></a>'
    community += '<h3>Before you share</h3><p class="sub">Remove credentials and private project files. Describe the result you expected and the result you saw.</p></div><aside class="side"><h2>Find your way</h2>' + link("docs") + link("repo") + link("baboom") + '<p class="sub">Discussions and Issues are hosted on GitHub.</p></aside></div>'
    # /cloud/ goes live when 717 calls the app stable from the release checks (F412; plan names decided 18 Nov).
    signin = "https://api.archhub.io/signin"
    cloud = '<div class="item"><div class="intro"><h1>Your office on one account</h1><p class="lede">Create a free account, add your office and invite your team. Everyone works from the same standard, skills and agents, on any PC.</p>'
    cloud += f'<p><a class="open" style="display:inline-flex;padding:0 18px" href="{signin}">Create free account</a> <a href="{signin}">Sign in</a></p><p class="sub">Free in open beta. Your email is the account, never your machine. Continue with Google; the first sign-in creates the account.</p></div>'
    cloud += '<aside class="side" aria-label="Plan and access"><h2>Plan &amp; access</h2><p class="sub">The same screen in the app: Settings, Plan &amp; access.</p><dl class="facts"><dt>Plan</dt><dd>Solo · beta</dd><dt>You</dt><dd>Owner</dd><dt>A colleague</dt><dd>Member · invited</dd><dt>A reviewer</dt><dd>Viewer</dd></dl><p class="sub">Roles: Owner, Administrator, Member, Viewer.</p></aside></div>'
    cloud += '<section class="section"><h2>One account, from one person to a firm</h2><div class="tw"><table class="programs"><tbody><tr><td>Solo</td><td>An individual architect or freelancer.</td></tr><tr><td>Studio</td><td>A practice or project team, seats as you need them.</td></tr><tr><td>Firm</td><td>A large firm: ten seats and more, single sign-on and audit.</td></tr></tbody></table></div><p class="sub">All three are planned; everything is free in open beta.</p></section>'
    cloud += '<section class="section"><h2>Invite your office in a minute</h2><ol class="steps"><li><h3>Create your account</h3><p>Continue with Google, on this page or in the app.</p></li><li><h3>Name your office</h3><p>Your standard, templates and skills attach to it.</p></li><li><h3>Invite by email</h3><p>Each colleague joins with their own email and gets a role.</p></li><li><h3>Everyone opens the same work</h3><p>Shared skills appear in each person’s Library.</p></li></ol></section>'
    cloud += '<section class="section item"><div><h2>What works in this build</h2><div class="tw"><table class="programs"><tbody><tr><td class="ok">Working</td><td>Cloud models in the model picker</td></tr><tr><td class="ok">Working</td><td>Office, team, roles and invitations</td></tr><tr><td class="ok">Working</td><td>The same account on any PC you sign in on</td></tr><tr><td class="warn">Not active</td><td>Brain cloud sync and sharing between offices</td></tr></tbody></table></div><p class="sub">Without an account the canvas, files, your own model credential and connectors all work.</p></div>'
    cloud += '<div><h2>What stays on your PC</h2><ul class="sub"><li>Your .archhub files, sessions and settings</li><li>Your sign-in session, kept by Windows</li><li>Everything the host programs read</li></ul><h2>What leaves it, only when a node asks</h2><ul class="sub"><li>A model step sends its prompt to the provider you chose</li><li>A connected agent or service uses its own connection</li><li>Sign-in talks to Google and the ArchHub cloud</li></ul></div></section>'
    pages = {
        "index.html": ("ArchHub", home),
        "docs/getting-started/index.html": ("Getting started", '<div class="item"><article class="prose"><div class="ih"><span class="tile fam-model">' + LOGO + '</span><div><h1>Getting started</h1><p class="sub">Install, open a session and connect your first nodes.</p></div></div>' + markdown(docs.replace("{build}", "the selected release")) + '</article>' + install_panel + '</div>'),
        "community/index.html": ("Community", community),
        "changelog/index.html": ("Changelog", '<h1>Changelog</h1>' + "".join(markdown("## " + title + "\n\n" + body) for title, body in entries)),
        "404.html": ("Not found", '<h1>Page not found</h1><p><a href="/">Return to ArchHub</a></p>'),
    }
    output = Path(output)
    for path, (title, body) in pages.items():
        navigation = "".join(f'<a href="{route}"' + (' aria-current="page"' if path == target else '') + f'>{label}</a>' for route, target, label in (("/", "index.html", "Home"), ("/docs/getting-started/", "docs/getting-started/index.html", "Docs"), ("https://baboom.archhub.io", None, "BABOOM"), ("/community/", "community/index.html", "Community"), ("/changelog/", "changelog/index.html", "Changelog")))
        description = "A visual node application where people, AI agents and programs work together across engineering work."
        document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="archhub-build" content="' + esc(build_id, quote=True) + '"><title>' + esc(title) + ' | ArchHub</title><meta name="description" content="' + description + '"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="any"><meta property="og:type" content="website"><meta property="og:title" content="' + esc(title, quote=True) + ' | ArchHub"><meta property="og:description" content="' + description + '"><meta property="og:image" content="' + esc(by_kind["site"]["url"].rstrip("/") + '/og.png', quote=True) + '"><meta property="og:url" content="' + esc(by_kind["site"]["url"].rstrip("/") + ('/' if path == 'index.html' else '/' + path.removesuffix('index.html')), quote=True) + '"><style>' + CSS + '</style></head><body><a class="skip" href="#main">Skip to content</a><header class="top"><a class="brand" href="/">' + LOGO + 'ArchHub</a><nav aria-label="Site">' + navigation + '</nav>' + download + '</header><main id="main" class="wrap">' + body + '</main><footer><a class="brand" href="/">' + LOGO + 'ArchHub</a><nav aria-label="All ArchHub links">' + footer + '</nav></footer>' + LATEST + COMPANION + '</body></html>'
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
    for name in ("favicon.svg", "favicon.ico", "og.png"):
        shutil.copyfile(HERE / "static" / name, output / name)
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    for name in ("home", "canvas", "library", "session"):
        shutil.copyfile(HERE / "assets" / (name + ".png"), assets / (name + ".png"))
    fonts = output / "assets/fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    for name in ("inter-variable.woff2", "jetbrains-mono-regular.woff2", "OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
        shutil.copyfile(BRAND / "fonts" / name, fonts / name)
    print(f"Static site: {output.resolve()} (build {build_id})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--installer-url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build_site(args.output, args.build_id, args.installer_url, args.sha256)


if __name__ == "__main__":
    main()
