"""Courts of the actual shared effect boundary; all physical writers are fakes."""
import copy
from types import SimpleNamespace

import pytest

from nodelang.enforce import defaults, graph_parameters, guarded_write, inspect_pending
from nodelang.universal_pipeline import _observed_effect_engines


@pytest.fixture(autouse=True)
def artifact_transport_fake(monkeypatch):
    """Only the transport is fake here; Rust's artifact courts own type rules."""
    import json
    from tools.pipeline import strict_check
    def check(root, pending, context=None, **options):
        rules = json.loads(context["rules"]) if isinstance(context["rules"], str) else context["rules"]
        content = pending.get("content")
        bad = False
        if pending["kind"] == "document":
            blocks = content.get("blocks") if isinstance(content, dict) else None
            bad = not blocks or any(not row.get("text", "").strip() or row.get("type") not in rules["document"]["block_types"] for row in blocks)
        elif pending["kind"] == "post":
            bad = not content.get("body", "").strip() or len(content["body"]) > int(context["post_limit"])
        elif pending["kind"] == "model":
            if pending.get("format") != "archhub-graph-v1":
                bad = type(content["elements"][0]["parameters"]["height"]["value"]) is not int
        else:
            return {"ok": False, "diagnostics": [{"code": "E0010", "file": "fixture", "line": 1, "column": 1,
                    "language": "product", "message": "no artifact rule", "help": "register a rule"}]}
        diagnostics = [{"code": "E0005", "file": "fixture", "line": 1, "column": 1, "language": "product",
                        "message": "fixture artifact refused by post_limit or typed block contract", "help": "fix the fixture content"}] if bad else []
        return {"ok": not bad, "diagnostics": diagnostics, "observation": {"author": context.get("author"), "new_method": False}}
    monkeypatch.setattr(strict_check, "check_artifact", check, raising=False)


def document(text="Issued drawing notes"):
    return {"kind": "document", "target": "drawing-notes", "content": {"blocks": [{"type": "paragraph", "text": text}]}}


def test_refusal_then_agent_correction_invokes_writer_once_and_reads_exact_value():
    writes = []
    corrections = []

    def writer(pending):
        writes.append(copy.deepcopy(pending))
        return {"ok": True, "revision": "fixture-revision"}

    def correct(pending, refusal):
        assert not writes
        corrections.append(refusal["diagnostics"])
        return document()

    result = guarded_write(document(""), writer, readback=lambda *_: writes[-1], correct=correct)
    assert result["ok"] and result["attempts"] == 2
    assert len(writes) == len(corrections) == 1
    assert result["content_sha256"] == result["readback_sha256"]
    assert "help" in corrections[0][0]


def test_bounded_failure_performs_zero_writes():
    writes = []
    calls = []

    def correct(pending, refusal):
        calls.append(refusal)
        return pending

    result = guarded_write(document(""), writes.append, readback=lambda *_: None,
                           correct=correct, params={"max_attempts": "2"})
    assert not result["ok"] and result["attempts"] == 2
    assert len(calls) == 1 and not writes


def test_missing_readback_adapter_refuses_before_write():
    writes = []
    result = guarded_write(document(), writes.append)
    assert not result["ok"] and not writes
    assert "readback" in result["display"]


def test_mutated_or_stale_writer_receipt_never_counts_as_pass():
    def writer(pending):
        pending["content"]["blocks"][0]["text"] = "changed behind the compiler"
        return {"ok": True}

    result = guarded_write(document(), writer, readback=lambda *_: document("stale"))
    assert not result["ok"]
    assert result["content_sha256"] != result["readback_sha256"]


def test_pipeline_actual_caller_preserves_refusal_and_admits_fixed_pending():
    writes = []

    def effect(params, feeds):
        writes.append(copy.deepcopy(feeds["pending"]))
        return {"ok": True, "out": "written"}, "fake host receipt"

    effect.enforce_pending = True
    effect.enforce_kind = "document"
    effect.enforce_readback = lambda *_: writes[-1]
    failed, refused = [], []
    call = _observed_effect_engines({"fixture.write": effect}, failed, refused)["fixture.write"]
    output, shown = call({}, {"pending": document("")})
    assert not output["ok"] and "error[E0005]" in shown
    assert refused == ["fixture.write"] and not failed and not writes
    output, shown = call({}, {"pending": document()})
    assert output["ok"] and shown == "fake host receipt" and len(writes) == 1
    assert output["enforcement"]["content_sha256"] == output["enforcement"]["readback_sha256"]
    assert "observation" in output["enforcement"]


def test_writers_without_an_adapter_keep_their_own_checks_and_unsupported_pending_fails():
    writes = []

    def opaque(params, feeds):
        writes.append(feeds)
        return {"ok": True}, "engine answered"

    call = _observed_effect_engines({"library.terminal": opaque}, [], [])["library.terminal"]
    result, _ = call({}, {"pending": document()})
    assert result == {"ok": True} and len(writes) == 1
    assert not inspect_pending({"kind": "unknown-language", "target": "out"})["ok"]


def test_unknown_engine_without_an_adapter_runs_its_own_engine_once():
    writes = []
    def effect(params, feeds):
        writes.append(feeds)
        return {"ok": True}, "unexpected"
    call = _observed_effect_engines({"fresh.capability": effect}, [], [])["fresh.capability"]
    assert call({}, {})[0]["ok"] is True
    assert len(writes) == 1


def test_unavailable_write_settings_do_not_block_read_only_bystanders():
    def unavailable():
        raise ValueError("write Settings unavailable")
    def read(params, feeds):
        return {"out": "read"}, "read"
    call = _observed_effect_engines({"text.ops": read}, [], [], enforce_parameters=unavailable)["text.ops"]
    assert call({}, {}) == ({"out": "read"}, "read")


def test_pipeline_agent_correction_is_bounded_and_uses_corrected_value():
    writes = []
    def effect(params, feeds):
        writes.append(copy.deepcopy(feeds["pending"]))
        return {"ok": True}, "written"
    effect.enforce_pending = True
    effect.enforce_kind = "document"
    effect.enforce_readback = lambda *_: writes[-1]
    effect.enforce_correct = lambda *_: document("agent corrected this content")
    call = _observed_effect_engines({"agent.write": effect}, [], [])["agent.write"]
    output, _ = call({}, {"pending": document("")})
    assert output["ok"] and len(writes) == 1
    assert writes[0]["content"]["blocks"][0]["text"] == "agent corrected this content"


def test_actual_server_effect_binding_preserves_enforcement_contract():
    from nodelang.application_server import ApplicationServer
    writes = []
    store = object()
    def effect(params, feeds):
        assert params["mods_store"] is store
        writes.append(copy.deepcopy(feeds["pending"]))
        return {"ok": True}, "server bound receipt"
    effect.enforce_pending = True
    effect.enforce_kind = "model"
    effect.enforce_readback = lambda *_: writes[-1]
    owner = SimpleNamespace(pipeline_effect_engines={"revit.create_sheets": effect}, universal_store=store)
    engines = ApplicationServer._effect_engines_with_mods_store(owner)
    call = _observed_effect_engines(engines, [], [])["revit.create_sheets"]
    assert not call({}, {"pending": document()})[0]["ok"]
    assert not writes
    model = {"kind": "model", "target": "fixture-model", "content": {"elements": [
        {"id": "wall-1", "parameters": {"height": {"type": "number", "value": 3000}}}]}}
    assert call({}, {"pending": model})[0]["ok"] and len(writes) == 1


def test_agent_correction_cannot_change_the_typed_writer_contract():
    writes = []
    def effect(params, feeds):
        writes.append(feeds)
        return {"ok": True}, "unexpected"
    effect.enforce_pending = True
    effect.enforce_kind = "document"
    effect.enforce_readback = lambda *_: document()
    effect.enforce_correct = lambda *_: {"kind": "post", "target": "feed", "content": {"account": "a", "platform": "web", "body": "hello"}}
    call = _observed_effect_engines({"agent.write": effect}, [], [])["agent.write"]
    result, _ = call({}, {"pending": document("")})
    assert not result["ok"] and not writes and "declared artifact kind" in result["display"]


def test_direct_writers_without_an_adapter_reach_their_own_engine_and_reads_pass():
    # An engine without an Enforce write adapter keeps its own approval/grant checks;
    # the shared boundary must not refuse it outright (no pass path = kill switch).
    from nodelang.application_server import ApplicationServer
    owner = ApplicationServer.__new__(ApplicationServer)
    owner.universal_store = object()
    calls = []
    def dispatch(params, feeds):
        calls.append((params, feeds))
        return {'ok': True}, 'engine answered'
    for operation in ('social.post', 'workshop.project.repair'):
        assert owner._guard_direct_effect(operation, dispatch, {}, {}) == ({'ok': True}, 'engine answered')
    assert len(calls) == 2
    assert owner._guard_direct_effect('skills.thinking_chain', lambda *_: ({'out': []}, 'read'), {}, {}) == ({'out': []}, 'read')


def test_code_compiler_receives_pending_overlay_without_touching_original(tmp_path):
    source = tmp_path / "module.py"
    source.write_text("original = True\n")
    calls = []

    def compiler(root, paths, *, overlay, timeout, context):
        calls.append((root, paths, overlay, timeout, context))
        assert source.read_text() == "original = True\n"
        bad = "bad" in overlay["module.py"]
        return {"ok": not bad, "diagnostics": [{"code": "E0001", "file": "module.py", "line": 1,
                "column": 1, "language": "python", "message": "duplicate route", "help": "remove the second owner"}] if bad else []}

    pending = {"kind": "code", "target": "module.py", "changes": {"module.py": "bad = True\n"},
               "intent": "ACOMPILER", "author": "fixture-human", "why": "repair duplicate ownership"}
    result = inspect_pending(pending, {"repo_root": str(tmp_path)}, compiler=compiler)
    assert not result["ok"] and "error[E0001]" in result["display"]
    pending["changes"]["module.py"] = "fixed = True\n"
    assert inspect_pending(pending, {"repo_root": str(tmp_path)}, compiler=compiler)["ok"]
    assert len(calls) == 2 and source.read_text() == "original = True\n"
    assert calls[-1][-1]["intent"] == "ACOMPILER" and calls[-1][-1]["author"] == "fixture-human"
    assert calls[-1][-1]["daily_alert_budget"] == defaults()["daily_alert_budget"]
    assert calls[-1][-1]["intent_rule_set"] == defaults()["intent_rule_set"]


def test_asserted_code_cannot_use_noncode_extension_to_skip_language_coverage(tmp_path):
    calls = []
    def empty_coverage(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "diagnostics": []}
    pending = {"kind": "code", "target": "x.txt", "changes": {"x.txt": "undefined()"}}
    result = inspect_pending(pending, {"repo_root": str(tmp_path)}, compiler=empty_coverage)
    assert not result["ok"] and result["diagnostics"][0]["code"] == "E0010"
    assert not calls


@pytest.mark.parametrize("pending", [
    {"kind": "model", "target": "host-model", "content": {"elements": [{"id": "wall-1", "parameters": {"height": {"type": "number", "value": "wrong"}}}]}},
    {"kind": "post", "target": "company-feed", "content": {"account": "company", "platform": "web", "body": ""}},
    {"kind": "document", "target": "notes", "content": "a claim that this document is correct"},
])
def test_each_noncode_domain_rejects_invalid_typed_pending_values(pending):
    assert not inspect_pending(pending)["ok"]


def test_settings_existing_owner_writer_changes_runtime_rule_parameters():
    from nodelang.domains.selfext import set_mod_param
    from nodelang.universal_application import _project_application_node_settings
    from nodelang.universal_cell import CellStore
    store = CellStore()
    set_mod_param(store, "enforce", "post_limit", 4)
    parameters = graph_parameters(store)
    assert parameters["post_limit"] == 4
    registry = SimpleNamespace(map=SimpleNamespace(domains={"selfext": "selfext-root"}))
    nodes = [{"id": "selfext-root", "application": True, "label": "Self-Extension"}]
    rows = _project_application_node_settings(nodes, [], "selfext-root", registry=registry,
                                             snapshot=store.snapshot(), theme_fields=[], theme_value_root="",
                                             baboom={}, composer={})
    row = next(row for row in rows if row["setting"] == {"kind": "mod-param", "mod_id": "enforce", "key": "post_limit"})
    assert row["value"] == parameters["post_limit"] and row["editable"]
    pending = {"kind": "post", "target": "feed", "content": {"account": "a", "platform": "web", "body": "hello"}}
    result = inspect_pending(pending, parameters)
    assert not result["ok"] and "post_limit" in result["display"]


def test_catalogue_parameters_have_typed_sockets_and_runtime_readers():
    from nodelang.base_universal_catalogue import BASE_CATALOGUE
    from nodelang.library_engines import library_catalogue
    entry = next(row for row in BASE_CATALOGUE if row["engine"] == "archhub.enforce")
    assert all(name in entry["interfaces"] for name in defaults())
    assert all(entry["interfaces"][name]["type"] != "unknown" for name in defaults())
    rows = [row for group in library_catalogue() for row in group["items"] if row["engine"] == "archhub.enforce"]
    assert len(rows) == 1 and not rows[0].get("hidden") and not rows[0].get("noEngine")


def test_old_host_hook_cannot_use_unrelated_clean_pending_to_bypass_admission():
    from nodelang.domains.selfext import before_write_hooks
    with pytest.raises(PermissionError, match="exact typed pending"):
        before_write_hooks(None, "revit.set_parameter_by_name", {"name": "height", "value": "wrong", "pending_write": document()})


def test_rule_sets_are_editable_settings_parameters_with_real_readers():
    from nodelang.domains.selfext import set_mod_param
    from nodelang.universal_cell import CellStore
    store = CellStore()
    rule_text = '{"document":{"block_types":["heading"]},"model":{"value_types":["string"]},"post":{"platforms":["web"]}}'
    set_mod_param(store, "enforce", "rules", rule_text)
    assert not inspect_pending(document(), graph_parameters(store))["ok"]
    heading = document()
    heading["content"]["blocks"][0]["type"] = "heading"
    assert inspect_pending(heading, graph_parameters(store))["ok"]


def selfext_fixture():
    from nodelang import Store
    from nodelang.domains.selfext import build_self_extension_domain, set_install_approval
    from tests_domains.test_selfext import _green_court
    store = Store()
    domain = build_self_extension_domain(store)
    _green_court(store, domain)
    set_install_approval(store, domain, True, approver="fixture-founder", approved_at="2026-10-16T12:00:00Z")
    return store, domain


def test_actual_selfextension_install_uses_live_graph_schema_and_readback():
    from nodelang.domains.selfext import apply_installation
    store, domain = selfext_fixture()
    sink = {}
    receipt = apply_installation(store, domain, sink)
    assert receipt["fired"] and sink[receipt["target"]] == receipt["after"]
    assert receipt["enforcement"]["content_sha256"] == receipt["enforcement"]["readback_sha256"]


def test_actual_selfextension_refuses_unknown_generated_primitive_before_mutation():
    from nodelang.domains.selfext import apply_installation
    store, domain = selfext_fixture()
    parameter = domain["generated_params"][0]["primitive"]
    store.edit(parameter, ["body", "floor", "value"], "host")
    sink = {}
    with pytest.raises(PermissionError, match="E0009"):
        apply_installation(store, domain, sink)
    assert not sink and store.nodes[domain["install_effect"]]["meta"]["frozen"]


def test_actual_selfextension_rechecks_parameter_reference_type():
    from nodelang.domains.selfext import apply_installation
    store, domain = selfext_fixture()
    group = domain["generated_groups"][0]
    store.nodes[group]["params"]["primitive"] = domain["generated_manifest"]
    with pytest.raises(PermissionError, match="E0009"):
        apply_installation(store, domain, {})
    assert store.nodes[domain["install_effect"]]["meta"]["frozen"]


def test_actual_selfextension_does_not_accept_a_lying_sink_receipt():
    from nodelang.domains.selfext import apply_installation
    store, domain = selfext_fixture()
    class LyingSink(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, {"wrong": "content"})
    with pytest.raises(PermissionError, match="readback differs"):
        apply_installation(store, domain, LyingSink())
    assert store.pull(domain["installed"]) is False
    assert store.nodes[domain["install_effect"]]["meta"]["frozen"]


def test_actual_selfextension_edit_invalidates_exact_approval():
    from nodelang.domains.selfext import apply_installation
    store, domain = selfext_fixture()
    configuration = domain["generated_params"][0]["configuration"]
    store.edit(configuration, ["body", "floor", "value"], {"value": "changed after approval"})
    sink = {}
    with pytest.raises(PermissionError, match="content changed since exact approval"):
        apply_installation(store, domain, sink)
    assert not sink and store.nodes[domain["install_effect"]]["meta"]["frozen"]


def test_enforce_node_uses_shared_attempt_bound():
    from nodelang.enforce import engine
    refused, _ = engine({"max_attempts": 0}, {"pending": document()})
    assert not refused["ok"]
    assert "max_attempts must be positive" in refused["display"]
    admitted, _ = engine({"max_attempts": 1}, {"pending": document()})
    assert admitted["ok"] and admitted["attempts"] == 1
    assert admitted["admitted"] == document()
    content_status, _ = engine({"max_attempts": 1}, {"pending": {**document(), "ok": False}})
    assert content_status["ok"] and content_status["admitted"]["ok"] is False


def test_enforce_build_parameters_reach_default_bridge(monkeypatch):
    from tools.pipeline import strict_check
    original = strict_check.check_artifact
    seen = []
    def transport(*args, **kwargs):
        seen.append(kwargs.pop("build_options"))
        return original(*args, **kwargs)
    monkeypatch.setattr(strict_check, "check_artifact", transport)
    result = inspect_pending(document(), {"compiler_jobs": 3, "compiler_rustflags": "-C target-feature=+crt-static"})
    assert result["ok"]
    assert seen == [{"jobs": 3, "rustflags": "-C target-feature=+crt-static"}]


def test_no_effect_path_is_refused_unconditionally():
    """A refusal with no pass path is a kill switch, not enforcement: the terminal, Workshop
    native turn and relay, host and Revit writes, social posts, file/package publication,
    memory/delegate and update reload must reach their own approval and readback checks."""
    import pathlib
    from nodelang import enforce
    assert not hasattr(enforce, 'require_typed_adapter')
    root = pathlib.Path(enforce.__file__).parent
    offenders = [str(path) for path in root.rglob('*.py') if 'require_typed_adapter' in path.read_text(encoding='utf-8')]
    assert offenders == []
