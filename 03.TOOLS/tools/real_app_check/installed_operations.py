"""Verify installed flow, Hosts, PDF and solver engines in a disposable Windows profile."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def flows(root, fixtures):
    from nodelang.enforce import guard_effect
    from nodelang.session_files import SessionFiles

    files = SessionFiles()
    for name in ("nodered-change", "nodered-function"):
        source = root / (name + ".json")
        shutil.copyfile(fixtures / source.name, source)
        opened = files.dispatch({"action": "open", "path": str(source)})
        doc = opened["document"]
        assert not any(n.get("result") for n in doc["nodes"]), "unexpected result on Open"
        destination = root / (name + ".archhub")
        files.dispatch({"action": "save", "path": str(destination), "document": doc})
        reopened = files.dispatch({"action": "open", "path": str(destination)})["document"]
        assert reopened["nodes"] == doc["nodes"] and reopened["wires"] == doc["wires"]
        ran = files.dispatch({"action": "run", "document": reopened}, invoke=guard_effect)
        if name == "nodered-change":
            debug, = [n for n in doc["nodes"] if n["type"] == "watch.preview"]
            assert ran["succeeded"] and ran["results"][debug["id"]]["output"]["out"] == "Hello World!"
        else:
            foreign, = [n for n in doc["nodes"] if n["type"] == "import.foreign"]
            result = ran["results"][foreign["id"]]
            assert not ran["succeeded"] and result["status"] == "Error" and "untrusted" in result["error"]
    return "Open, save, reopen, Run: Hello World!; foreign function refused"


def hosts():
    from colleague_setup import _setup_host_installations
    from nodelang import clean_revit_adapter, host_brokers, pipeline_engines
    from nodelang.connector_operation_evidence import EVIDENCE, host_projection

    snapshot = host_projection()
    rows = {r["op"]: r for r in snapshot["operations"]}
    assert len(rows) == len(snapshot["operations"]), "duplicate operation rows"
    registered = set(pipeline_engines.PIPELINE_ENGINES)
    assert rows.keys() == registered and EVIDENCE.keys() == registered, {
        "missing_evidence": sorted(registered - EVIDENCE.keys()), "stale_evidence": sorted(EVIDENCE.keys() - registered)}
    assert {r["op"] for r in snapshot["operations"] if r["evidence"] == "court"} == {
        op for op, evidence in EVIDENCE.items() if "court" in evidence}
    assert rows["pdf.extract_text"]["evidence"] == "court" and rows["pdf.snip"]["evidence"] == "unavailable"
    connectors = {r["id"]: r for r in snapshot["connectors"]}
    processes = host_brokers._windows_process_names()
    installed = _setup_host_installations()
    sessions = clean_revit_adapter.live_sessions()
    for host, exe, check, drive in (("autocad", "acad.exe", pipeline_engines.is_autocad_session, "cad.host_lines"),
                                    ("revit", "revit.exe", pipeline_engines.is_revit_session, "revit.build_walls")):
        expected = "connected" if any(map(check, sessions)) else "running" if exe in processes else "installed" if installed.get(host) else "absent"
        assert connectors[host]["state"] == expected and connectors[host]["drive"] == drive, (host, expected, connectors[host]["state"])
    return {"operations": len(rows), "autocad": connectors["autocad"]["state"], "revit": connectors["revit"]["state"]}


def pdf(root):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    from nodelang.pipeline_engines import PIPELINE_ENGINES

    path = root / "door.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=150)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 16 Tf 20 110 Td (Level 3 door D-312) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    for _ in range(2):
        result, _ = PIPELINE_ENGINES["pdf.extract_text"]({"path": str(path), "pages": [1]}, {})
        assert [(r["page"], r["text"]) for r in result["out"]] == [(1, "Level 3 door D-312")]
    return "Level 3 door D-312 on page 1, twice"


def whatsapp_fixture(root):
    """Read two isolated cloud-owner rows through the packaged desktop reader and Social node."""
    from functools import partial
    from unittest.mock import patch
    from nodelang import cloud_social_oauth as oauth
    from nodelang.nograph_server import JsonFile
    from nodelang.social_surface import SocialSurface

    cloud = Path(__file__).resolve().parents[3] / "06.CLOUD/cloud_backend"
    database = root / "guest-whatsapp.sqlite"
    assert not database.exists() and not (cloud / ".env").exists()
    sys.path.insert(0, str(cloud))
    try:
        with patch.dict(os.environ, {"DATABASE_URL": str(database)}):
            import config, db
            assert Path(db.__file__).resolve() == cloud / "db.py" and Path(config.DATABASE_URL) == database
            db.init_schema()
            owner = db.get_or_create_user("reader@example.invalid")["id"]
            other = db.get_or_create_user("neighbor@example.invalid")["id"]
            ticket = db.issue_token(owner)
            rows = [{"user_id": tenant, "phone_number_id": number, "wamid": "qa-" + number,
                     "direction": "in", "contact": number, "contact_name": "QA Contact", "kind": "text",
                     "text": text, "sent_at": 1} for tenant, number, text in (
                         (owner, "10001", "Review sheet A-101"), (other, "20002", "Neighbor only"))]
            assert db.store_whatsapp_messages(rows) == 2 and db.store_whatsapp_messages(rows) == 0

            def fixture_transport(method, url, *, bearer, body):
                assert method == "POST" and url == oauth.DEFAULT_BASE + "/oauth/whatsapp/messages"
                user = db.user_for_token(bearer)
                assert user and user["id"] == owner
                saved = db.list_whatsapp_messages(user_id=user["id"], **body)
                return 200, {"messages": saved, "next": saved[-1]["id"] if saved else body["since"]}

            # The ticket authenticates only to this temporary SQLite owner. Desktop admission is untouched.
            read = partial(oauth.whatsapp_messages, path=root / "fixture-account", http=fixture_transport)
            social_file = root / "social-fixture.json"
            node = SocialSurface(store=JsonFile(social_file, {"state": {}}))
            with patch.object(oauth, "read_cloud_session", return_value={"token": ticket}), \
                    patch.object(oauth, "whatsapp_messages", read):
                assert [m["wamid"] for m in read("QA Contact")["messages"]] == ["qa-10001"]
                assert node.dispatch("read_whatsapp_inbox", [])["result"]["added"] == 1
                reopened = SocialSurface(store=JsonFile(social_file, {"state": {}}))
                assert reopened.dispatch("read_whatsapp_inbox", [])["result"]["added"] == 0
                inbox = reopened.get_social_snapshot()["inbox"]
                assert [(m["id"], m["text"]) for m in inbox] == [("wa:qa-10001", "Review sheet A-101")]
    finally:
        sys.path.remove(str(cloud))
    return "Stored fixture reached the installed reader and reopened Inbox once; neighbor excluded. Offline fixture transport."


def solver():
    import highspy
    from nodelang.pipeline_engines import PIPELINE_ENGINES

    row = {"name": "A", "value": 7, "weight": 1}
    best, _ = PIPELINE_ENGINES["decide.optimize"](
        {"objective": "value", "sense": "Maximize", "max_each": 2, "whole_amounts": True,
         "constraints": [{"field": "weight", "op": "<=", "value": 2}]}, {"in": [row]})
    assert best["status"] == "Optimal" and best["objective"] == 14
    schedule, _ = PIPELINE_ENGINES["decide.schedule"](
        {"crews": 1}, {"in": [{"name": "A", "duration": 2}, {"name": "B", "duration": 3, "after": "A"}]})
    assert schedule["status"] == "Optimal" and schedule["finish"] == 5
    return {"highs": highspy.Highs().version(), "objective": 14, "finish": 5}


if __name__ == "__main__":
    install = Path(sys.executable).resolve().parents[2]
    build = (install / "BUILD_ID").read_text().strip()
    assert sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize
    assert build == os.environ["PUBLISHED_BUILD"] and Path(sys.prefix).resolve() == install / ".venv"
    fixtures = Path(sys.argv[1]).resolve(strict=True)
    sys.path.insert(0, str(install))
    failed = []
    print("BUILD", build)
    with tempfile.TemporaryDirectory(prefix="archhub-installed-operations-") as temp:
        root = Path(temp)
        for key in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "ARCHHUB_TEST_STATE_DIR", "TEMP", "TMP"):
            folder = root / key
            folder.mkdir()
            os.environ[key] = str(folder)
        os.environ["ARCHHUB_TEST_NO_OPEN"] = "1"
        for name, verify in (("flow", lambda: flows(root, fixtures)), ("hosts", hosts),
                             ("pdf", lambda: pdf(root)), ("solver", solver), ("whatsapp", lambda: whatsapp_fixture(root))):
            try:
                print("PASS", name, json.dumps(verify()))
            except Exception as error:
                failed.append(name)
                print("FAIL", name, type(error).__name__, str(error))
        for name, module in list(sys.modules.items()):
            if name.split(".")[0] in {"nodelang", "app", "colleague_setup", "pypdf", "pypdfium2", "pypdfium2_raw", "highspy"} and getattr(module, "__file__", None):
                assert Path(module.__file__).resolve().is_relative_to(install), name
        for name in ("nodelang.flow_import", "nodelang.connector_operation_evidence", "pypdf", "pypdfium2", "highspy"):
            if name in sys.modules:
                print("MODULE", name, sys.modules[name].__file__)
    print("SIGNED-IN CANVAS TOOLS: NOT EXERCISED. See the actual-window admission result for this installation.")
    sys.exit(bool(failed))
