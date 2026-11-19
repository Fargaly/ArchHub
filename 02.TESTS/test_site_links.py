"""Isolated static export check; no application imports, browser or live profile."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03.TOOLS/packaging/website"))
from build_site import LATEST_INSTALLER, build_site, slug, soon_chip
from links import load_links, readme_table

DATA = ROOT / "03.TOOLS/packaging/website/data"
# Served by Caddy, not files: BABOOM's chat and sign-in proxy, the release record and BABOOM's own site.
SERVED = ("/signin", "/api/", "/download.json", "/baboom")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.images = []
        self.visible = []
        self.suppressed = 0
        self.metadata = {}

    def handle_starttag(self, tag, attrs):
        self.targets.extend(value for key, value in attrs if key in ("href", "src"))
        attributes = dict(attrs)
        if tag == "img":
            self.images.append(attributes)
        if tag in ("script", "style"):
            self.suppressed += 1
        if tag == "meta":
            self.metadata[attributes.get("property", attributes.get("name"))] = attributes.get("content")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.suppressed -= 1

    def handle_data(self, text):
        if not self.suppressed:
            self.visible.append(text)


class StaticSiteTest(unittest.TestCase):
    def test_design_pages_data_pages_and_honest_states(self):
        rows = load_links()
        build = "test-build-123"
        installer = next(row["url"] for row in rows if row["kind"] == "repo") + "/releases/download/" + build + "/setup.exe"
        # The catalogue is exported from the app at build time, in its own process (this test never imports it).
        catalogue_path = ROOT / ".cache/site/catalogue.json"
        try:
            subprocess.run([sys.executable, str(ROOT / "03.TOOLS/packaging/website/export_catalogue.py")], check=True)
        except subprocess.CalledProcessError:
            # Release machines are Windows; Linux agents may lack msvcrt. A fixture catalogue still courts the site.
            if not catalogue_path.is_file():
                raise
        catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="sitelinks-test-") as temporary:
            output = Path(temporary) / "site"
            build_site(output, build, installer, "a" * 64)
            pages = {path.relative_to(output).as_posix() for path in output.rglob("*.html")}
            for required in ("index.html", "download/index.html", "docs/index.html", "docs/getting-started/index.html",
                             "features/index.html", "security/index.html", "signin/index.html", "community/index.html",
                             "changelog/index.html", "account/index.html", "docs/nodes/index.html", "search/index.html", "404.html"):
                self.assertIn(required, pages)
            for absent in ("signup", "contact", "cloud", "pricing", "community/people"):
                self.assertFalse(any(page.startswith(absent + "/") for page in pages), absent)
            self.assertEqual(len([p for p in pages if p.startswith("docs/nodes/") and p != "docs/nodes/index.html"]), len(catalogue["nodes"]))
            for starter in catalogue["starters"]:
                self.assertIn(f"community/{slug(starter['id'])}/index.html", pages)
            site = next(row["url"] for row in rows if row["kind"] == "site")
            for name in pages:
                page = output / name
                with self.subTest(page=name):
                    text = page.read_text(encoding="utf-8")
                    parser = Links()
                    parser.feed(text)
                    self.assertEqual(parser.metadata["archhub-build"], build)
                    self.assertEqual(parser.metadata["og:image"], site + "/og.png")
                    self.assertIn("/favicon.svg", parser.targets)
                    self.assertNotIn('href="#/', text)
                    self.assertNotRegex(text, r"(?i)fargool|ahmed|api\.archhub\.io/founder|founder of archhub")
                    # The label for an unbuilt part appears only as the one chip.
                    self.assertEqual(len(re.findall(r"(?i)coming\s+soon", text)), text.count(soon_chip()))
                    self.assertNotRegex(text.lower(), r"not\s+live\s+yet")
                    for image in parser.images:
                        source = image["src"]
                        if source.startswith("/"):
                            self.assertTrue((output / source.lstrip("/")).is_file(), source)
                        self.assertTrue(image.get("alt") is not None, source)
                    for target in parser.targets:
                        self.assertFalse(target.startswith("//"))
                        if target.startswith("/") and not target.startswith(SERVED):
                            local = output / target.split("#")[0].split("?")[0].lstrip("/")
                            self.assertTrue(local.is_file() or (local / "index.html").is_file(), target)
            for name in ("download/index.html",):
                self.assertIn(f'href="{LATEST_INSTALLER}"', (output / name).read_text(encoding="utf-8"))
            self.assertIn(f'data-rel="tag">{build}<', (output / "download/index.html").read_text(encoding="utf-8"))
            home = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("fetch('/download.json')", home)
            self.assertIn('data-rel="tag"', home)
            changelog = (output / "changelog/index.html").read_text(encoding="utf-8")
            self.assertIn('id="changelog-live"', changelog)
            self.assertIn("api.github.com/repos/Fargaly/ArchHub/releases", changelog)
            # Baked headings are dates (build identity stays on the release); the newest
            # published installer must appear before older narrative entries.
            self.assertIn("2026-11-19 · 09:04", changelog)
            self.assertLess(changelog.index("2026-11-19 · 09:04"), changelog.index("2026-11-13 · 00:22"))
            self.assertFalse((output / "download.json").exists())
            account = (output / "account/index.html").read_text(encoding="utf-8")
            self.assertEqual(re.findall(r'class="accs" id="([a-z-]+)"', account), ["acc-me", "acc-plan", "acc-comm", "acc-social", "acc-brain"])
            search = json.loads((output / "search.json").read_text(encoding="utf-8"))
            self.assertEqual(len(search), len(catalogue["nodes"]) + len(catalogue["starters"]))
            self.assertIn(readme_table(), (ROOT / "README.md").read_text(encoding="utf-8"))
            for name in ("favicon.svg", "favicon.ico", "og.png", "assets/fonts/inter-variable.woff2"):
                self.assertGreater((output / name).stat().st_size, 0)
            for identity, address, digest in (("bad/id", installer, "a" * 64),
                                               (build, installer.replace("https:", "http:"), "a" * 64),
                                               (build, installer.replace(build, "other-build"), "a" * 64),
                                               (build, installer, "invalid")):
                with self.subTest(identity=identity, digest=digest):
                    with self.assertRaises(ValueError):
                        build_site(output, identity, address, digest)
        self.assertFalse(any(name.startswith("nodelang") for name in sys.modules))


if __name__ == "__main__":
    unittest.main()
