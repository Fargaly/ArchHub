"""First-open data courts against a reopened, lazily restored HTTP owner.

Only transport producers are faked. Groups, messages, Skills files, signed
browser reads, SQLite restore and screen responses use their real paths.
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlencode

from nodelang import agent_composer, cloud_signin, commit_intent, pipeline_engines
from nodelang import universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.lazy_application_registry import DeferredRegistryField
from nodelang.universal_pipeline import create_engine_node
from tests_replica.test_clean_server_visual_projection import _json


def _register(directory):
    rows = ["| No | title | rev | state | date | file | SHA-256 |",
            "|---|---|---|---|---|---|---|"]
    for number, path in enumerate(sorted(directory.rglob("*")), 1):
        if path.is_file() and path.name != "REGISTER.md":
            relative = path.relative_to(directory).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(f"| {number} | {path.name} | 1 | WIP | 2026-10-15 | {relative} | {digest} |")
    (directory / "REGISTER.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_cold_screens_receive_group_skills_hosts_and_saved_graph_messages(monkeypatch):
    # Keep the runner's browser installation while isolating application data.
    browser_cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ms-playwright")
    with tempfile.TemporaryDirectory(prefix="archhub-lazy-cold-views-") as temporary:
        directory = Path(temporary)
        for state in ("01.WIP", "02.SHARED", "03.PUBLISHED", "04.ARCHIVE"):
            (directory / state).mkdir()
        (directory / "README.md").write_text(
            "Purpose: disposable lazy first-open court. Owner: LAZYBOOT-MAIN.\n"
            "Tier: T1 INTERNAL; synthetic data only. Scope: fake HTTP application.\n"
            "All data stays in WIP; regenerate disk register; remove fixture on exit.\n",
            encoding="utf-8",
        )
        _register(directory)
        work = directory / "01.WIP"
        monkeypatch.setenv("APPDATA", str(work / "appdata"))
        monkeypatch.setenv("LOCALAPPDATA", str(work / "localappdata"))
        monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(
            Path(app.__file__).parent / "data" / "public_runtime_map.json"))
        fake_home = work / "home"
        skill = fake_home / ".codex" / "skills" / "cold-first-open" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: cold-first-open\ndescription: Saved cold Skills catalogue entry\n---\n", encoding="utf-8")
        expanduser = os.path.expanduser
        monkeypatch.setattr(os.path, "expanduser", lambda path: str(fake_home) if path == "~" else expanduser(path))
        monkeypatch.setattr(pipeline_engines, "brain_recall", lambda *_args, **_kwargs: ({"out": ""}, ""))
        monkeypatch.setattr(ApplicationServer, "_probe_brain", staticmethod(lambda: {"ok": True, "facts": 0}))
        # Reproduce the PM's 27 raw connectors / six admitted Hosts rows.
        # All surfaces must apply the same catalogue rule, rather than count
        # only live endpoints or expose the unimplemented connector entries.
        fake_hosts = [
            {"id": f"court-host-{index}", "name": f"Cold fixture host {index}", "state": state,
             "detail": "Synthetic host; no host app launched", "drive": "court.read", "operations": []}
            for index, state in enumerate(("connected", "listening", "installed", "off", "connected", "installed"))
        ] + [
            {"id": f"court-unwired-{index}", "name": f"Cold unwired fixture {index}",
             "state": ("absent", "needs-key", "connected")[index % 3],
             "detail": ("Executable not found", "Provider key required", "Endpoint answers")[index % 3],
             "drive": "", "operations": []}
            for index in range(21)
        ]
        monkeypatch.setattr(ApplicationServer, "_probe_hosts", staticmethod(lambda: fake_hosts))
        monkeypatch.setattr(cloud_signin, "sign_in_state", lambda *_args, **_kwargs: {
            "state": "signed_out", "signed_in": False, "email": "", "expires_at": None, "founder": False})
        # Accepted release model-discovery producers are outside this replica.
        monkeypatch.setattr(ApplicationServer, "_local_runtime_states", lambda _self: {1234: False, 11434: False})
        monkeypatch.setattr(ApplicationServer, "_assistant_cli_path", lambda _self, _name: None)
        monkeypatch.setattr(ApplicationServer, "_opencode_cli_status", lambda _self, _path: {
            "installed": False, "signed_in": False, "route_ok": False})
        calls = []

        def provider(prompt, *_args, **_kwargs):
            calls.append(prompt)
            return json.dumps({"actions": [], "answer": "Saved graph answer after cold reopen"})

        monkeypatch.setattr(agent_composer, "_chat", provider)
        keys = MemorySigningKeyProvider("archhub.local.relationship-authority", b"cold-view-court-key" + b"0" * 13)
        keys.add_key("archhub.local.court-attestation", b"cold-view-attestation" + b"0" * 11)

        def start():
            instance = ApplicationServer(
                universal_state_path=work / "application.sqlite3", universal_key_provider=keys,
                universal_workspace_root=work, enable_machine_transport=False,
                enable_universal_cloud_gateway=False, enable_brain_cloud_sync=False,
                enable_machine_projection_prewarm=False, live_watch=False,
            )
            # The fixture owns the SQLite lifetime. Drain browser requests before
            # server.close closes that file; no daemon request may outlive it.
            instance.httpd.daemon_threads = False
            instance.httpd.block_on_close = True
            return instance.start()

        server = start()
        try:
            store, registry = server.universal_store, server.universal_registry
            with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="save cold group fixture"):
                members = [create_engine_node(store, registry, title=title, engine="library.think")["root"]
                           for title in ("Cold member A", "Cold member B")]
                app.set_universal_selection(store, registry, members)
                group, _ = app.group_universal_selection(store, registry, title="Cold saved group")
                app.set_universal_selection(store, registry, [])
            scope = registry.canvas_root
            message = "Saved graph question with empty selection before cold reopen"
            status, answer = _json(server.url, "/api/universal/agent", {
                "prompt": message, "model": "court/free", "graph": True,
                "graph_id": scope, "request_id": "cold-reopen-graph-send",
            }, token=server.browser_session_token, csrf=server.browser_csrf_token)
            assert status == 200, answer
            assert answer["delivery"]["state"] == "replied", answer
            assert calls == [message]
        finally:
            server.close()
        _register(directory)

        report = {"group": {"root": group, "members": members}}
        # Each screen gets an independent owner and cold registry. Opening
        # Workspace cannot accidentally hydrate the Skills or transcript court.
        screens = ["workspace", "created-group", "skills", "hosts", "graph"]
        desktop_patterns = {
            "desktop-skills": "^desktop HTML: cold rail Skills",
            "desktop-hosts": "^desktop HTML: Home, status, Hosts and About",
            "desktop-group": "^desktop HTML: group created after lazy boot",
        }
        browser_patterns = {
            "browser-skills": "^desktop browser: cold rail Skills",
            "browser-hosts": "^desktop browser: Home, status, Hosts and About",
            "browser-group": "^desktop browser: group created after lazy boot",
        }
        if os.environ.get("LAZYBOOT_RUN_DESKTOP_COURT") == "1":
            screens.extend(browser_patterns)
            screens.extend(desktop_patterns)
        for screen in screens:
            server = start()
            try:
                registry = server.universal_registry
                token, csrf = server.browser_session_token, server.browser_csrf_token

                def get(path):
                    status, value = _json(server.url, path, token=token)
                    assert status == 200, value
                    assert value.get("ok") is not False, value
                    return value

                home = get("/api/universal/canvas?screen=home")
                graphs = get("/api/universal/graphs?screen=home")
                for owner, name in ((registry.map, "nodes"), (registry, "workshop_category_roots")):
                    field = object.__getattribute__(owner, name)
                    assert isinstance(field, DeferredRegistryField) and field.group._values is None
                assert home["canvas_deferred"] and home["nodes"] == []
                report.update(home=home, graphs=graphs)
                if screen == "workspace":
                    workspace = get("/api/universal/canvas")
                    card = next(node for node in workspace["nodes"] if node["id"] == group)
                    assert {member["id"] for member in card["members"]} == set(members)
                    assert card["member_count"] == len(members)
                    assert {member["title"] for member in card["members"]} == {"Cold member A", "Cold member B"}
                    report["workspace"] = workspace
                elif screen == "created-group":
                    # A post-boot composition is absent from every restored
                    # index. Exercise the actual group interaction's first
                    # topology response, before any follow-up canvas read.
                    store = server.universal_store
                    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="create members after lazy boot"):
                        created_members = [create_engine_node(store, registry, title=title, engine="library.think")["root"]
                                           for title in ("New cold member A", "New cold member B")]
                    before = get("/api/universal/canvas")
                    status, selected = _json(server.url, "/api/universal/gesture", {
                        "roots": created_members, "focus": created_members[-1],
                    }, token=token, csrf=csrf)
                    assert status == 200, selected
                    binding = next(row for row in selected["interaction_projection"]["bindings"]
                                   if row["control"] == "app:control:canvas:group")
                    status, grouped = _json(server.url, "/api/universal/interaction", {
                        "interaction": binding["interaction"], "control": binding["control"],
                        "event": binding["event"], "revision": selected["interaction_projection"]["revision"],
                        "projection_mode": "topology-delta-v1",
                    }, token=token, csrf=csrf)
                    assert status == 200, grouped
                    created_group = grouped["created_root"]
                    assert grouped["projection_mode"] == "topology-delta-v1"
                    card = next(node for node in grouped["topology_patch"]["upsert_nodes"]
                                if node["id"] == created_group)
                    assert card["composition"]
                    assert {member["id"] for member in card["members"]} == set(created_members)
                    assert {member["title"] for member in card["members"]} == {"New cold member A", "New cold member B"}
                    assert card["member_count"] == len(created_members)
                    remove_binding = next(row for row in grouped["interaction_projection"]["bindings"]
                                          if row["control"] == "app:control:canvas:remove-member")
                    # Existing Studio's chip drag uses its signed remove-member
                    # interaction and refreshes after the committed receipt.
                    status, removal = _json(server.url, "/api/universal/interaction", {
                        "interaction": remove_binding["interaction"], "control": remove_binding["control"],
                        "event": remove_binding["event"], "revision": grouped["revision"],
                        "projection_mode": "receipt-v1", "command_id": str(uuid.uuid4()),
                        "expected_scope": grouped["scope"]["current"],
                        "membership": {"member": created_members[0], "from_group": created_group, "to_group": ""},
                    }, token=token, csrf=csrf)
                    assert status == 200, removal
                    assert removal["committed_revision"] > grouped["revision"]
                    moved = get("/api/universal/canvas")
                    moved_card = next(node for node in moved["nodes"] if node["id"] == created_group)
                    assert [member["id"] for member in moved_card["members"]] == created_members[1:]
                    reloaded = get("/api/universal/canvas")
                    reloaded_card = next(node for node in reloaded["nodes"] if node["id"] == created_group)
                    assert [member["id"] for member in reloaded_card["members"]] == created_members[1:]
                    assert created_members[0] in {node["id"] for node in reloaded["nodes"]}
                    report["created_group"] = {"before": before, "selected": selected, "response": grouped,
                                               "members": created_members, "root": created_group, "moved": moved}
                elif screen == "skills":
                    # It must finish while another thread holds the lock,
                    # exactly as an unrelated cold canvas hydration does.
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        with server.mutation_lock:
                            request = executor.submit(_json, server.url, "/api/universal/skills",
                                                      {"want": "catalogue"}, token=token, csrf=csrf)
                            status, skills = request.result(timeout=5)
                    assert status == 200 and skills["ok"], skills
                    assert any(row["name"] == "cold-first-open" for row in skills["result"])
                    report["skills"] = skills
                elif screen == "hosts":
                    hosts = get("/api/universal/hosts")
                    deadline = time.monotonic() + 2
                    while hosts.get("probing") and time.monotonic() < deadline:
                        time.sleep(0.01)
                        hosts = get("/api/universal/hosts")
                    assert not hosts.get("probing"), hosts
                    assert [row["id"] for row in hosts["connectors"]] == [row["id"] for row in fake_hosts]
                    assert len(hosts["connectors"]) == 27
                    assert len([row for row in hosts["connectors"] if row["drive"]]) == 6
                    report["hosts"] = hosts
                elif screen == "graph":
                    transcript_path = "/api/universal/workshop-transcript?" + urlencode({"node": "graph:" + scope, "scope": scope})
                    page = get(transcript_path)
                    assert [(row["kind"], row["text"]) for row in page["rows"]] == [
                        ("message", message), ("reply", "Saved graph answer after cold reopen")]
                    assert calls == [message], "reopen must not replay the provider"
                    report["graph"] = {"root": scope, "message": message, "page": page}
                else:
                    # Each exact desktop test gets its own cold owner and
                    # registry. Settings cannot warm the group-card court,
                    # and no prior screen can hydrate the Skills rail read.
                    desktop_report = work / "desktop-cold-report.json"
                    desktop_report.write_text(json.dumps(report) + "\n", encoding="utf-8")
                    environment = dict(os.environ, LAZYBOOT_HTTP_URL=server.url,
                                       LAZYBOOT_HTTP_TOKEN=token, LAZYBOOT_HTTP_CSRF=csrf,
                                       PLAYWRIGHT_BROWSERS_PATH=browser_cache,
                                       LAZYBOOT_COLD_REPORT=str(desktop_report))
                    pattern = (browser_patterns if screen.startswith("browser-") else desktop_patterns)[screen]
                    script = ("02.TESTS/tests_js/studio_lazy_desktop_browser.test.cjs" if screen.startswith("browser-")
                              else "02.TESTS/tests_js/studio_lazy_cold_views.test.cjs")
                    desktop = subprocess.run([
                        "node", "--test", "--test-concurrency=1", "--test-force-exit",
                        "--test-name-pattern=" + pattern, script,
                    ], cwd=Path(__file__).resolve().parents[2], env=environment,
                        capture_output=True, text=True, encoding="utf-8", timeout=180)
                    print(desktop.stdout.encode("ascii", "backslashreplace").decode("ascii"))
                    assert desktop.returncode == 0, desktop.stdout + desktop.stderr
            finally:
                server.close()
            _register(directory)
        destination = os.environ.get("LAZYBOOT_COLD_REPORT")
        if destination:
            Path(destination).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert not directory.exists(), "every synthetic fixture must be deleted"
