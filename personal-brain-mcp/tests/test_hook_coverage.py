"""Brain-owned hook coverage audit/repair tests.

These tests pin the governance layer above the installer:

* the installer remains the migration wiring plan for vendor hook adapters;
* Brain reads/writes hook coverage through the Universal Cell control ledger;
* Brain can repair missing hooks by invoking the installer; and
* write-capable work assignment can be refused before a runtime claims work
  when its hook coverage is red.
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
WORKSPACE = Path(__file__).resolve().parents[4]
NODE_LANGUAGE = WORKSPACE / "10.PRODUCT" / "13.NODE-LANGUAGE"
if str(NODE_LANGUAGE) not in sys.path:
    sys.path.insert(0, str(NODE_LANGUAGE))

from nodelang.application_server import ApplicationServer  # noqa: E402
from personal_brain import active_work as aw  # noqa: E402
from personal_brain import compliance_report as cr  # noqa: E402
from personal_brain import hook_coverage as hc  # noqa: E402
from personal_brain import installer  # noqa: E402
from personal_brain.storage import BrainStore  # noqa: E402


@pytest.fixture(scope="module")
def cell_runtime():
    """One real Cell runtime for this module's integration-level courts."""
    server = ApplicationServer().start()
    try:
        yield server
    finally:
        server.close()


BRAIN_CONTROL_PLANE_MODULES = [
    "active_work.py",
    "client_hook.py",
    "court_harness.py",
    "installer.py",
    "mcp_core.py",
    "models.py",
    "reflexion.py",
    "secret_resolver.py",
    "server.py",
    "server_verify.py",
    "storage.py",
    "cell_room_wiring.py",
    "cockpit_drain.py",
    "compliance_report.py",
    "core_values_authority.py",
    "grand_map_sync.py",
    "hook_coverage.py",
    "meeting_room.py",
    "run_report.py",
    "runtime_holders.py",
    "universal_session_manager.py",
]


class _InProcessRuntimeBridge:
    def __init__(self, server):
        self._server = server

    def _request(self, method, path, body=None):
        return self._server.dispatch_universal_machine_route({
            "method": method,
            "path": path,
            "body": dict(body or {}),
        })

    def work_list(self):
        return self._request("GET", "/api/universal/work")

    def work_create(self, **body):
        return self._request("POST", "/api/universal/work", body)

    def assembly_create(self, **body):
        return self._request("POST", "/api/universal/assembly", body)

    def assembly_field_update(self, **body):
        return self._request("POST", "/api/universal/assembly-field", body)

    def deliberation_read(self, **body):
        return self._request("GET", "/api/universal/deliberation", body)

    def deliberation_append(self, **body):
        return self._request("POST", "/api/universal/deliberation", body)


class _FailingAssemblyBridge:
    def deliberation_append(self, **body):  # noqa: ARG002
        raise RuntimeError("cell create refused")


class _FailingOutcomeBridge:
    def __init__(self):
        self.calls = 0

    def deliberation_append(self, **body):  # noqa: ARG002
        self.calls += 1
        if self.calls == 1:
            return {
                "ok": True,
                "root": "deliberation-entry:repair-request",
                "payload_root": "payload:repair-request",
            }
        raise RuntimeError("outcome create refused")


class _FastAssemblyBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def assembly_create(self, **body):
        self.calls.append(dict(body))
        source = (body.get("fields") or {}).get("source") or len(self.calls)
        return {
            "ok": True,
            "created_root": f"assembly-instance:{source}",
            "assembly": {"interfaces": []},
        }


def _module_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        try:
            values[stmt.targets[0].id] = ast.literal_eval(stmt.value)
        except ValueError:
            continue
    return values


def test_brain_control_plane_modules_cannot_pose_as_cell_authority():
    root = _SRC / "personal_brain"

    for name in BRAIN_CONTROL_PLANE_MODULES:
        values = _module_assignments(root / name)
        assert values.get("LEGACY_MIGRATION_ONLY") is True, name
        assert values.get("ACTIVE_AUTHORITY") == "10.PRODUCT/13.NODE-LANGUAGE", name
        assert values.get("PROMOTION_ALLOWED") is False, name
        status = values.get("AUTHORITY_STATUS")
        assert (
            status == "control_plane_projection_until_universal_cell_policy"
            or (
                isinstance(status, str)
                and status.startswith("superseded_by_universal_cell")
            )
        ), name


def test_brain_control_plane_text_cannot_claim_unified_completion():
    root = _SRC / "personal_brain"
    source_truth = "source of " + "truth"
    forbidden = (
        "fully unified",
        "unified authority",
        "integrated authority",
        "integrated into the same graph",
        "same graph lens",
        "one graph lens",
        "cell-native product complete",
        "universal cell complete",
        "final authority",
        source_truth,
        "brain workshop room (node-native)",
    )

    violations: dict[str, list[str]] = {}
    for name in BRAIN_CONTROL_PLANE_MODULES:
        text = (root / name).read_text(encoding="utf-8").lower()
        found = [phrase for phrase in forbidden if phrase in text]
        if found:
            violations[name] = found

    assert violations == {}


def test_hook_coverage_is_control_plane_projection_not_product_authority():
    source = Path(hc.__file__).read_text(encoding="utf-8")
    test_source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "source of " + "truth"

    assert hc.LEGACY_MIGRATION_ONLY is True
    assert hc.MIGRATION_CONTROL_ONLY is True
    assert hc.AUTHORITY_STATUS == (
        "control_plane_projection_until_universal_cell_policy"
    )
    assert hc.ACTIVE_AUTHORITY == "10.PRODUCT/13.NODE-LANGUAGE"
    assert hc.PROMOTION_ALLOWED is False
    assert "migration wiring plan" in source
    assert "not product authority" in source
    assert forbidden not in source.lower()
    assert forbidden not in test_source.lower()


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    installer.ALL_PLANS["claude-code"].config_path = (
        tmp_path / ".claude" / "settings.json")
    installer.ALL_PLANS["cursor"].config_path = tmp_path / ".cursor" / "mcp.json"
    installer.ALL_PLANS["codex"].config_path = tmp_path / ".codex" / "config.toml"
    installer.ALL_PLANS["gemini-cli"].config_path = (
        tmp_path / ".gemini" / "settings.json")
    installer.ALL_PLANS["antigravity"].config_path = (
        tmp_path / ".gemini" / "config" / "hooks.json")
    yield tmp_path


@pytest.fixture()
def store():
    s = BrainStore.open(":memory:")
    yield s
    s.close()


def test_audit_persists_installed_hook_coverage_in_brain_meta(fake_home, store):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])

    report = hc.audit(store, only=["codex"], owner_user="founder")

    raw = store.get_meta(hc.COVERAGE_META_KEY)
    assert raw, "audit must persist the coverage ledger in brain_meta"
    persisted = json.loads(raw)
    assert persisted["owner_user"] == "founder"
    assert persisted["status"] == "green"

    codex = report.clients["codex"]
    assert codex.detected is True
    assert codex.installed is True
    assert codex.status == "green"
    assert codex.schema_valid is True
    assert codex.schema_evidence
    assert codex.config_hashes
    assert codex.touchpoints["scope_gate"].state == installer.ENFORCED
    assert codex.touchpoints["workshop_authority"].state == installer.ENFORCED
    assert codex.touchpoints["workshop_authority"].installed is True
    assert codex.touchpoints["post_tool_write"].state == installer.ENFORCED


@pytest.mark.parametrize(
    ("brain_table", "expected_issue"),
    [
        (
            'command = "personal-brain"\n'
            "args = []\n"
            "\n"
            "[mcp_servers.brain.env]\n"
            'BRAIN_OWNER_USER = "${USER}"',
            "mcp_servers.brain.url must be",
        ),
        (
            f'url = "{installer.CODEX_BRAIN_MCP_URL}"\n'
            'command = "personal-brain"\n'
            "args = []\n"
            "\n"
            "[mcp_servers.brain.env]\n"
            'BRAIN_OWNER_USER = "${USER}"',
            "mcp_servers.brain must not declare",
        ),
        (
            f'url = "{installer.CODEX_BRAIN_MCP_URL}"\n'
            "enabled = false",
            "mcp_servers.brain must not be disabled",
        ),
    ],
)
def test_hook_coverage_rejects_unsafe_codex_brain_mcp_config(
    fake_home,
    store,
    brain_table,
    expected_issue,
):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    path = installer._codex_path()
    path.write_text(
        path.read_text().replace(
            f'url = "{installer.CODEX_BRAIN_MCP_URL}"',
            brain_table,
        )
    )

    report = hc.audit(store, only=["codex"], owner_user="founder")

    codex = report.clients["codex"]
    assert codex.installed is False
    assert codex.status == "red"
    assert any(expected_issue in issue for issue in codex.issues)


def test_runtime_compliance_observer_is_read_only_and_covers_exact_court_checks(
    fake_home,
):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])

    observation = hc.observe_runtime_compliance("codex")

    assert observation["client"] == "codex"
    assert observation["status"] == "green"
    assert observation["checks"] == {
        "runtime-detected": True,
        "required-hooks": True,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": True,
        "workshop-authority": True,
    }
    assert observation["issue_count"] == 0


def test_runtime_compliance_observer_maps_codex_desktop_to_codex_wiring(
    fake_home,
):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])

    observation = hc.observe_runtime_compliance("codex-desktop")

    assert observation["client"] == "codex"
    assert observation["status"] == "green"
    assert all(observation["checks"].values())


def test_runtime_compliance_observer_fails_closed_for_missing_client_wiring(
    fake_home,
):
    observation = hc.observe_runtime_compliance("codex")

    assert observation["status"] == "red"
    assert observation["checks"]["required-hooks"] is False
    assert observation["checks"]["brain-connected"] is False


def test_audit_appends_compliance_history_event(fake_home, store):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])

    hc.audit(store, only=["codex"], owner_user="founder")

    history = cr.get_compliance_history(store, owner_user="founder", limit=5)
    assert history["total"] == 1
    event = history["events"][0]
    assert event["event_type"] == "hook_coverage_audit"
    assert event["status"] == "green"
    assert event["clients"]["codex"] == "green"


def test_hook_coverage_audit_cell_first_writes_only_the_cell_ledger(
    fake_home,
    store,
    cell_runtime,
):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    bridge = _InProcessRuntimeBridge(cell_runtime)
    result = hc.audit_cell_first(
        store,
        only=["codex"],
        owner_user="founder",
        cell_bridge=bridge,
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["report"]["status"] == "green"
    assert result["report"]["cell_record_root"]
    assert result["cell_record"]["root"] == result["report"][
        "cell_record_root"
    ]
    assert store.get_meta(hc.COVERAGE_META_KEY) is None
    persisted = hc.get_report_cell_first(
        store, owner_user="founder", cell_bridge=bridge
    )
    assert persisted is not None
    assert persisted.clients["codex"].status == "green"
    entries = bridge.deliberation_read(
        space=hc.CELL_CONTROL_LEDGER_ROOT,
        limit=10,
    )
    event = entries["entries"][-1]
    assert event["root"] == result["report"]["cell_record_root"]
    assert event["payload"]["event_type"] == "hook_coverage_audit"
    assert event["payload"]["clients"]["codex"]["status"] == "green"


def test_hook_coverage_audit_cell_first_fails_closed_before_brain_write(store):
    result = hc.audit_cell_first(
        store,
        only=["codex"],
        owner_user="founder",
        cell_bridge=_FailingAssemblyBridge(),
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert "cell create refused" in result["error"]
    assert store.get_meta(hc.COVERAGE_META_KEY) is None
    assert store.get_meta(cr.HISTORY_META_KEY) is None


def test_runtime_write_gate_rejects_legacy_only_green_coverage(
    fake_home,
    store,
):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    hc.audit(store, only=["codex"], owner_user="founder")

    gate = hc.runtime_write_gate(
        store,
        runtime="codex",
        owner_user="founder",
        write=True,
    )

    assert gate["allowed"] is False
    assert gate["action_tool"] == "brain.hook_coverage_audit_cell_first"
    assert "has not been audited" in gate["reason"]


def test_runtime_write_gate_accepts_cell_first_green_coverage(
    fake_home,
    store,
    cell_runtime,
):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    bridge = _InProcessRuntimeBridge(cell_runtime)
    result = hc.audit_cell_first(
        store,
        only=["codex"],
        owner_user="founder",
        cell_bridge=bridge,
    )
    assert result["ok"] is True

    gate = hc.runtime_write_gate(
        store,
        runtime="codex",
        owner_user="founder",
        write=True,
        cell_bridge=bridge,
    )

    assert gate["allowed"] is True
    assert gate["cell_record_root"] == result["report"]["cell_record_root"]


def test_audit_marks_detected_missing_codex_hooks_red(fake_home, store):
    (fake_home / ".codex").mkdir()

    report = hc.audit(store, only=["codex"], owner_user="founder")

    codex = report.clients["codex"]
    assert codex.detected is True
    assert codex.installed is False
    assert codex.status == "red"
    assert any("hooks.json" in issue for issue in codex.issues)


@pytest.mark.parametrize(
    ("client", "event_name", "vendor"),
    [
        ("claude-code", "PostToolUse", "claude"),
        ("codex", "PostToolUse", "codex"),
        ("gemini-cli", "AfterTool", "gemini"),
    ],
)
def test_audit_requires_signed_post_write_settlement(
    fake_home,
    store,
    client,
    event_name,
    vendor,
):
    installer.ALL_PLANS[client].config_path.parent.mkdir(parents=True, exist_ok=True)
    installer.install_all(only=[client])
    path = (
        installer._codex_hooks_path()
        if client == "codex"
        else installer.ALL_PLANS[client].config_path
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload["hooks"][event_name]
    payload["hooks"][event_name] = [
        group
        for group in groups
        if not any(
            "agent_scope_gate.py" in str(handler.get("command", ""))
            and f"--vendor {vendor}" in str(handler.get("command", ""))
            for handler in group.get("hooks", [])
            if isinstance(handler, dict)
        )
    ]
    assert len(payload["hooks"][event_name]) < len(groups)
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = hc.audit(store, only=[client], owner_user="founder")

    coverage = report.clients[client]
    assert coverage.status == "red"
    assert coverage.touchpoints["post_tool_write"].installed is False
    assert any("post_tool_write" in issue for issue in coverage.issues)


def test_audit_accepts_antigravity_named_hooks_and_mcp(fake_home, store):
    (fake_home / ".gemini" / "config").mkdir(parents=True)
    installer.install_all(only=["antigravity"])

    report = hc.audit(store, only=["antigravity"], owner_user="founder")

    antigravity = report.clients["antigravity"]
    assert antigravity.detected is True
    assert antigravity.installed is True
    assert antigravity.status == "green"
    assert antigravity.touchpoints["scope_gate"].installed is True
    assert antigravity.touchpoints["pre_prompt_inject"].installed is True
    assert antigravity.touchpoints["workshop_authority"].installed is True
    assert antigravity.touchpoints["drive_inject"].installed is True
    assert antigravity.touchpoints["stop_gate"].installed is True


def test_audit_marks_missing_antigravity_hooks_red(fake_home, store):
    (fake_home / ".gemini" / "config").mkdir(parents=True)
    installer._antigravity_mcp_path().write_text(
        json.dumps({"mcpServers": {"brain": {"command": "personal-brain"}}}),
        encoding="utf-8",
    )

    report = hc.audit(store, only=["antigravity"], owner_user="founder")

    antigravity = report.clients["antigravity"]
    assert antigravity.detected is True
    assert antigravity.installed is False
    assert antigravity.status == "red"
    assert any("hooks.json" in issue for issue in antigravity.issues)


def test_audit_marks_missing_workshop_authority_red(fake_home, store):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    hooks_path = installer._codex_hooks_path()
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    hooks["hooks"].pop("UserPromptSubmit")
    hooks_path.write_text(json.dumps(hooks), encoding="utf-8")

    report = hc.audit(store, only=["codex"], owner_user="founder")

    codex = report.clients["codex"]
    assert codex.status == "red"
    assert codex.touchpoints["workshop_authority"].installed is False
    assert any("workshop_authority" in issue for issue in codex.issues)


def test_audit_rejects_marker_complete_but_parser_invalid_claude_hooks(
    fake_home,
    store,
):
    path = fake_home / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "mcpServers": {"brain": {"command": "personal-brain"}},
        "hooks": {
            "PreToolUse": [{"type": "command", "command": "pretooluse_validate.py"}],
            "UserPromptSubmit": [
                {"type": "mcp_tool", "server": "brain", "tool": "brain.hook_context"},
                {"type": "mcp_tool", "server": "brain", "tool": "brain.work_assigned_block"},
            ],
            "PostToolUse": [
                {"type": "mcp_tool", "server": "brain", "tool": "brain.observe"},
            ],
            "Stop": [{"type": "command", "command": "anti_laziness_gate.py"}],
        },
    }))

    report = hc.audit(store, only=["claude-code"], owner_user="founder")

    claude = report.clients["claude-code"]
    assert claude.schema_valid is False
    assert claude.installed is False
    assert claude.status == "red"
    assert any(".hooks must be an array" in issue for issue in claude.issues)


def test_audit_rejects_disabled_gemini_hooks(fake_home, store):
    (fake_home / ".gemini").mkdir()
    installer.install_all(only=["gemini-cli"])
    path = installer._gemini_path()
    config = json.loads(path.read_text())
    config["hooksConfig"] = {"enabled": False}
    path.write_text(json.dumps(config))

    report = hc.audit(store, only=["gemini-cli"], owner_user="founder")

    gemini = report.clients["gemini-cli"]
    assert gemini.schema_valid is False
    assert gemini.status == "red"
    assert any("hooksConfig.enabled is false" in issue for issue in gemini.issues)


def test_audit_rejects_disabled_codex_hooks(fake_home, store):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    path = installer._codex_path()
    path.write_text(path.read_text() + "\n[features]\nhooks = false\n")

    report = hc.audit(store, only=["codex"], owner_user="founder")

    codex = report.clients["codex"]
    assert codex.schema_valid is False
    assert codex.status == "red"
    assert any("explicitly disabled" in issue for issue in codex.issues)


def test_repair_runs_installer_then_reaudits_to_green(fake_home, store):
    (fake_home / ".gemini").mkdir()

    result = hc.repair(
        store,
        only=["gemini-cli"],
        owner_user="founder",
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["after"]["status"] == "green"
    assert installer._gemini_path().exists()
    after = hc.get_report(store, owner_user="founder")
    assert after is not None
    assert after.clients["gemini-cli"].status == "green"


def test_repair_appends_compliance_history_event(fake_home, store):
    (fake_home / ".gemini").mkdir()

    hc.repair(store, only=["gemini-cli"], owner_user="founder", dry_run=False)

    history = cr.get_compliance_history(store, owner_user="founder", limit=5)
    event_types = [event["event_type"] for event in history["events"]]
    assert "hook_coverage_repair" in event_types
    repair_event = next(
        event for event in history["events"]
        if event["event_type"] == "hook_coverage_repair"
    )
    assert repair_event["after_status"] == "green"
    assert repair_event["clients"]["gemini-cli"] == "green"


def test_hook_coverage_repair_cell_first_records_request_and_outcome(
    fake_home,
    store,
    cell_runtime,
):
    (fake_home / ".gemini").mkdir()
    bridge = _InProcessRuntimeBridge(cell_runtime)
    result = hc.repair_cell_first(
        store,
        only=["gemini-cli"],
        owner_user="founder",
        dry_run=False,
        cell_bridge=bridge,
    )

    assert result["ok"] is True
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is True
    assert result["before"]["status"] == "red"
    assert result["after"]["status"] == "green"
    assert installer._gemini_path().exists()
    assert result["request_cell_record"]["root"] == result["after"][
        "repair_request_cell_record_root"
    ]
    assert result["outcome_cell_record"]["root"] == result["after"][
        "repair_outcome_cell_record_root"
    ]
    assert store.get_meta(hc.COVERAGE_META_KEY) is None
    persisted = hc.get_report_cell_first(
        store, owner_user="founder", cell_bridge=bridge
    )
    assert persisted is not None
    assert persisted.clients["gemini-cli"].status == "green"
    entries = bridge.deliberation_read(
        space=hc.CELL_CONTROL_LEDGER_ROOT,
        limit=10,
    )
    event = entries["entries"][-1]
    assert event["root"] == result["after"]["repair_outcome_cell_record_root"]
    assert event["payload"]["event_type"] == "hook_coverage_repair_outcome"
    assert event["payload"]["after"]["clients"]["gemini-cli"]["status"] == "green"


def test_hook_coverage_repair_cell_first_request_failure_prevents_file_write(
    fake_home,
    store,
):
    (fake_home / ".gemini").mkdir()

    result = hc.repair_cell_first(
        store,
        only=["gemini-cli"],
        owner_user="founder",
        dry_run=False,
        cell_bridge=_FailingAssemblyBridge(),
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is False
    assert "cell create refused" in result["error"]
    assert not installer._gemini_path().exists()
    assert store.get_meta(hc.COVERAGE_META_KEY) is None
    assert store.get_meta(cr.HISTORY_META_KEY) is None


def test_hook_coverage_repair_cell_first_outcome_failure_blocks_brain_receipt(
    fake_home,
    store,
):
    (fake_home / ".gemini").mkdir()
    bridge = _FailingOutcomeBridge()

    result = hc.repair_cell_first(
        store,
        only=["gemini-cli"],
        owner_user="founder",
        dry_run=False,
        cell_bridge=bridge,
    )

    assert result["ok"] is False
    assert result["cell_first"] is True
    assert result["brain_written"] is False
    assert result["side_effect_executed"] is True
    assert "outcome create refused" in result["error"]
    assert bridge.calls == 2
    assert installer._gemini_path().exists()
    assert result["after"]["status"] == "green"
    assert store.get_meta(hc.COVERAGE_META_KEY) is None
    assert store.get_meta(cr.HISTORY_META_KEY) is None


def test_server_registers_hook_coverage_tools(store):
    from personal_brain.server import build_server

    mcp = build_server(store=store, default_owner_user="founder")
    names = {t["name"] for t in mcp.list_tools()}
    assert {
        "brain.hook_coverage_audit",
        "brain.hook_coverage_audit_cell_first",
        "brain.hook_coverage_get",
        "brain.hook_coverage_repair",
        "brain.hook_coverage_repair_cell_first",
    } <= names


def test_legacy_hook_tools_are_retired_without_writes_or_repairs(fake_home, store):
    from personal_brain.server import build_server

    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    mcp = build_server(store=store, default_owner_user="founder")

    audit_result = mcp._tools["brain.hook_coverage_audit"].handler(
        only=["codex"],
        owner_user="founder",
    )
    assert audit_result["ok"] is False
    assert audit_result["migration_only"] is True
    assert audit_result["deprecated"] is True
    assert audit_result["code"] == "legacy_governance_route_retired"
    assert audit_result["brain_written"] is False
    assert audit_result["side_effect_executed"] is False
    assert audit_result["cell_first_alternative"] == (
        "brain.hook_coverage_audit_cell_first"
    )
    assert store.get_meta(hc.COVERAGE_META_KEY) is None

    repair_result = mcp._tools["brain.hook_coverage_repair"].handler(
        only=["codex"],
        dry_run=True,
        owner_user="founder",
    )
    assert repair_result["ok"] is False
    assert repair_result["migration_only"] is True
    assert repair_result["deprecated"] is True
    assert repair_result["code"] == "legacy_governance_route_retired"
    assert repair_result["brain_written"] is False
    assert repair_result["side_effect_executed"] is False
    assert repair_result["cell_first_alternative"] == (
        "brain.hook_coverage_repair_cell_first"
    )
    assert store.get_meta(hc.COVERAGE_META_KEY) is None


def test_monitor_start_runs_startup_audit(fake_home, store, cell_runtime):
    (fake_home / ".codex").mkdir()
    installer.install_all(only=["codex"])
    assert store.get_meta(hc.COVERAGE_META_KEY) is None

    bridge = _InProcessRuntimeBridge(cell_runtime)
    monitor = None
    try:
        monitor = hc.start_hook_coverage_monitor(
            store,
            owner_user="founder",
            only=["codex"],
            interval_s=60.0,
            cell_bridge=bridge,
        )
        report = hc.get_report_cell_first(
            store, owner_user="founder", cell_bridge=bridge
        )
        assert report is not None
        assert report.status == "green"
        assert report.clients["codex"].status == "green"
        assert monitor.status()["cycle_count"] >= 1
        assert store.get_meta(hc.COVERAGE_META_KEY) is None
        assert report.cell_first is True
        assert report.cell_record_root
    finally:
        if monitor is not None:
            monitor.stop()


def test_monitor_periodically_refreshes_coverage(fake_home, store, cell_runtime):
    (fake_home / ".codex").mkdir()
    bridge = _InProcessRuntimeBridge(cell_runtime)
    monitor = None
    try:
        monitor = hc.start_hook_coverage_monitor(
            store,
            owner_user="founder",
            only=["codex"],
            interval_s=0.05,
            cell_bridge=bridge,
        )
        report = hc.get_report_cell_first(
            store, owner_user="founder", cell_bridge=bridge
        )
        assert report is not None
        assert report.clients["codex"].status == "red"
        assert store.get_meta(hc.COVERAGE_META_KEY) is None
        assert report.cell_first is True

        monitor.stop()
        installer.install_all(only=["codex"])
        tick = monitor.tick()
        refreshed = hc.get_report_cell_first(
            store, owner_user="founder", cell_bridge=bridge
        )
        status = monitor.status()

        assert tick["ok"] is True
        assert refreshed is not None
        assert refreshed.clients["codex"].status == "green"
        assert status["cycle_count"] >= 2
        assert store.get_meta(hc.COVERAGE_META_KEY) is None
        assert refreshed.cell_first is True
    finally:
        if monitor is not None:
            monitor.stop()


def test_monitor_auto_repairs_detected_red_client(fake_home, store, cell_runtime):
    (fake_home / ".codex").mkdir()

    bridge = _InProcessRuntimeBridge(cell_runtime)
    monitor = None
    try:
        monitor = hc.start_hook_coverage_monitor(
            store,
            owner_user="founder",
            only=["codex"],
            interval_s=60.0,
            auto_repair=True,
            cell_bridge=bridge,
        )
        report = hc.get_report_cell_first(
            store, owner_user="founder", cell_bridge=bridge
        )
        assert report is not None
        assert report.clients["codex"].status == "green"
        assert installer._codex_hooks_path().exists()
        st = monitor.status()
        assert st["repair_count"] >= 1
        assert st["last_repair"]["cell_first"] is True
        assert st["last_repair"]["after"]["clients"]["codex"]["status"] == "green"
        assert st["last_repair"]["after"]["repair_outcome_cell_record_root"]
    finally:
        if monitor is not None:
            monitor.stop()


def test_monitor_auto_repair_is_opt_in(monkeypatch):
    monkeypatch.delenv("BRAIN_HOOK_COVERAGE_AUTO_REPAIR", raising=False)
    assert hc.hook_coverage_auto_repair_enabled() is False

    monkeypatch.setenv("BRAIN_HOOK_COVERAGE_AUTO_REPAIR", "1")
    assert hc.hook_coverage_auto_repair_enabled() is True


def test_work_assignment_requires_graph_session_before_legacy_coverage_state(
    fake_home,
    store,
    monkeypatch,
):
    from personal_brain import cell_room_wiring
    from personal_brain.server import build_server

    runtime_handle = object()
    monkeypatch.setattr(cell_room_wiring, "_HANDLE", runtime_handle)
    monkeypatch.setattr(
        cell_room_wiring,
        "wire_cell_room",
        lambda mcp, store: runtime_handle,
    )
    monkeypatch.setattr(
        cell_room_wiring,
        "cell_room_leaf_gate",
        lambda leaf_id, phase: {
            "allowed": True,
            "missing": [],
            "matching_entries": ["app:workshop:entry:test-plan"],
        },
    )
    monkeypatch.setattr(cell_room_wiring, "cell_room_injection_tail", lambda: "")

    (fake_home / ".codex").mkdir()
    hc.audit(store, only=["codex"], owner_user="founder")
    aw.add_leaves(store, owner_user="founder", leaves=[{
        "title": "edit governed file",
        "gate_kind": "file_exists",
        "gate_spec": {"path": "x.py"},
        "fit": ["write"],
    }])

    mcp = build_server(store=store, default_owner_user="founder")
    res = mcp._tools["brain.work_assigned_block"].handler(
        runtime="codex",
        fit=["write"],
        owner_user="founder",
        write=True,
    )

    assert res["ok"] is False
    assert res["blocked"] is True
    assert res["universal"] is True
    assert res["code"] == "universal_session_required"
    assert res["leaf"] is None
    assert "Universal Agent Session" in res["error"]
    st = aw.status(store, owner_user="founder")
    assert st["counts"]["open"] == 1
    assert st["counts"]["claimed"] == 0
