"""Courts for handing ArchHub to a colleague: a clean machine is not the founder's.

Identity is an account, never a machine. Before these courts every graph that
opened the accounts route recorded the founder's two addresses as its
founders; the shipped cockpit map carried his address; setup installed the
cloud's server packages from the internet; and Revit was offered on machines
with no way to connect it.
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import colleague_setup  # noqa: E402
from nodelang.cell_accounts import (  # noqa: E402
    FOUNDER_EMAIL_ROOT, FOUNDERS_ROOT, ensure_accounts, founder_email,
    founder_emails, is_founder, read_accounts, upsert_account,
)
from nodelang.cloud_session import signed_in_founder_account  # noqa: E402
from nodelang.universal_cell import CellStore  # noqa: E402

FOUNDER = "ahmed.fargaly98@gmail.com"


def _session(tmp_path, **held):
    record = tmp_path / "cloud.json"
    record.write_text(json.dumps({"token": "placeholder", **held}), encoding="utf-8")
    return record


def test_a_colleague_graph_records_no_founder():
    store = CellStore()
    ensure_accounts(store, founder_email=None)
    upsert_account(store, "colleague@firm.example")
    snapshot = store.snapshot()
    assert FOUNDER_EMAIL_ROOT not in snapshot.cells
    assert FOUNDERS_ROOT not in snapshot.cells
    assert founder_email(snapshot) is None and founder_emails(snapshot) == ()
    assert not is_founder(snapshot, FOUNDER)
    assert read_accounts(snapshot) == [{"email": "colleague@firm.example", "tier": "free"}]


def test_the_founder_graph_still_records_the_founders():
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)
    snapshot = store.snapshot()
    assert founder_email(snapshot) == FOUNDER
    assert is_founder(snapshot, FOUNDER)
    assert upsert_account(store, FOUNDER)[2] == "founder"


def test_the_founder_tier_comes_from_the_cloud_account_only(tmp_path):
    from nodelang import cloud_session
    asked = []

    def cloud(me_email, founder_code, me_code=200):
        def fetch(url, bearer):
            asked.append(url)
            if url.endswith("/v1/me"):
                return me_code, ({"email": me_email} if me_code == 200 else None)
            return founder_code, None
        return fetch

    cloud_session._founder_verdicts.clear()
    assert signed_in_founder_account(tmp_path / "absent.json", fetch=cloud(FOUNDER, 200)) is None
    assert asked == [], "no session, no question"
    # A colleague's session: the cloud refuses the founder route.
    assert signed_in_founder_account(
        _session(tmp_path, email="colleague@firm.example"),
        fetch=cloud("colleague@firm.example", 403)) is None
    # A hand-edited cloud.json naming the founder, with a "founder" flag and a
    # base URL of the editor's choosing: only the pinned cloud is asked, and
    # it answers for the TOKEN's account, not the file's email.
    forged = _session(tmp_path, email=FOUNDER, founder=True, cloud_base_url="http://127.0.0.1:9/evil")
    cloud_session._founder_verdicts.clear()
    asked.clear()
    assert signed_in_founder_account(forged, fetch=cloud("colleague@firm.example", 403)) is None
    assert asked == ["https://api.archhub.io/v1/me", "https://api.archhub.io/founder/api/system"], asked
    # A token the cloud rejects, or an unreachable cloud, grants nothing.
    cloud_session._founder_verdicts.clear()
    assert signed_in_founder_account(forged, fetch=cloud(None, 200, me_code=401)) is None
    cloud_session._founder_verdicts.clear()
    assert signed_in_founder_account(forged, fetch=cloud(None, None, me_code=None)) is None
    # The founder: the email returned is the cloud's (/v1/me), whatever the file says.
    cloud_session._founder_verdicts.clear()
    other = _session(tmp_path, email="typed-in@firm.example")
    assert signed_in_founder_account(other, fetch=cloud(FOUNDER, 200)) == FOUNDER
    source = Path(cloud_session.__file__).read_text(encoding="utf-8")
    assert "FOUNDER_EMAILS" not in source and 'get("founder")' not in source


def test_an_old_graph_holding_the_founder_never_makes_a_forged_sign_in_founder():
    """Reproduction: a graph that already records the founder (an old or copied
    graph) plus a forged cloud.json. The sign-in must answer free, not founder."""
    from nodelang.cloud_session import login_standing
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)           # the old graph's founder record
    _root, mail, stored = upsert_account(store, FOUNDER)
    assert stored == "founder" and is_founder(store.snapshot(), FOUNDER)
    # Forged session: the cloud's verdict is "no founder" (None).
    assert login_standing(mail, stored, None) == ("free", False)
    # The cloud naming a different founder does not lift this account either.
    assert login_standing(mail, stored, "someone-else@firm.example") == ("free", False)
    # Only the cloud's verdict for THIS account grants it.
    assert login_standing(mail, stored, FOUNDER) == ("founder", True)
    assert login_standing("colleague@firm.example", "pro", None) == ("pro", False)
    route = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    login = route.index("elif self.path == '/api/universal/login':")
    body = route[login:route.index("elif self.path == '/api/universal/accounts':", login)]
    assert "login_standing(" in body and "is_founder(" not in body


def test_an_old_graph_and_a_forged_email_never_change_the_offer_as_the_founder(tmp_path):
    """Reproduction of the relay path: the cockpit's offer command (launcher
    _cockpit_offer_command, reached by cloud_relay app-execute tasks) on a graph
    that already records the founder, with cloud.json hand-edited to name him."""
    from nodelang import cloud_session
    from nodelang.cell_accounts import apply_offer_command, declare_offer, read_offer
    from nodelang.universal_cell import InvalidCell
    import pytest as _pytest
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)            # the old graph's founder record
    declare_offer(store, founder_account=FOUNDER)
    before = read_offer(store.snapshot())
    forged = _session(tmp_path, email=FOUNDER, founder=True)  # the colleague's own token

    def colleague_cloud(url, bearer):                         # the cloud knows the token's owner
        if url.endswith("/v1/me"):
            return 200, {"email": "colleague@firm.example"}
        return 403, None

    cloud_session._founder_verdicts.clear()
    account = cloud_session.signed_in_founder_account(forged, fetch=colleague_cloud)
    assert account is None
    with _pytest.raises(InvalidCell, match="only a founder account"):
        apply_offer_command(store, 'set offer public-label to "Pwned"',
                            founder_account=account, execute=True)
    assert read_offer(store.snapshot()) == before
    # The launcher takes the founder from the cloud, never from cloud.json.
    launcher = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
    offer = launcher[launcher.index("def _cockpit_offer_command"):]
    offer = offer[:offer.index("\ncloud_relay = None")]
    assert "founder_account=signed_in_founder_account()" in offer
    assert "signed_in_cloud_account" not in offer
    # No founder_account anywhere in the shipped code comes from the file.
    for path in [ROOT / "launch_archhub_test.py", *(ROOT / "nodelang").rglob("*.py")]:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "founder_account=signed_in_cloud_account" not in text, path


def test_no_route_names_a_fixed_founder_account():
    source = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    assert FOUNDER not in source and "ahmedfargale@gmail.com" not in source
    accounts = source.index("elif self.path == '/api/universal/accounts':")
    assert source.index("owner._require_founder_machine()", accounts) < source.index(
        "ensure_accounts(", accounts), "a refused request must write nothing"


def test_the_shipped_cockpit_map_carries_no_founder_data():
    shipped = (ROOT / "nodelang" / "studio" / "map-data.js").read_bytes()
    for marker in (FOUNDER.encode(), b"ahmedfargale@gmail.com", b"owner_email", b"require_founder"):
        assert marker not in shipped


def _requirement_names(path):
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(re.split(r"[\[<>=;! ]", line, maxsplit=1)[0].lower())
    return names


# Import name of each package the cloud needs and the desktop must not use.
CLOUD_ONLY_IMPORTS = {"fastapi": "fastapi", "psycopg": "psycopg", "boto3": "boto3",
                      "opencv-python-headless": "cv2", "uvicorn": "uvicorn"}


def test_the_desktop_imports_no_server_package():
    """What the desktop boot IMPORTS, measured in a fresh interpreter.

    uvicorn and starlette are installed on the desktop as dependencies of mcp,
    so a requirements list cannot prove they are unused; the import can.
    """
    cloud = set(_requirement_names(ROOT / "requirements-cloud.txt"))
    assert set(CLOUD_ONLY_IMPORTS) <= cloud
    watched = sorted(set(CLOUD_ONLY_IMPORTS.values()) | {"starlette", "botocore"})
    probe = (
        "import sys\n"
        "for name in %r:\n"
        "    __import__(name)\n"
        "print(sorted({m.split('.')[0] for m in sys.modules} & set(%r)))\n"
    ) % (("nodelang.application_server", "nodelang.universal_application",
          "nodelang.universal_pipeline", "nodelang.pipeline_engines",
          "nodelang.baboom_attach", "nodelang.baboom_native_runtime",
          "nodelang.cell_accounts", "nodelang.host_brokers"), watched)
    answer = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), capture_output=True,
                            text=True, timeout=300)
    assert answer.returncode == 0, answer.stderr[-2000:]
    assert answer.stdout.strip().splitlines()[-1] == "[]", answer.stdout
    # And setup neither lists nor probes them; the installer ships no cloud list.
    assert not [pip for pip, probe_name in colleague_setup.PACKAGES
                if probe_name.split(".")[0] in watched]
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    shipped = [line for line in iss.splitlines() if line.startswith("Source:")]
    assert not [line for line in shipped if "requirements-cloud" in line]


def test_setup_installs_from_the_bundled_wheelhouse_without_internet(tmp_path, monkeypatch):
    (tmp_path / "wheelhouse").mkdir()
    (tmp_path / "wheelhouse" / "example-1-py3-none-any.whl").write_bytes(b"")
    pinned = tmp_path / "requirements.txt"
    pinned.write_text("example==1\n", encoding="ascii")
    calls = []
    monkeypatch.setattr(colleague_setup.subprocess, "run",
                        lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    assert colleague_setup.install_requirements(tmp_path, pinned).returncode == 0
    assert len(calls) == 1
    assert "--no-index" in calls[0] and str(tmp_path / "wheelhouse") in calls[0]


def test_setup_reaches_the_index_only_when_the_wheelhouse_cannot_serve(tmp_path, monkeypatch):
    pinned = tmp_path / "requirements.txt"
    pinned.write_text("example==1\n", encoding="ascii")
    calls = []
    monkeypatch.setattr(colleague_setup.subprocess, "run",
                        lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    colleague_setup.install_requirements(tmp_path, pinned)
    assert len(calls) == 1 and "--no-index" not in calls[0]


ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")


def _sweep_harness(tmp_path):
    """Compile a setup that runs ONLY SweepLegacyV1 on /root= and installs nothing."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "sweep_court.iss"
    script.write_text(
        "[Setup]\nAppName=ArchHubSweepCourt\nAppVersion=1\nCreateAppDir=no\n"
        "Uninstallable=no\nPrivilegesRequired=lowest\nOutputDir=%s\n"
        "OutputBaseFilename=sweep-court\n\n[Code]\n#include \"%s\"\n\n"
        "function InitializeSetup(): Boolean;\nbegin\n"
        "  SweepLegacyV1(ExpandConstant('{param:root}'));\n  Result := False;\nend;\n"
        % (tmp_path, ROOT / "installer" / "legacy_sweep.iss"), encoding="utf-8")
    built = subprocess.run([str(ISCC), "/Q", str(script)], capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    return tmp_path / "sweep-court.exe"


def _v1_install(root, *, marker=True):
    shipped = {"app/main.py", "app/bridge.py", "app/connectors/registry.py",
               "app/web_ui/index.html", "installer/install_gui.ps1",
               "payload/sources/max_mcp/max_mcp_startup.py"}
    kept = {"app/.env", "app/cloud.json", "app/events.jsonl", "app/token.txt",
            "app/store.sqlite3-shm", "app/state.db-wal", "app/__init__.py",
            "app/secrets_store.py", "app/credential_lock.py", "app/assets/archhub.ico",
            "app/connectors/my_notes.txt", "payload/revit/2024/RevitMCP.dll",
            "secrets.dat", "node-native-wip.json.gz.universal.sqlite3"}
    for rel in shipped | kept:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(rel, encoding="utf-8")
    if marker:
        (root / "VERSION").write_text("1.7.0\n", encoding="ascii")
    return shipped, kept


def _run_sweep(exe, root, tmp_path):
    log = tmp_path / ("sweep-%s.log" % root.parent.name)
    subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/LOG=%s" % log, "/root=%s" % root],
                   timeout=120)
    return log.read_text(encoding="utf-8", errors="replace")


def _registry_says_v1():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion"
                            r"\Uninstall\{B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE}_is1") as key:
            return str(winreg.QueryValueEx(key, "DisplayVersion")[0]).strip().startswith("1.")
    except OSError:
        return False


@pytest.mark.skipif(sys.platform != "win32" or not ISCC.is_file(), reason="needs Inno Setup 6 on Windows")
def test_the_legacy_sweep_deletes_only_what_v1_shipped(tmp_path):
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert "SweepLegacyV1(ExpandConstant('{app}'));" in iss
    assert 'Source: "{#WheelhousePath}\\*.whl"; DestDir: "{app}\\wheelhouse"' in iss
    exe = _sweep_harness(tmp_path / "build")

    # An upgraded v1 install: exactly the v1-shipped files go; everything else stays.
    root = tmp_path / "upgrade" / "ArchHub"
    shipped, kept = _v1_install(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.py").write_text("not v1", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "app" / "web_ui_link"), str(outside)],
                   check=True, capture_output=True)
    text = _run_sweep(exe, root, tmp_path)
    assert "Legacy sweep removed" in text, text[-2000:]
    assert not [rel for rel in shipped if (root / rel).exists()]
    assert not [rel for rel in kept if not (root / rel).exists()]
    assert (outside / "main.py").exists()
    assert not (root / "app" / "web_ui").exists(), "an emptied v1 directory is removed"
    assert (root / "app" / "connectors" / "my_notes.txt").exists()

    # A source checkout (holds .git) is never swept.
    checkout = tmp_path / "checkout" / "ArchHub"
    shipped, _kept = _v1_install(checkout)
    (checkout / ".git").mkdir()
    assert "source checkout" in _run_sweep(exe, checkout, tmp_path)
    assert all((checkout / rel).exists() for rel in shipped)

    # No v1 install marker: refused, even with app\main.py present.
    if not _registry_says_v1():
        bare = tmp_path / "bare" / "ArchHub"
        shipped, _kept = _v1_install(bare, marker=False)
        assert "no v1 install marker" in _run_sweep(exe, bare, tmp_path)
        assert all((bare / rel).exists() for rel in shipped)

    # An install folder that is itself a junction is refused.
    real = tmp_path / "real-v1"
    shipped, _kept = _v1_install(real)
    linked = tmp_path / "linked" / "ArchHub"
    linked.parent.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(real)], check=True, capture_output=True)
    # Refused either by the sweep's own link check or, earlier, by Setup's
    # RedirectionGuard, which will not follow a user-created junction.
    assert "Legacy sweep removed" not in _run_sweep(exe, linked, tmp_path)
    assert all((real / rel).exists() for rel in shipped)

    # The person's graph folder is never a sweep root.
    graph = tmp_path / "graph" / "ArchHub-Test"
    shipped, _kept = _v1_install(graph)
    assert "unexpected install root" in _run_sweep(exe, graph, tmp_path)
    assert all((graph / rel).exists() for rel in shipped)


def test_the_build_bundles_a_binary_wheelhouse():
    build = (ROOT / "installer" / "build_release.ps1").read_text(encoding="utf-8")
    assert "--only-binary=:all:" in build and '"/DWheelhousePath=$wheelhouse"' in build


def test_revit_and_max_say_plainly_why_they_cannot_connect(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    adapter = importlib.import_module("nodelang.clean_revit_adapter")
    brokers = importlib.import_module("nodelang.host_brokers")
    assert adapter.revit_addin_years() == []
    try:
        adapter._session_for(None, [])
    except adapter.RevitUnreachable as refusal:
        assert str(refusal) == adapter.REVIT_ADDIN_ABSENT
    monkeypatch.setattr(brokers, "_installed", lambda paths: True)
    monkeypatch.setattr(brokers, "_running", lambda names: False)
    monkeypatch.setattr(brokers, "_port_open", lambda port, timeout=0.15: False)
    revit = [row for row in brokers.probe_catalogue_rows() if row["id"].startswith("revit-")]
    assert revit and all(row["state"] == "unavailable" and row["detail"] == adapter.REVIT_ADDIN_ABSENT
                         for row in revit)
    assert brokers.open_host("max")["error"] == brokers.MAX_PLUGIN_ABSENT
    # A machine that registered the add-in (a v1 install) keeps Revit.
    addins = tmp_path / "appdata" / "Autodesk" / "Revit" / "Addins" / "2024"
    addins.mkdir(parents=True)
    (addins / "RevitMCP.addin").write_text(
        "<RevitAddIns><AddIn><FullClassName>RevitMCP.RevitMCPApp</FullClassName></AddIn></RevitAddIns>",
        encoding="utf-8")
    assert adapter.revit_addin_years() == ["2024"]
    row = next(r for r in brokers.probe_catalogue_rows() if r["id"] == "revit-2024")
    assert row["state"] != "unavailable"
