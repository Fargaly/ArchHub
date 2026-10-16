"""Execute the real Core routes and shim pump with API doubles, never a live host."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from urllib import error as urlerror, request as urlrequest

import pytest

from nodelang import clean_revit_adapter as adapter, host_bridge_auth as auth

ROOT = Path(__file__).resolve().parents[1]
UNC = r"\\fixture-server\models\A project\model.rvt"
_FIXTURE_CALL = adapter._call


@pytest.fixture(scope="module")
def fixture_exe(tmp_path_factory):
    output = tmp_path_factory.mktemp("revit-open-build")
    dotnet = Path(shutil.which("dotnet"))
    installed = subprocess.run([str(dotnet), "--list-sdks"], capture_output=True, text=True, check=True)
    version, sdk_root = installed.stdout.splitlines()[-1].split(" [", 1)
    csc = Path(sdk_root.rstrip("]")) / version / "Roslyn/bincore/csc.dll"
    packs = dotnet.parent / "packs/Microsoft.NETCore.App.Ref"
    reference_packs = sorted(packs.glob("10.*"))
    assert reference_packs
    references = sorted((reference_packs[-1] / "ref/net10.0").glob("*.dll"))
    assert csc.is_file() and references
    core = Path(os.environ.get("REVITOPEN_BASE_SOURCE", ROOT / "bridges/sources/revit_mcp_core/RevitMCPCore.cs"))
    assembly = output / "RevitOpenFixture.dll"
    command = [str(dotnet), str(csc), "/nologo", "/noconfig", "/nostdlib+", "/target:exe",
               "/langversion:latest", "/out:" + str(assembly)]
    command += ["/r:" + str(path) for path in references]
    command += [str(core), str(ROOT / "bridges/sources/revit_mcp/RevitEventHandler.cs"),
                str(ROOT / "bridges/sources/shared/BridgeAuth.cs"), str(ROOT / "bridges/sources/shared/ReviewedCore.cs")]
    command += [str(path) for path in (ROOT / "tests_replica/revit_open_fixture").glob("*.cs")]
    built = subprocess.run(command, capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    runtimes = subprocess.run([str(dotnet), "--list-runtimes"], capture_output=True, text=True, check=True)
    runtime = next(row.split()[1] for row in runtimes.stdout.splitlines()
                   if row.startswith("Microsoft.NETCore.App 10."))
    (output / "RevitOpenFixture.runtimeconfig.json").write_text(json.dumps({"runtimeOptions": {
        "tfm": "net10.0", "framework": {"name": "Microsoft.NETCore.App", "version": runtime}}}), encoding="utf-8")
    return [str(dotnet), str(assembly)]


def run(fixture_exe, route="/open", body=None, **state):
    result = subprocess.run(fixture_exe, input=json.dumps(
        {"route": route, "body": {"path": UNC, "activate": True} if body is None else body, **state}),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("path", [UNC, r"C:\fixture\a model.rvt", r"\\fixture-server\a b\العربية.rvt"])
@pytest.mark.parametrize("active", [False, True])
def test_open_preserves_path_and_runs_on_external_event_without_transaction(fixture_exe, path, active):
    result = run(fixture_exe, body={"path": path, "activate": True}, active=active)
    assert result["answer"] == {"status": "ok", "title": "Fixture", "path": path,
                                "active_view": "Default", "error": None}
    assert result["LastPath"] == path
    assert result["Opens"] == 1 and result["Starts"] == result["Calls"] == 0
    if path.startswith("\\\\"):
        assert result["LastPath"].startswith("\\\\") and not result["LastPath"].startswith("C:")


@pytest.mark.parametrize("body,method", [({}, "POST"), ({"path": " "}, "POST"),
    ({"path": UNC, "activate": False}, "POST"), ({"path": UNC, "activate": "true"}, "POST"),
    ({"path": 3}, "POST"), ({"path": UNC}, "GET")])
def test_bad_open_is_refused_before_any_api_call(fixture_exe, body, method):
    result = run(fixture_exe, body=body, method=method)
    assert result["answer"]["status"] == "error" and result["answer"]["error"]
    assert result["Opens"] == result["Starts"] == 0 and result["LastPath"] is None


@pytest.mark.parametrize("view,ok", [("Plan", True), ("Missing", False), ("Template", False),
                                     ("Duplicate", False), ("Invalid", False)])
def test_view_activation_reports_opened_document_even_if_view_refused(fixture_exe, view, ok):
    result = run(fixture_exe, body={"path": UNC, "view": view})
    answer = result["answer"]
    assert answer["status"] == ("ok" if ok else "error")
    assert answer["path"] == UNC and answer["title"] == "Fixture" and result["Opens"] == 1
    assert answer["active_view"] == ("Plan" if ok else "Default")
    assert (answer["error"] is None) == ok and result["Starts"] == 0


@pytest.mark.parametrize("state", [{"fail_open": True}, {"active": True, "modifiable": True}])
def test_open_failure_is_structured_and_does_not_write(fixture_exe, state):
    result = run(fixture_exe, **state)
    assert result["answer"]["status"] == "error" and result["answer"]["title"] is None
    assert result["answer"]["error"] and result["Opens"] == result["Starts"] == 0


@pytest.mark.parametrize("transaction,starts", [(False, 0), (True, 1)])
def test_exec_explicit_app_mode_keeps_model_transaction_default(fixture_exe, transaction, starts):
    result = run(fixture_exe, "/exec", {"code": "probe", "transaction": transaction}, active=True)
    assert result["answer"]["status"] == "ok" and result["Calls"] == 1
    assert result["Starts"] == result["Commits"] == starts
    assert result["answer"]["result"] == {"doc_null": False, "uidoc_null": False,
                                            "modifiable": bool(starts)}


@pytest.mark.parametrize("transaction", [True, False])
def test_exec_without_a_model_never_runs_user_code(fixture_exe, transaction):
    # Broker review R1: no-document exec would hand arbitrary C# the full UIApplication
    # (create/save documents). Opening a first model is the /open route's job.
    result = run(fixture_exe, "/exec", {"code": "probe", "transaction": transaction}, active=False)
    assert result["answer"]["status"] == "error" and "No active document" in result["answer"]["error"]
    assert result["Calls"] == result["Starts"] == result["Opens"] == 0


@pytest.mark.parametrize("active", [True])
def test_app_script_can_switch_documents(fixture_exe, active):
    result = run(fixture_exe, "/exec", {"code": "open", "transaction": False}, active=active)
    assert result["answer"]["status"] == "ok" and result["Opens"] == 1 and result["Starts"] == 0


@pytest.mark.parametrize("code", ["throw", "fail"])
def test_model_script_failure_rolls_back(fixture_exe, code):
    result = run(fixture_exe, "/exec", {"code": code}, active=True)
    assert result["answer"]["status"] == "error" and result["Rollbacks"] == 1 and result["Commits"] == 0


def test_transaction_start_failure_does_not_execute_script(fixture_exe):
    result = run(fixture_exe, "/exec", {"code": "probe"}, active=True, fail_start=True)
    assert result["answer"]["status"] == "error" and result["Calls"] == 0


def test_real_core_http_auth_admits_signed_open_and_refuses_unsigned_browser_and_replay(fixture_exe, monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([*fixture_exe, str(port)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "READY"
        url = "http://localhost:%d/open" % port
        body = json.dumps({"path": UNC, "activate": True}).encode()
        secret = "revit-open-fixture-only-not-a-credential"
        headers = auth.signed_headers("POST", url, body, secret=secret)

        def request(held_headers):
            req = urlrequest.Request(url, data=body, headers=held_headers)
            try:
                with urlrequest.urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except urlerror.HTTPError as error:
                return error.code, json.load(error)

        assert request({})[0] == 401
        assert request({**headers, "Origin": "http://fixture.invalid"})[0] == 403
        status, answer = request(headers)
        assert status == 200 and answer["status"] == "ok" and answer["path"] == UNC
        assert request(headers)[0] == 401
        monkeypatch.setattr(auth, "ensure_secret", lambda: secret)
        monkeypatch.setattr(adapter, "_call", _FIXTURE_CALL)
        monkeypatch.setattr(adapter, "broker_sessions", lambda _: [{"port": port, "document": None}])
        answer = adapter.broker_call("revit", "/open", {"path": UNC, "activate": True})
        assert answer["ok"] and answer["document"] == "Fixture" and answer["path"] == UNC
    finally:
        process.stdin.close()
        process.wait(timeout=10)
