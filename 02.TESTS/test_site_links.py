"""Isolated static export check; no application imports, browser or live profile."""
import re
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03.TOOLS/packaging/website"))
from build_site import build_site
from links import load_links, readme_table


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
    def test_release_pages_and_single_link_source(self):
        rows = load_links()
        build = "test-build-123"
        installer = next(row["url"] for row in rows if row["kind"] == "repo") + "/releases/download/" + build + "/setup.exe"
        allowed = {row["url"] for row in rows} | {installer}
        with tempfile.TemporaryDirectory(prefix="sitelinks-test-") as temporary:
            output = Path(temporary) / "site"
            build_site(output, build, installer, "a" * 64)
            self.assertEqual({path.relative_to(output).as_posix() for path in output.rglob("*.html")}, {
                "index.html", "docs/getting-started/index.html", "community/index.html",
                "changelog/index.html", "404.html",
            })
            for page in output.rglob("*.html"):
                with self.subTest(page=page.name):
                    text = page.read_text(encoding="utf-8")
                    self.assertIn(build, text)
                    self.assertNotIn("Cell graph", text)
                    parser = Links()
                    parser.feed(text)
                    visible = " ".join(parser.visible)
                    self.assertNotRegex(visible, r"\b[0-9a-f]{7,40}\b")
                    self.assertNotIn("Source:", visible)
                    self.assertNotRegex(text.lower(), r"coming\s+soon")
                    self.assertEqual(parser.metadata["archhub-build"], build)
                    self.assertEqual(parser.metadata["og:image"], next(row["url"] for row in rows if row["kind"] == "site") + "/og.png")
                    self.assertTrue(parser.metadata["og:title"])
                    self.assertIn('/favicon.svg', parser.targets)
                    self.assertIn('/favicon.ico', parser.targets)
                    for image in parser.images:
                        self.assertTrue((output / image["src"].lstrip("/")).is_file())
                        self.assertTrue(image["alt"])
                        self.assertEqual((image["width"], image["height"]), ("1600", "1000"))
                    for row in rows:
                        self.assertIn(row["url"], parser.targets)
                    for target in parser.targets:
                        self.assertTrue(target in allowed or target.startswith(("/", "#")))
                        self.assertFalse(target.startswith("//"))
                        if target.startswith("/"):
                            local = output / target.lstrip("/")
                            self.assertTrue(local.is_file() or (local / "index.html").is_file(), target)
                    addresses = set(re.findall(r'https?://[^\s<>"\x27)]+', text))
                    site = next(row["url"] for row in rows if row["kind"] == "site")
                    route = page.relative_to(output).as_posix().removesuffix("index.html")
                    self.assertEqual(parser.metadata["og:url"], site + "/" + route)
                    self.assertTrue(addresses <= allowed | {site + "/og.png", site + "/" + route})
            home = Links()
            home.feed((output / "index.html").read_text(encoding="utf-8"))
            self.assertEqual({image["src"] for image in home.images}, {
                "/assets/home.png", "/assets/canvas.png", "/assets/library.png", "/assets/session.png"})
            home_text = " ".join(home.visible)
            for phrase in ("Revit", "AutoCAD", "Excel", "Outlook", "Claude Code", "Codex", "OpenCode", "Gemini CLI", "Goose", "BABOOM", ".archhub", "Approve", "Windows Credential Manager"):
                self.assertIn(phrase, home_text)
            self.assertEqual(json.loads((output / "download.json").read_text(encoding="utf-8")), {
                "build_id": build, "installer_url": installer, "sha256": "a" * 64})
            docs = (output / "docs/getting-started/index.html").read_text(encoding="utf-8")
            self.assertIn("<h2>Install</h2>\n<ol>", docs)
            self.assertIn("<h2>First open</h2>\n<p>", docs)
            for asset in ("favicon.svg", "favicon.ico", "og.png"):
                self.assertGreater((output / asset).stat().st_size, 0)
            for licence in output.rglob("*.txt"):
                self.assertTrue(set(re.findall(r'https?://[^\s<>"\x27)]+' , licence.read_text(encoding="utf-8"))) <= allowed)
            self.assertIn(readme_table(), (ROOT / "README.md").read_text(encoding="utf-8"))
            for name in ("inter-variable.woff2", "jetbrains-mono-regular.woff2", "OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
                self.assertGreater((output / "assets/fonts" / name).stat().st_size, 0)
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
