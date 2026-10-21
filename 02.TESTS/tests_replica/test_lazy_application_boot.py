"""Cold Home and verified first-open courts, using disposable synthetic stores.

The shipped eager restore function comes from canonical main 479df6bd and is
SHA-256 verified before paired timing. Git is only a fallback if that fixture
is absent; exported trees run without Git. Timings include fresh CellStore
open, restore, and Home projection.
"""
from __future__ import annotations

import ast
from collections import Counter
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier
import time
from urllib.request import Request, urlopen

import pytest

from nodelang import cell_protocols, universal_application as application
from nodelang import universal_cell, universal_map_import
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.lazy_application_registry import DeferredRegistryField, DeferredRegistryGroup
from nodelang.map_import import resolve_map_path
from nodelang.universal_cell import Cell, CellStore, InvalidCell


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "479df6bdf130145ec857332b48d1fd2d230451e3"
BASELINE_FIXTURE = ROOT / "02.TESTS/tests_replica" / "fixtures" / "lazyboot_eager_restore.py.txt"
# Exact UTF-8 source span 15360-17311 of nodelang/universal_application.py
# at canonical main BASELINE, including its decorator. Identical to the
# lane-local c5570d1 function; no other baseline module code is executed.
BASELINE_SOURCE_SHA256 = "df025a80118d100b0abe093a0873711473f82b5d35360f9dc16d834a485c5e4f"


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"l" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"b" * 32)
    return provider


def _baseline_restore():
    if BASELINE_FIXTURE.is_file():
        source = BASELINE_FIXTURE.read_bytes().decode("utf-8")
    else:
        try:
            source = subprocess.check_output(
                ["git", "show", BASELINE + ":nodelang/universal_application.py"],
                cwd=ROOT, stderr=subprocess.PIPE,
            ).decode("utf-8")
        except (OSError, subprocess.CalledProcessError) as error:
            print(
                f"SKIPPED paired eager baseline {BASELINE}: shipped fixture absent "
                f"and Git source unavailable ({type(error).__name__}); "
                "lazy Home and replica courts still run.",
                flush=True,
            )
            return None, None
    module = ast.parse(source)
    function = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "restore_universal_application"
    )
    first_line = min([function.lineno, *(node.lineno for node in function.decorator_list)])
    original = "".join(source.splitlines(keepends=True)[first_line - 1:function.end_lineno])
    source_hash = hashlib.sha256(original.encode()).hexdigest()
    assert source_hash == BASELINE_SOURCE_SHA256, "eager baseline restore source SHA-256 changed"
    namespace = dict(vars(application))
    program = ast.Module(body=[function], type_ignores=[])
    exec(compile(program, "<main restore_universal_application>", "exec"), namespace)
    return namespace[function.name], source_hash


def test_concurrent_first_opens_share_one_verified_factory_result():
    calls = []
    value = object()
    ready = Barrier(8)

    def factory():
        calls.append(True)
        return {"value": value}

    field = DeferredRegistryGroup(factory).field("value")

    def first_open(_):
        ready.wait(timeout=3)
        return field.resolve()

    with ThreadPoolExecutor(max_workers=8) as readers:
        results = tuple(readers.map(first_open, range(8)))
    assert calls == [True]
    assert all(result is value for result in results)


def test_fixture_generator_refuses_existing_or_non_temporary_destinations():
    from tools.seed_large_store import seed_large_store

    with pytest.raises(ValueError, match="must be a child"):
        seed_large_store(Path(tempfile.gettempdir()).anchor, target_gb=0.001)
    with tempfile.TemporaryDirectory(prefix="archhub-fixture-refusal-") as directory:
        destination = Path(directory)
        readme = destination / "README.md"
        readme.write_text("Purpose: generator refusal court. Owner: boot court.\n"
                          "Tier: T0. Scope: temporary fixture only.\n", encoding="utf-8")
        for state in ("01.WIP", "02.SHARED", "03.PUBLISHED", "04.ARCHIVE"):
            (destination / state).mkdir()
        digest = hashlib.sha256(readme.read_bytes()).hexdigest()
        (destination / "REGISTER.md").write_text(
            "No | title | rev | state | date | file | SHA-256\n"
            f"1 | Fixture refusal | 1 | WIP | 2026-10-14 | README.md | {digest}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must be empty"):
            seed_large_store(destination, target_gb=0.001)
        assert not list(destination.rglob("*.sqlite3"))


@contextmanager
def _reads(monkeypatch):
    """Count actual SQL materializations, rather than logical cache reads."""
    roots = Counter()
    physical = Counter()
    members = Counter()
    original_walk = cell_protocols._read_relation_walk
    original_remember = universal_cell._HeadRowReader._remember

    def walk(snapshot, root, *args, **kwargs):
        roots[root] += 1
        answer = original_walk(snapshot, root, *args, **kwargs)
        members[root] += len(answer)
        return answer

    def remember(reader, key, cell):
        physical[key] += 1
        return original_remember(reader, key, cell)

    with monkeypatch.context() as scope:
        scope.setattr(cell_protocols, "_read_relation_walk", walk)
        scope.setattr(universal_cell._HeadRowReader, "_remember", remember)
        yield roots, physical, members


def _statistics(roots, physical, members):
    def category_of(identifier):
        parts = identifier.split(":", 2)
        if len(parts) < 2 or (len(parts[1]) == 36 and parts[1][8:9] == "-"):
            return parts[0] + ":"
        return ":".join(parts[:2]) + ":"

    relation_categories = {}
    physical_categories = Counter()
    for root, count in roots.items():
        category = category_of(root)
        held = relation_categories.setdefault(category, {
            "walks": 0, "unique_roots": 0, "members_walked": 0,
        })
        held["walks"] += count
        held["unique_roots"] += 1
        held["members_walked"] += members[root]
    for cell, count in physical.items():
        physical_categories[category_of(cell)] += count
    return {
        "relation_walks": sum(roots.values()),
        "unique_relation_roots": len(roots),
        "relation_members_walked": sum(members.values()),
        "physical_cells_read": sum(physical.values()),
        "unique_physical_cells_read": len(physical),
        "relation_categories": dict(sorted(relation_categories.items())),
        "physical_cell_categories": dict(sorted(physical_categories.items())),
    }


@pytest.fixture(scope="module")
def large_fixture():
    from tools.seed_large_store import seed_large_store

    # Row, empty-atom, chain, identifier-byte and history ratios follow STEP 1.
    with tempfile.TemporaryDirectory(prefix="archhub-lazyboot-court-") as directory:
        ledger = os.environ.get("LAZYBOOT_TEMP_LEDGER")
        if ledger:
            with Path(ledger).open("a", encoding="utf-8") as output:
                output.write(json.dumps({"owned_fixture_root": directory}) + "\n")
        manifest = seed_large_store(
            Path(directory),
            target_gb=float(os.environ.get("LAZYBOOT_FIXTURE_GB", "0.08")),
        )
        yield manifest
    assert not Path(directory).exists(), "synthetic fixture was not removed"


def _close_fixture_store(store):
    # Runtime/CDE readers own separate connections to this fixture database.
    for name in ("_runtime_presence_lease_storage", "_cde_operational_storage"):
        storage = getattr(store, name, None)
        if storage is not None:
            storage.close()
    store.close()


def _boot(manifest, restore, monkeypatch, *, home_frame=False):
    from tools.seed_large_store import FIXTURE_EPOCH

    provider = manifest.get("key_provider") or _provider()
    with monkeypatch.context() as clock_scope, _reads(monkeypatch) as (roots, physical, members):
        # Identical unexpired fixture authority for both cold reopens. Wall
        # duration still uses the real monotonic performance counter.
        clock_scope.setattr(time, "time", lambda: FIXTURE_EPOCH)
        original_map_projector = universal_map_import.project_grand_map_cells
        map_calls = []
        map_stage = "restore"

        def project_map(*args, **kwargs):
            caller = sys._getframe(1)
            map_calls.append({
                "stage": map_stage,
                "lazy": kwargs.get("lazy", False),
                "caller": caller.f_code.co_name,
                "file": Path(caller.f_code.co_filename).name,
                "line": caller.f_lineno,
            })
            return original_map_projector(*args, **kwargs)

        clock_scope.setattr(universal_map_import, "project_grand_map_cells", project_map)
        clock_scope.setattr(application, "project_grand_map_cells", project_map)
        restored_function = restore
        while hasattr(restored_function, "__wrapped__"):
            restored_function = restored_function.__wrapped__
        if restored_function.__name__ == "restore_universal_application":
            clock_scope.setitem(restored_function.__globals__, "project_grand_map_cells", project_map)
        started = time.perf_counter()
        store = CellStore(manifest["path"])
        try:
            opening_revision = store.revision
            _, registry = restore(
                manifest.get("map_path") or resolve_map_path(),
                store,
                key_provider=provider,
            )
            restored_at = time.perf_counter()
            restored_revision = store.revision
            map_stage = "home"
            restore_stats = _statistics(roots, physical, members)
            restore_roots = set(roots)
            context = registry.authorization.session.context(minimum_validity_seconds=5)
            home = (application.project_universal_home_frame(
                        store, registry, authentication_context=context) if home_frame
                    else application.project_universal_canvas(store, registry))
            from nodelang.universal_graphs import project_graph_index
            graph_index = project_graph_index(store, registry, authentication_context=context,
                                             include_canvas=not home_frame)
            ready_at = time.perf_counter()
            home_revision = store.revision
            home_stats = _statistics(roots, physical, members)
            boot_roots = set(roots)
            agent_field = object.__getattribute__(registry, "agent_body")
            agent_deferred = (
                isinstance(agent_field, DeferredRegistryField)
                and agent_field.group._values is None
            )
            map_field = object.__getattribute__(registry.map, "nodes")
            map_deferred = (
                isinstance(map_field, DeferredRegistryField)
                and map_field.group._values is None
            )
            canvas_evidence = os.environ.get("LAZYBOOT_CANVAS_REPORT")
            if canvas_evidence and agent_deferred and map_deferred:
                # Synthetic data only; export after the Home timing boundary
                # for the UI rendering court, not as part of measured boot.
                Path(canvas_evidence).write_text(json.dumps(home, indent=2) + "\n", encoding="utf-8")
                graph_evidence = os.environ.get("LAZYBOOT_GRAPH_REPORT")
                if graph_evidence:
                    Path(graph_evidence).write_text(json.dumps(graph_index, indent=2) + "\n", encoding="utf-8")
            before_open = sum(physical.values())
            map_stage = "first_agent_open"
            first_open_started = time.perf_counter()
            body = registry.agent_body
            opened_at = time.perf_counter()
            assert body.body.root_id
            assert registry.agent_body is body
            workshop_field = object.__getattribute__(registry, "workshop_category_roots")
            workshop_deferred = (isinstance(workshop_field, DeferredRegistryField)
                                 and workshop_field.group._values is None)
            before_workspace = sum(physical.values())
            map_stage = "first_workspace_open"
            workspace_started = time.perf_counter()
            workspace = (application.project_universal_canvas(store, registry)
                         if home_frame else home)
            workspace_opened = time.perf_counter()
            workspace_evidence = os.environ.get("LAZYBOOT_WORKSPACE_REPORT")
            if workspace_evidence and home_frame:
                Path(workspace_evidence).write_text(json.dumps(workspace, indent=2) + "\n", encoding="utf-8")
            return {
                "restore_seconds": restored_at - started,
                "opening_revision": opening_revision,
                "restored_revision": restored_revision,
                "home_revision": home_revision,
                "home_ready_seconds": ready_at - started,
                "home_and_primary_agent_identity_ready_seconds": opened_at - started,
                "first_agent_open_seconds": opened_at - first_open_started,
                "first_agent_physical_cells": before_workspace - before_open,
                "agent_deferred_at_home": agent_deferred,
                "map_deferred_at_home": map_deferred,
                "workshop_deferred_after_transport_identity": workshop_deferred,
                "canvas_deferred_at_home": home.get("canvas_deferred", False),
                "first_workspace_open_seconds": workspace_opened - workspace_started,
                "first_workspace_physical_cells": sum(physical.values()) - before_workspace,
                "restore": restore_stats,
                "home_ready": home_stats,
                "restore_roots": restore_roots,
                "home_roots": boot_roots,
                "node_ids": tuple(node["id"] for node in workspace["nodes"]),
                "scope": workspace["scope"],
                "selected": workspace.get("selected"),
                "properties": workspace.get("properties"),
                "home_theme": home["configuration"]["theme"],
                "agent_root": body.body.root_id,
                "map_projection_calls": list(map_calls),
            }
        finally:
            _close_fixture_store(store)


def _boot_replica_home(manifest, monkeypatch, expected):
    """Measure constructor/start plus authenticated Home on the owned fixture.

    This is a replica backend with native/machine/cloud transports disabled;
    installed desktop startup still requires its separate install proof.
    """
    from nodelang.application_server import ApplicationServer
    from nodelang import cloud_signin, pipeline_engines
    from tools.seed_large_store import FIXTURE_EPOCH

    opening = CellStore(manifest["path"])
    try:
        opening_revision = opening.revision
    finally:
        _close_fixture_store(opening)
    companion = Path(str(manifest["path"]) + ".conversations.sqlite3")
    companion_counts = {"conversations": 0, "messages": 0}
    if companion.exists():
        connection = sqlite3.connect(companion.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            companion_counts = {table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                                for table in companion_counts}
        finally:
            connection.close()
    assert companion_counts == {"conversations": 0, "messages": 0}, "the replica companion fixture starts empty"
    forbidden_probes = []

    def refuse_live_probe(name):
        def refused(*_args, **_kwargs):
            forbidden_probes.append(name)
            raise AssertionError("replica boot court must not probe live " + name)
        return refused

    with monkeypatch.context() as scope, _reads(monkeypatch) as (roots, physical, members):
        scope.setattr(time, "time", lambda: FIXTURE_EPOCH)
        scope.setenv("ARCHHUB_GRAND_MAP_PATH", str(manifest.get("map_path") or resolve_map_path()))
        scope.setattr(pipeline_engines, "_brain_call", refuse_live_probe("Brain"))
        scope.setattr(pipeline_engines, "probe_connectors", refuse_live_probe("hosts"))
        scope.setattr(ApplicationServer, "_probe_brain", staticmethod(lambda: {"ok": True, "facts": 7}))
        scope.setattr(ApplicationServer, "_probe_hosts", staticmethod(lambda: []))
        scope.setattr(cloud_signin, "sign_in_state", lambda *_args, **_kwargs: {
            "state": "signed_out", "signed_in": False, "email": "",
            "expires_at": None, "founder": False,
        })
        server = None
        store = None
        started = time.perf_counter()
        try:
            server = ApplicationServer(
                universal_state_path=manifest["path"],
                universal_key_provider=manifest.get("key_provider") or _provider(),
                universal_workspace_root=Path(manifest["path"]).parent,
                enable_machine_transport=False, enable_universal_cloud_gateway=False,
                enable_brain_cloud_sync=False,
                enable_machine_projection_prewarm=False, live_watch=False,
            )
            store, registry = server.universal_store, server.universal_registry
            constructed_at = time.perf_counter()
            constructed_revision = store.revision
            server.start()
            primary_identity = registry.agent_body.session.root_id
            assert primary_identity and registry.agent_body.body.root_id == expected["agent_root"]

            def get(route):
                request = Request(server.url + route, headers={
                    "X-ArchHub-Session": server.browser_session_token,
                    "X-ArchHub-CSRF": server.browser_csrf_token,
                    "Origin": server.url,
                })
                with urlopen(request, timeout=30) as response:
                    assert response.status == 200
                    answer = json.loads(response.read().decode("utf-8"))
                assert answer.get("ok") is not False, answer
                return answer

            home = get("/api/universal/canvas?screen=home")
            graphs = get("/api/universal/graphs?screen=home")
            ready_at = time.perf_counter()
            home_revision = store.revision
            home_stats = _statistics(roots.copy(), physical.copy(), members.copy())
            home_roots = set(roots)
            map_field = object.__getattribute__(registry.map, "nodes")
            workshop_field = object.__getattribute__(registry, "workshop_category_roots")
            map_deferred = isinstance(map_field, DeferredRegistryField) and map_field.group._values is None
            workshop_deferred = isinstance(workshop_field, DeferredRegistryField) and workshop_field.group._values is None
            assert ready_at - started <= 21.0
            assert home["canvas_deferred"] and graphs["canvas"]["canvas_deferred"]
            assert home["nodes"] == home["wires"] == []
            assert home["interaction_projection"]["bindings"] == []
            assert map_deferred and workshop_deferred
            assert home["scope"]["current"] == expected["scope"]["current"]
            assert tuple(row["root"] for row in home["scope"]["trail"]) == tuple(
                row["root"] for row in expected["scope"]["trail"])
            assert home["configuration"]["theme"] == expected["home_theme"]
            assert not set(manifest["synthetic_relation_roots"]) & home_roots

            workspace_started = time.perf_counter()
            workspace = get("/api/universal/canvas")
            workspace_opened = time.perf_counter()
            assert tuple(node["id"] for node in workspace["nodes"]) == expected["node_ids"]
            assert workspace["scope"] == expected["scope"]
            assert workspace.get("selected") == expected["selected"]
            assert workspace.get("properties") == expected["properties"]
            assert workspace["configuration"]["theme"] == expected["home_theme"]
            assert forbidden_probes == [], "a background worker attempted a forbidden live producer"
            # Replace pure-function exports with actual authenticated replica
            # responses only after both Home and first Workspace have passed.
            for name, value in (("LAZYBOOT_CANVAS_REPORT", home),
                                ("LAZYBOOT_GRAPH_REPORT", graphs),
                                ("LAZYBOOT_WORKSPACE_REPORT", workspace)):
                destination = os.environ.get(name)
                if destination:
                    Path(destination).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            return {
                "mode": "replica backend; native/machine/cloud transports disabled",
                "companion_initial_counts": companion_counts,
                "forbidden_live_probe_calls": len(forbidden_probes),
                "constructor_seconds": constructed_at - started,
                "home_and_primary_agent_identity_ready_seconds": ready_at - started,
                "first_workspace_open_seconds": workspace_opened - workspace_started,
                "opening_revision": opening_revision,
                "constructed_revision": constructed_revision,
                "home_revision": home_revision,
                "first_workspace_revision": workspace["revision"],
                "canvas_deferred_at_home": home["canvas_deferred"],
                "map_deferred_at_home": map_deferred,
                "workshop_deferred_at_home": workshop_deferred,
                "home_ready": home_stats,
            }
        finally:
            try:
                if server is not None:
                    server.close()
            finally:
                if store is not None:
                    _close_fixture_store(store)
                assert forbidden_probes == [], "a teardown worker attempted a forbidden live producer"


def test_large_store_cold_home_is_bounded_and_unrelated_relations_wait(
    large_fixture, monkeypatch,
):
    baseline_restore, source_hash = _baseline_restore()
    eager = None
    if baseline_restore is not None:
        print("begin original restore on generated fixture", flush=True)
        eager = _boot(large_fixture, baseline_restore, monkeypatch)
        print("original Home ready: %.6fs; %d restore cell fetches" %
              (eager['home_ready_seconds'], eager['restore']['physical_cells_read']), flush=True)

    def lazy_restore(*args, **kwargs):
        return application.restore_universal_application(*args, lazy=True, **kwargs)

    print("begin lazy restore on same generated fixture", flush=True)
    lazy = _boot(large_fixture, lazy_restore, monkeypatch, home_frame=True)
    print("lazy Home ready: %.6fs; %d restore cell fetches" %
          (lazy['home_ready_seconds'], lazy['restore']['physical_cells_read']), flush=True)
    assert lazy["restored_revision"] == lazy["home_revision"] == lazy["opening_revision"]
    assert lazy["agent_deferred_at_home"]
    assert lazy["map_deferred_at_home"]
    assert lazy["workshop_deferred_after_transport_identity"]
    assert lazy["canvas_deferred_at_home"]
    assert lazy["first_agent_physical_cells"] > 0
    assert lazy["home_ready_seconds"] <= 21.0
    assert lazy["home_and_primary_agent_identity_ready_seconds"] <= 21.0
    deferred_roots = set(large_fixture["synthetic_relation_roots"])
    assert not deferred_roots & lazy["restore_roots"]
    assert not deferred_roots & lazy["home_roots"]
    if eager is not None:
        assert lazy["node_ids"] == eager["node_ids"]
        assert lazy["opening_revision"] == eager["opening_revision"]
        assert eager["restored_revision"] == eager["home_revision"] == eager["opening_revision"]
        assert lazy["scope"] == eager["scope"]
        assert lazy["selected"] == eager["selected"]
        assert lazy["properties"] == eager["properties"]
        assert lazy["home_theme"] == eager["home_theme"]
        assert lazy["agent_root"] == eager["agent_root"]
        assert lazy["restore"]["relation_members_walked"] < eager["restore"]["relation_members_walked"]
        assert lazy["restore"]["physical_cells_read"] < eager["restore"]["physical_cells_read"]
        assert deferred_roots & eager["restore_roots"]
    print("begin replica constructor and authenticated Home on same generated fixture", flush=True)
    replica = _boot_replica_home(large_fixture, monkeypatch, lazy)
    report = {
        "baseline_ref": BASELINE,
        "baseline_status": "measured" if eager is not None else "unavailable; paired eager timing skipped",
        "baseline_restore_source_sha256": source_hash,
        "fixture": {
            **{key: value for key, value in large_fixture.items()
               if key not in {"path", "key_provider", "map_path",
                              "target_member_roots", "synthetic_relation_roots",
                              "target_relation_root"}},
            "synthetic_relation_count": len(deferred_roots),
        },
        "before": ({key: value for key, value in eager.items()
                    if key not in {"restore_roots", "home_roots", "node_ids", "scope"}}
                   if eager is not None else None),
        "after": {key: value for key, value in lazy.items()
                  if key not in {"restore_roots", "home_roots", "node_ids", "scope"}},
        "replica_backend": replica,
    }
    encoded = json.dumps(report, indent=2, default=str)
    evidence = os.environ.get("LAZYBOOT_BOOT_REPORT")
    if evidence:
        Path(evidence).write_text(encoded + "\n", encoding="utf-8")
    summary = dict(report)
    for phase in ("before", "after"):
        if report[phase] is None:
            continue
        summary[phase] = dict(report[phase])
        for stage in ("restore", "home_ready"):
            summary[phase][stage] = {
                key: value for key, value in report[phase][stage].items()
                if key not in {"relation_categories", "physical_cell_categories"}
            }
    print("LAZYBOOT_MEASURED " + json.dumps(summary, default=str, sort_keys=True))


def test_shipped_eager_baseline_runs_without_git(monkeypatch):
    def no_git(*args, **kwargs):
        pytest.fail("shipped eager baseline must not invoke Git")

    monkeypatch.setattr(subprocess, "check_output", no_git)
    restore, source_hash = _baseline_restore()
    assert callable(restore)
    assert restore.__name__ == "restore_universal_application"
    assert source_hash == BASELINE_SOURCE_SHA256


@pytest.mark.parametrize("missing", ["checkout", "git"])
def test_no_git_baseline_keeps_lazy_and_replica_courts(monkeypatch, capsys, missing):
    def unavailable(*args, **kwargs):
        if missing == "git":
            raise FileNotFoundError("git")
        raise subprocess.CalledProcessError(128, args[0], stderr=b"not a git repository")

    monkeypatch.setattr(subprocess, "check_output", unavailable)
    monkeypatch.setitem(globals(), "BASELINE_FIXTURE", BASELINE_FIXTURE.with_name("absent-eager-baseline.py.txt"))
    monkeypatch.delenv("LAZYBOOT_BOOT_REPORT", raising=False)
    calls = []
    measured = {
        "opening_revision": 1, "restored_revision": 1, "home_revision": 1,
        "agent_deferred_at_home": True, "map_deferred_at_home": True,
        "workshop_deferred_after_transport_identity": True,
        "canvas_deferred_at_home": True, "first_agent_physical_cells": 1,
        "home_ready_seconds": 1.0, "home_and_primary_agent_identity_ready_seconds": 2.0,
        "restore": {"physical_cells_read": 1}, "home_ready": {},
        "restore_roots": set(), "home_roots": set(),
    }

    def boot(manifest, restore, patch, *, home_frame=False):
        assert callable(restore)
        assert home_frame
        calls.append("lazy")
        return measured

    def replica(manifest, patch, expected):
        assert expected is measured
        calls.append("replica")
        return {"home_ready_seconds": 2.0}

    monkeypatch.setitem(globals(), "_boot", boot)
    monkeypatch.setitem(globals(), "_boot_replica_home", replica)
    test_large_store_cold_home_is_bounded_and_unrelated_relations_wait(
        {"synthetic_relation_roots": []}, monkeypatch,
    )
    assert calls == ["lazy", "replica"]
    output = capsys.readouterr().out
    assert f"SKIPPED paired eager baseline {BASELINE}" in output
    encoded = output.split("LAZYBOOT_MEASURED ", 1)[1]
    report = json.loads(encoded)
    assert report["baseline_status"] == "unavailable; paired eager timing skipped"
    assert report["before"] is None
    assert report["after"]["home_ready_seconds"] == 1.0
    assert report["replica_backend"]["home_ready_seconds"] == 2.0


@pytest.mark.parametrize("suffixes,value", [
    ((":revision", ":resolver-revision"), b"0"),
    ((":evaluated-at", ":resolver-evaluated-at"), b"0.0"),
])
def test_first_agent_open_uses_original_receipt_checks_and_failed_reads_retry(
    monkeypatch, suffixes, value,
):
    provider = _provider()
    store, built = application.build_universal_application(
        resolve_map_path(), key_provider=provider,
    )
    try:
        receipt = built.agent_body.body.creation_receipt_root
        original_cells = tuple(store.snapshot().cells[receipt + suffix]
                               for suffix in suffixes)
        store.commit(store.revision, replace=tuple(
            Cell(cell.id, cell.link0, cell.link1, value) for cell in original_cells
        ))
        _, lazy = application.restore_universal_application(
            resolve_map_path(), store, key_provider=provider, lazy=True,
        )
        field = object.__getattribute__(lazy, "agent_body")
        assert isinstance(field, DeferredRegistryField)
        assert field.group._values is None
        verified = application._project_application_agent_body
        calls = []

        def read(*args, **kwargs):
            calls.append(True)
            return verified(*args, **kwargs)

        monkeypatch.setattr(application, "_project_application_agent_body", read)
        with pytest.raises(InvalidCell, match="receipt"):
            lazy.agent_body
        assert calls
        assert field.group._values is None
        store.commit(store.revision, replace=original_cells)
        body = lazy.agent_body
        assert body.body.root_id == built.agent_body.body.root_id
        count = len(calls)
        assert lazy.agent_body is body
        assert len(calls) == count
    finally:
        _close_fixture_store(store)


def test_first_nested_scope_open_matches_eager_projection():
    provider = _provider()
    store, built = application.build_universal_application(
        resolve_map_path(), key_provider=provider,
    )
    try:
        _, lazy = application.restore_universal_application(
            resolve_map_path(), store, key_provider=provider, lazy=True,
        )
        home = application.project_universal_canvas(store, lazy)
        target = built.map.domains["models"]
        application.set_universal_scope(store, lazy, target, projected_canvas=home)
        opened = application.project_universal_canvas(store, lazy)
        assert opened["scope"]["current"] == target
        _, eager = application.restore_universal_application(
            resolve_map_path(), store, key_provider=provider,
        )
        restored = application.project_universal_canvas(store, eager)
        assert tuple(node["id"] for node in opened["nodes"]) == tuple(
            node["id"] for node in restored["nodes"]
        )
        assert opened["scope"] == restored["scope"]
    finally:
        _close_fixture_store(store)


def test_saved_nested_scope_waits_for_its_authorized_first_canvas_projection(monkeypatch):
    provider = _provider()
    store, built = application.build_universal_application(
        resolve_map_path(), key_provider=provider,
    )
    try:
        target = built.map.domains["models"]
        application.set_universal_scope(store, built, target)
        expected = application.project_universal_canvas(store, built)
        _, lazy = application.restore_universal_application(
            resolve_map_path(), store, key_provider=provider, lazy=True,
        )
        agent = object.__getattribute__(lazy, "agent_body")
        map_nodes = object.__getattribute__(lazy.map, "nodes")
        assert isinstance(agent, DeferredRegistryField) and agent.group._values is None
        assert isinstance(map_nodes, DeferredRegistryField) and map_nodes.group._values is None
        view = lazy.view_sessions[lazy.authorization.subject_root]
        assert application._read_view_scope_trail_structure(store.snapshot(), lazy, view)[-1] == target
        original_loader = lazy.lazy_scope_loader
        loads = []

        def load(scope, opening_view=None):
            loads.append(scope)
            return original_loader(scope, opening_view)

        object.__setattr__(lazy, "lazy_scope_loader", load)
        revision = store.revision
        with pytest.raises(AuthorizationDenied, match="unknown authenticated context"):
            application.project_universal_canvas(store, lazy, authentication_context=object())
        assert loads == []
        assert store.revision == revision
        opened = application.project_universal_canvas(store, lazy)
        assert loads == [target]
        assert opened["scope"] == expected["scope"]
        assert tuple(node["id"] for node in opened["nodes"]) == tuple(node["id"] for node in expected["nodes"])
        assert opened["selected"] == expected["selected"]
        assert opened["properties"] == expected["properties"]
    finally:
        _close_fixture_store(store)


def test_primary_transport_identity_does_not_hydrate_workshop_catalogue():
    provider = _provider()
    store, built = application.build_universal_application(resolve_map_path(), key_provider=provider)
    try:
        _, lazy = application.restore_universal_application(
            resolve_map_path(), store, key_provider=provider, lazy=True,
        )
        workshop = object.__getattribute__(lazy, "workshop_category_roots")
        assert workshop.group._values is None
        assert lazy.agent_body.session.root_id == built.agent_body.session.root_id
        assert workshop.group._values is None
        assert lazy.workshop_category_roots == built.workshop_category_roots
        assert workshop.group._values is not None
    finally:
        _close_fixture_store(store)
