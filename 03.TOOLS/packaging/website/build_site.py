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
        safe = html.escape(block)
        safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
        if safe.startswith("#"):
            heading = re.match(r"(#{1,3}) (.*)", safe, re.S)
            if heading:
                level = len(heading[1])
                blocks.append(f"<h{level}>{heading[2]}</h{level}>")
                continue
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
    return [(title, body.strip()) for title, body in
            (part.split("\n", 1) for part in text.split("\n## ")[1:]) if body.strip()]


LOGO = '<svg viewBox="0 0 64 64" width="28" height="28" aria-hidden="true"><path d="M10 56 V32 a22 22 0 0 1 44 0 V56" fill="none" stroke="#d97757" stroke-width="4.5" stroke-linecap="square"/><circle cx="32" cy="22" r="5.2" fill="none" stroke="#d97757" stroke-width="2.4"/><circle cx="32" cy="22" r="1.8" fill="#d97757"/><path d="M6 58 H58" stroke="#d97757" stroke-width="1.5" stroke-linecap="round"/></svg>'
CSS = '''
@font-face{font-family:Inter;src:url('/assets/fonts/inter-variable.woff2') format('woff2');font-weight:400 600;font-display:swap}
@font-face{font-family:'JetBrains Mono';src:url('/assets/fonts/jetbrains-mono-regular.woff2') format('woff2');font-display:swap}
:root{color-scheme:dark;--bg:#0e0e11;--panel:#15151a;--line:#26262e;--ink:#ece8e0;--muted:#9b938a;--accent:#d97757}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 Inter,system-ui,sans-serif}a{color:var(--accent);text-underline-offset:4px}a:hover{color:var(--ink)}a:focus-visible{outline:2px solid var(--accent);outline-offset:5px}
header{border-bottom:1px solid var(--line);padding:18px max(24px,calc((100vw - 1080px)/2));display:flex;align-items:center;gap:32px;flex-wrap:wrap}.brand{display:flex;align-items:center;gap:10px;color:var(--ink);font-weight:600;text-decoration:none}nav{display:flex;flex-wrap:wrap;gap:20px}nav a{font-size:14px}nav a[aria-current=page]{color:var(--ink)}
main{max-width:880px;margin:auto;padding:64px 24px 80px;min-height:60vh}h1{font-size:clamp(32px,6vw,56px);line-height:1.15;letter-spacing:-.035em;margin:12px 0 24px;font-weight:600}h2{font-size:24px;margin-top:40px}p,li{max-width:74ch}.lede{font-size:21px;line-height:1.6}.stamp,code{font-family:'JetBrains Mono',monospace;font-size:12px}.stamp{color:var(--muted);overflow-wrap:anywhere}.download{display:inline-block;background:var(--accent);color:#180f08;padding:12px 20px;border-radius:8px;font-weight:600;text-decoration:none;margin:16px 0}.download:hover{background:var(--ink);color:#180f08}.release{border-top:1px solid var(--line);margin-top:40px;padding-top:8px}footer{background:var(--panel);border-top:1px solid var(--line);padding:28px max(24px,calc((100vw - 1080px)/2))}footer nav{gap:12px 24px}code{overflow-wrap:anywhere}ol,ul{padding-left:24px}li{margin:10px 0}.skip{position:absolute;left:24px;top:-80px}.skip:focus{top:4px;background:var(--bg)}@media(max-width:600px){header{gap:14px}header nav{gap:14px}main{padding-top:36px}}
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
    download = f'<a class="download" href="{esc(installer_url, quote=True)}">Download for Windows</a><p class="stamp">Installer build {esc(build_id)}<br>SHA-256: {sha256.lower()}</p>'
    docs = documentation_sections("getting-started", ("Install", "First open"))
    docs += "\n\n## First session\n\nOpen Home and choose a starter, then choose Start. Start places the wired nodes on the canvas. It does not run them.\n\n## The Canvas\n\n"
    docs += documentation_sections("composer-canvas", ("Connect nodes", "Properties"))
    docs += "\n\n## Run and Approve\n\nCheck the source connection and parameters before Run. Read each node's result. A missing host, account, or engine is a blocker, not a completed result. Outside changes still need the existing Approve flow.\n\nPress Run in the Canvas toolbar. If an Approve card appears, review the action before approving it."
    pages = {
        "index.html": ("ArchHub", '<h1>Nodes. Wires.<br>Your work, in a file.</h1><p class="lede">ArchHub is a visual node app: blocks wired on a canvas, saved as <code>.archhub</code> files. It works with any agent installed on the PC. Nothing runs until you press Run, unless you set an explicit trigger.</p>' + download + '<p>' + link("docs") + '</p><section class="release"><h2>What’s new</h2>' + markdown("### " + top_title + "\n\n" + top_notes) + '<a href="/changelog/">Full changelog</a></section>'),
        "docs/getting-started/index.html": ("Getting started", '<h1>Getting started</h1>' + download + markdown(docs.replace("{build}", build_id))),
        "community/index.html": ("Community", '<h1>Work in the open.</h1><p>Report a problem in ' + link("issues") + '; ask and share in ' + link("discuss") + '. Include your build id, what you tried and what happened. Do not post credentials or private project files.</p><p>This page does not host a community network or a shared workflow catalogue.</p>'),
        "changelog/index.html": ("Changelog", '<h1>Changelog</h1>' + "".join(markdown("## " + title + "\n\n" + body) for title, body in entries)),
        "404.html": ("Not found", '<h1>Page not found</h1><p><a href="/">Return to ArchHub</a></p>'),
    }
    output = Path(output)
    for path, (title, body) in pages.items():
        navigation = "".join(f'<a href="{route}"' + (' aria-current="page"' if path == target else '') + f'>{label}</a>' for route, target, label in (("/", "index.html", "Home"), ("/docs/getting-started/", "docs/getting-started/index.html", "Docs"), ("/community/", "community/index.html", "Community"), ("/changelog/", "changelog/index.html", "Changelog")))
        document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(title) + ' | ArchHub</title><style>' + CSS + '</style></head><body><a class="skip" href="#main">Skip to content</a><header><a class="brand" href="/">' + LOGO + 'ArchHub</a><nav aria-label="Site">' + navigation + '</nav></header><main id="main"><p class="stamp">Build ' + esc(build_id) + '</p>' + body + '</main><footer><nav aria-label="All ArchHub links">' + footer + '</nav><p class="stamp">Build ' + esc(build_id) + '</p></footer></body></html>'
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
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
