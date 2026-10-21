from __future__ import annotations

import json
import hashlib

from nodelang import model_router
from nodelang import native_inbox_recovery
from nodelang import private_root_grants
from nodelang import universal_application
from nodelang import workspace_roots_catalogue as roots
from nodelang.cell_brain_secrets import admit_secret
from nodelang.cell_model_providers import register_provider, registered
from nodelang.native_workshop_execution import native_material_from_values
from nodelang.universal_cell import CellStore
from tests_replica.test_workspace_root_write_admission import _Store, _entry, _registry, graph_digest
from tests_replica.test_workspace_roots_catalogue import _Key


EXPECTED_RUNTIMES = (
    "claude",
    "codex",
    "gemini",
    "opencode",
    "antigravity",
    "cursor",
    "windsurf",
    "zed",
    "aider",
)


def test_gov_eq_registered_workspace_root_is_open_to_every_runtime(tmp_path, monkeypatch):
    folder = tmp_path / "client-a"
    folder.mkdir()
    key = _Key()
    files = _registry(tmp_path, key, [_entry(folder, writers=("claude",))])
    signed = json.loads(files["snapshot_path"].read_text(encoding="utf-8"))
    body = {key: value for key, value in signed.items() if key != "signature"}
    monkeypatch.setattr(
        roots,
        "verified_graph_state",
        lambda: {
            "purpose": "archhub.workspace-roots-state/v1",
            "graph_id": "court",
            "request_id": "r",
            "nonce": "0" * 32,
            "revision": 1,
            "registry_digest": graph_digest(body),
        },
    )

    for runtime in ("claude", "codex", "gemini", "a-runtime-not-yet-known"):
        container, digest, entry = roots.root_bound_registration(
            "workspace-roots/client-a/a.md",
            runtime=runtime,
            verifier=_Store(key),
            **files,
        )
        assert container == "workspace-root:client-a"
        assert digest
        assert entry["id"] == "client-a"


def test_gov_eq_runtime_catalogues_share_one_open_runtime_constant():
    assert roots.OPEN_AGENT_RUNTIMES == EXPECTED_RUNTIMES
    assert private_root_grants._RUNTIMES == frozenset(EXPECTED_RUNTIMES)
    assert native_inbox_recovery.NATIVE_RUNTIMES == frozenset(EXPECTED_RUNTIMES)
    assert tuple(runtime for runtime, _label in universal_application._HARNESS_AGENT_RUNTIMES) == EXPECTED_RUNTIMES


def test_gov_eq_native_work_material_accepts_non_claude_runtime():
    inputs = {
        "runtime": "codex",
        "model": "codex-local",
        "data_class": "public-text",
        "files": [
            {
                "path": "example.py",
                "content": "value = 1\n",
                "sha256": hashlib.sha256(b"value = 1\n").hexdigest(),
            }
        ],
        "artifact_name": "repair.patch",
        "limits": {
            "max_turns": 1,
            "max_processes": 1,
            "max_input_bytes": 4096,
            "max_output_bytes": 4096,
            "max_event_bytes": 1024,
            "max_events": 8,
            "max_process_bytes": 1024 * 1024,
            "startup_timeout_seconds": 5,
            "turn_timeout_seconds": 5,
            "lifetime_seconds": 20,
            "stop_timeout_seconds": 5,
        },
    }
    requirements = {
        "acceptance_criteria": [
            {"criterion": "The patch is public text", "verification": "Inspect the patch"}
        ]
    }

    material, raw = native_material_from_values(
        inputs,
        requirements,
        title="Repair",
        description="Return a patch.",
    )

    assert material["runtime"] == "codex"
    assert json.loads(raw)["runtime"] == "codex"


def test_gov_eq_provider_registration_is_open_once_key_is_in_custody():
    store = CellStore()
    admit_secret(
        store,
        name="mistral",
        reference="op://archhub/models/mistral",
        custody="operator-vault",
    )

    register_provider(store, provider="mistral", key_entry_name="mistral")

    assert registered(store.snapshot()) == ("mistral",)


def test_gov_eq_model_router_routes_anthropic_and_all_local_clis(monkeypatch):
    sent = []

    class Answer:
        headers = {"Content-Type": "application/json"}

        def read(self):
            return json.dumps(
                {
                    "id": "msg_1",
                    "content": [{"type": "text", "text": "anthropic ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def opener(request, timeout):
        sent.append(request)
        return Answer()

    answer = model_router.route_chat(
        "anthropic-api/claude-sonnet-4.5",
        [{"role": "system", "content": "Be terse"}, {"role": "user", "content": "hi"}],
        opener=opener,
        environ={},
        secrets_loader=lambda name: "a" * 40 if name == "anthropic" else "",
        cloud_session=None,
    )

    request = sent[-1]
    body = json.loads(request.data.decode("utf-8"))
    assert answer["family"] == "anthropic"
    assert answer["text"] == "anthropic ok"
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    headers = {key.casefold(): value for key, value in request.headers.items()}
    assert headers["x-api-key"] == "a" * 40
    assert headers["anthropic-version"] == "2023-06-01"
    assert body["system"] == "Be terse"
    assert body["model"] == "claude-sonnet-4.5"

    for assistant in ("claude", "codex", "gemini", "opencode", "antigravity", "cursor"):
        route = model_router.resolve_model_route("local-cli/%s" % assistant)
        assert route.family == "local-cli"
        assert route.url == "local-cli:" + assistant

    assert model_router._unverified_reason("codex", lambda _route: "999.0.0").startswith(
        "not verified on this machine"
    )
