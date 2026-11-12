"""Isolated static export check; no application imports, browser or live profile."""
import re
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

    def handle_starttag(self, tag, attrs):
        self.targets.extend(value for key, value in attrs if key in ("href", "src"))


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
                    for row in rows:
                        self.assertIn(row["url"], parser.targets)
                    for target in parser.targets:
                        self.assertTrue(target in allowed or target.startswith(("/", "#")))
                        self.assertFalse(target.startswith("//"))
                        if target.startswith("/"):
                            local = output / target.lstrip("/")
                            self.assertTrue(local.is_file() or (local / "index.html").is_file(), target)
                    self.assertTrue(set(re.findall(r'https?://[^\s<>"\x27)]+', text)) <= allowed)
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
