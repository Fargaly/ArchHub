"""Export the site design (the one design link's site.html) for the public site generator.

Run at release time from the repository root:
    python 03.TOOLS/packaging/website/export_design.py <path to archhub-directions/site.html>
It writes 03.TOOLS/packaging/website/data/design.json (styles, header, footer and one block per page)
and copies the design's product shots to assets/. build_site.py renders every page from that file,
so the live site follows the design without hand-edited output.
"""
import ast
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "design.json"
SHOTS = ("home", "canvas", "library", "settings")


def sections(markup):
    """Each <section class="page" data-page="..."> block, keyed by its route, nested sections kept."""
    pages = {}
    for match in re.finditer(r'<section class="page" data-page="([^"]+)"', markup):
        start, depth, i = match.start(), 0, match.start()
        while True:
            opened = markup.find("<section", i + 1)
            closed = markup.find("</section>", i + 1)
            if opened != -1 and opened < closed:
                depth, i = depth + 1, opened
                continue
            if depth == 0:
                pages[match.group(1)] = markup[start:closed + len("</section>")]
                break
            depth, i = depth - 1, closed
    return pages


def docs(markup):
    """The design's docs articles (its DOCS table): slug, title, group, lede, paragraphs, where in the app."""
    start = markup.index("const DOCS=") + len("const DOCS=")
    table = ast.literal_eval(markup[start:markup.index("};", start) + 1])
    return [[slug, *row] for slug, row in table.items()]


def export(source):
    source = Path(source)
    markup = source.read_text(encoding="utf-8")
    css = markup[markup.index("<style>") + 7:markup.index("</style>")]
    header = markup[markup.index('<header class="top"'):markup.index("</header>") + len("</header>")]
    footer = markup[markup.index('<footer class="foot">'):markup.index("</footer>") + len("</footer>")]
    data = {"source": source.name, "sha256": hashlib.sha256(markup.encode("utf-8")).hexdigest(),
            "css": css, "header": header, "footer": footer, "pages": sections(markup), "docs": docs(markup)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name in SHOTS:
        shot = source.parent / "site-assets" / (name + ".png")
        if shot.is_file():
            shutil.copyfile(shot, HERE / "assets" / (name + ".png"))
    print(f"{OUT}: {len(data['pages'])} pages from {source.name} {data['sha256'][:12]}")


if __name__ == "__main__":
    export(sys.argv[1])
