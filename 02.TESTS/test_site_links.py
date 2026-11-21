"""Isolated static export check; no application imports, browser or live profile."""
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03.TOOLS/packaging/website"))
from build_site import LATEST_INSTALLER, build_site, prepare_deploy_context, slug, soon_chip
from links import load_links, readme_table
import sync_changelog

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
    def test_changelog_sync_keeps_published_builds_and_local_history(self):
        current = "20261120-143339-44754205914-1-7c364326cfec80539087ac8153d5616322a78955"
        legacy = "20261119-1847-9d8e490"
        local_only = ["20261118-0950-a1b2c3d", "20261117-123456-12345-2-" + "a" * 40]

        def release(identity, **overrides):
            return {"tag_name": "build-" + identity, "draft": False, "prerelease": False,
                    "published_at": "2026-11-20T15:22:40Z",
                    "body": "## What changed\n- Reviewed release note\n", **overrides}

        first = [
            release(current), release("20261120-1500-1111111", draft=True),
            release("20261120-1501-2222222", prerelease=True),
            {**release("20261120-1502-3333333"), "published_at": None},
        ]
        first.extend(release("unrelated-tag") for _ in range(96))
        second = [release(current), release(legacy)]
        calls = []

        def response(request, timeout):
            self.assertNotIn("Authorization", dict(request.header_items()))
            page = int(request.full_url.rsplit("=", 1)[1])
            calls.append(page)
            return BytesIO(json.dumps(first if page == 1 else second).encode("utf-8"))

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "CHANGELOG.md"
            history = "\n".join(f"## {identity}\n\n- Kept manual entry {i}.\n"
                                for i, identity in enumerate(local_only))
            path.write_text("# Changelog\n\n## Next build\n\n" + history, encoding="utf-8")
            with patch.dict("os.environ", {"GH_TOKEN": ""}), patch.object(sync_changelog, "CHANGELOG", path), patch.object(
                    sync_changelog.urllib.request, "urlopen", side_effect=response):
                result = sync_changelog.sync()
                stamp = path.stat().st_mtime_ns
                self.assertEqual(sync_changelog.sync(), result)
                self.assertEqual(path.stat().st_mtime_ns, stamp)
            self.assertEqual(calls, [1, 2, 1, 2])
            self.assertEqual(re.findall(r"(?m)^## (.+)$", result), ["Next build", current, legacy, *local_only])
            self.assertTrue(result.endswith(history))
            self.assertEqual(path.read_text(encoding="utf-8"), result)


    def test_release_fetch_authentication_stays_on_the_initial_request(self):
        from urllib.request import HTTPRedirectHandler

        requests = []

        def response(request, timeout):
            redirected = HTTPRedirectHandler().redirect_request(
                request, None, 302, "Found", {}, "https://redirect.example/releases")
            requests.append((request.get_header("Authorization"), redirected.get_header("Authorization")))
            self.assertEqual(request.host, "api.github.com")
            return BytesIO(b"[]")

        with patch.object(sync_changelog.urllib.request, "urlopen", side_effect=response):
            with patch.dict("os.environ", {"GH_TOKEN": "placeholder-env"}):
                self.assertEqual(sync_changelog.fetch_releases(), [])
                self.assertEqual(sync_changelog.fetch_releases("placeholder-helper"), [])
                self.assertEqual(sync_changelog.fetch_releases(""), [])
            with patch.dict(os.environ):
                os.environ.pop("GH_TOKEN", None)
                self.assertEqual(sync_changelog.fetch_releases(), [])
        self.assertEqual(requests, [
            ("Bearer placeholder-env", None), ("Bearer placeholder-helper", None),
            (None, None), (None, None),
        ])

    def test_deploy_context_rejects_public_identity_matches(self):
        def render_identity(site, *release):
            site.mkdir(parents=True)
            (site / "index.html").write_text("<p>Founder of ArchHub</p>", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temporary:
            context = Path(temporary) / "deploy"
            with patch("build_site.build_site", side_effect=render_identity):
                with self.assertRaisesRegex(ValueError, "Public identity scan did not pass"):
                    prepare_deploy_context(context, "test", "https://example.org/test/setup.exe", "a" * 64)
            self.assertFalse((context / "Dockerfile").exists())

    def test_stable_download_keeps_the_checksum_bound_to_the_installer(self):
        from build_site import UI_SCRIPT, design, from_design, release_facts

        markup = release_facts(from_design(design()["pages"]["/download"]))
        script = r"""
const {JSDOM}=require('jsdom'), assert=require('node:assert/strict');
const {markup,loader,latest}=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const name='ArchHub-Setup-0.exe', id='20261120-official', sha='b'.repeat(64);
const pinned=latest.replace('/latest/download/', '/download/build-'+id+'/');
const offer={build_id:id,asset_sha256:sha,asset_bytes:64,asset_name:name};
const release={draft:false,prerelease:false,tag_name:'build-'+id,assets:[
 {name,size:64,digest:'sha256:'+sha,browser_download_url:pinned}]};
async function check(first,second,verified,expectedCalls){
 const dom=new JSDOM(markup,{url:'https://archhub.io/download/',runScripts:'outside-only'});
 const w=dom.window, field=k=>w.document.querySelector('[data-rel="'+k+'"]'),calls=[];
 try{
  assert.equal(field('url').href,latest);
  assert.equal(field('sha').textContent,'Checksum unavailable');
  w.fetch=async url=>{
   if(url==='https://api.github.com/repos/Fargaly/ArchHub')return {ok:false};
   calls.push(url);const value=url==='/download.json'?first:second;
   if(value instanceof Error)throw value;
   return {ok:value!==null,json:async()=>{if(value==='invalid JSON')throw SyntaxError();return value;}};
  };
  w.eval(loader);await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,['/download.json','https://api.github.com/repos/Fargaly/ArchHub/releases/latest'].slice(0,expectedCalls));
  assert.equal(field('url').href,verified?pinned:latest);
  assert.equal(field('sha').textContent,verified?sha:'Checksum unavailable');
  assert.equal(field('tag').textContent,verified?id:'Latest stable release');
 }finally{w.close();}
}
(async()=>{
 await check(offer,null,true,1);
 for(const bad of [new TypeError('CORS'),null,'invalid JSON',{...offer,asset_sha256:'bad'}])
  await check(bad,release,true,2);
 await check(null,{...release,assets:[{...release.assets[0],digest:null}],body:'BUILD_ID: '+id+'\nSHA256 ArchHub-Setup-0.exe: '+sha+' (64 bytes)'},true,2);
 for(const bad of [null,new TypeError('unavailable'),{...release,assets:[]},
  {...release,body:'SHA256 ArchHub-Setup-0.exe: '+'c'.repeat(64)},
  {...release,assets:[{...release.assets[0],browser_download_url:latest}]}])
  await check(null,bad,false,2);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        subprocess.run(["node", "-e", script], cwd=ROOT, check=True, timeout=20,
                       input=json.dumps({"markup": markup, "latest": LATEST_INSTALLER,
                                         "loader": UI_SCRIPT.removeprefix("<script>").removesuffix("</script>")}),
                       text=True, encoding="utf-8")

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
            context = Path(temporary) / "deploy"
            prepare_deploy_context(context, build, installer, "a" * 64)
            output = context / "site"
            config = tomllib.loads((context / "fly.toml").read_text(encoding="utf-8"))
            service = config["http_service"]
            self.assertEqual(config["app"], "archhub-web")
            self.assertEqual(service["internal_port"], 3000)
            self.assertTrue(service["force_https"])
            self.assertEqual([(check["method"], check["path"]) for check in service["checks"]], [("GET", "/")])
            self.assertEqual(config["build"], {"dockerfile": "Dockerfile", "ignorefile": ".dockerignore"})
            self.assertEqual((context / ".dockerignore").read_text(encoding="utf-8").splitlines(),
                             ["*", "!Dockerfile", "!Caddyfile", "!site/", "!site/**"])
            docker = (context / "Dockerfile").read_text(encoding="utf-8").splitlines()
            self.assertRegex(docker[0], r"^FROM caddy:2\.8\.4-alpine@sha256:[a-f0-9]{64}$")
            self.assertEqual(docker[1:], ["COPY Caddyfile /etc/caddy/Caddyfile", "COPY site/ /srv/"])
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
            self.assertIn('data-rel="tag">Latest stable release<', (output / "download/index.html").read_text(encoding="utf-8"))
            home = (output / "index.html").read_text(encoding="utf-8")
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
