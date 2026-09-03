"""Courts for the non-authoritative physical BABOOM model broker."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import nodelang.model_execution_broker as broker_module
from nodelang.model_execution_broker import (
    HostProcessResult,
    LocalModelExecutionHost,
    ModelExecutionBroker,
)


def _review() -> bytes:
    return json.dumps({
        "summary": "Review the sealed Workshop context before proposing.",
        "next_actions": ["Validate the required plan."],
        "risks": ["Do not execute an unapproved effect."],
        "uncertainty": 0.25,
    }).encode("utf-8")


class _Host:
    def __init__(self, result: HostProcessResult) -> None:
        self.result = result
        self.process_calls: list[dict[str, object]] = []
        self.http_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def run_process(self, command, *, prompt, cwd, timeout_seconds):
        self.process_calls.append({
            "command": tuple(command), "prompt": prompt, "cwd": cwd,
            "timeout_seconds": timeout_seconds,
        })
        return self.result

    def post_json(self, url, *, headers, payload, timeout_seconds):
        self.http_calls.append({
            "url": url, "headers": dict(headers), "payload": dict(payload),
            "timeout_seconds": timeout_seconds,
        })
        return self.result

    def get_json(self, url, *, timeout_seconds):
        self.get_calls.append({"url": url, "timeout_seconds": timeout_seconds})
        return self.result


class _Credentials:
    def __init__(self, key: str | None) -> None:
        self.key = key

    def openrouter_api_key(self) -> str | None:
        return self.key


def _broker(tmp_path: Path, host: _Host, **kwargs) -> ModelExecutionBroker:
    return ModelExecutionBroker(
        workspace_root=tmp_path,
        host=host,
        executables={
            "local-cli:codex": "codex-test.exe",
            "local-cli:claude": "claude-test.exe",
            "local-cli:gemini": "gemini-test.cmd",
        },
        **kwargs,
    )


def test_broker_runs_exact_graph_released_codex_contract_without_task_argv(tmp_path):
    host = _Host(HostProcessResult(True, _review()))
    result = _broker(tmp_path, host).execute(
        provider="gpt",
        location="local-cli:codex",
        model="gpt-5",
        data_class="internal-text",
        task="Review the bounded Work plan.",
    )

    assert result.outcome == "succeeded"
    assert result.proposal_payload == json.loads(_review())
    assert result.output_digest == hashlib.sha256(_review()).hexdigest()
    assert result.output_bytes == len(_review())
    assert len(host.process_calls) == 1
    call = host.process_calls[0]
    assert call["command"] == (
        "codex-test.exe", "exec", "--ephemeral", "--ignore-user-config",
        "--sandbox", "read-only", "--color", "never", "-m", "gpt-5",
        "-C", str(tmp_path.resolve()), "-",
    )
    assert b"Review the bounded Work plan." in call["prompt"]
    assert all("Review the bounded" not in item for item in call["command"])


def test_broker_rejects_provider_location_and_confidentiality_drift_before_host_call(tmp_path):
    host = _Host(HostProcessResult(True, _review()))
    broker = _broker(tmp_path, host)

    binding = broker.execute(
        provider="gpt",
        location="local-cli:claude",
        model="gpt-5",
        data_class="internal-text",
        task="Review the bounded Work plan.",
    )
    confidential = broker.execute(
        provider="openrouter",
        location="network:openrouter",
        model="openrouter/free",
        data_class="confidential-text",
        task="Review the bounded Work plan.",
    )

    assert binding.error_code == "provider_binding_denied"
    assert confidential.error_code == "data_class_denied"
    assert not host.process_calls
    assert not host.http_calls


def test_broker_normalizes_network_output_without_persisting_openrouter_credential(tmp_path):
    response = json.dumps({
        "choices": [{"message": {"content": _review().decode("utf-8")}}],
    }).encode("utf-8")
    host = _Host(HostProcessResult(True, response))
    broker = _broker(
        tmp_path,
        host,
        credential_resolver=_Credentials("live-key-not-for-graph"),
    )

    result = broker.execute(
        provider="openrouter",
        location="network:openrouter",
        model="openrouter/free",
        data_class="internal-text",
        task="Review the bounded Work plan.",
    )

    assert result.outcome == "succeeded"
    assert result.proposal_payload == json.loads(_review())
    assert len(host.http_calls) == 1
    call = host.http_calls[0]
    assert call["headers"]["Authorization"] == "Bearer live-key-not-for-graph"
    assert call["payload"]["messages"][0]["content"].startswith(
        "Review the bounded Work plan."
    )
    assert "live-key-not-for-graph" not in json.dumps(result.__dict__ if hasattr(result, "__dict__") else {
        "outcome": result.outcome,
        "output_digest": result.output_digest,
        "output_bytes": result.output_bytes,
        "error_code": result.error_code,
        "proposal_payload": result.proposal_payload,
    })


def test_broker_returns_a_redacted_failed_receipt_material_for_invalid_or_failed_output(tmp_path):
    invalid_host = _Host(HostProcessResult(True, b"not valid json"))
    invalid = _broker(tmp_path, invalid_host).execute(
        provider="local",
        location="local-http:ollama",
        model="qwen3:8b",
        data_class="confidential-text",
        task="Review the bounded Work plan.",
    )
    failed_output = b"provider diagnostic that must not be persisted"
    failed_host = _Host(HostProcessResult(False, failed_output, "provider_timeout"))
    failed = _broker(tmp_path, failed_host).execute(
        provider="gemini",
        location="local-cli:gemini",
        model="gemini-2.5-pro",
        data_class="internal-text",
        task="Review the bounded Work plan.",
    )

    assert invalid.outcome == "failed"
    assert invalid.error_code == "invalid_model_output"
    assert invalid.output_digest == hashlib.sha256(b"not valid json").hexdigest()
    assert invalid.proposal_payload is None
    assert failed.outcome == "failed"
    assert failed.error_code == "provider_timeout"
    assert failed.output_digest == hashlib.sha256(failed_output).hexdigest()
    assert failed.proposal_payload is None


def test_broker_readiness_observes_hosts_without_invoking_any_model(tmp_path):
    catalog = json.dumps({"models": [{"name": "qwen3:8b"}]}).encode("utf-8")
    host = _Host(HostProcessResult(True, catalog))
    readiness = _broker(
        tmp_path,
        host,
        credential_resolver=_Credentials(None),
    ).model_provider_readiness()

    assert readiness["gpt"]["state"] == "executable-discovered"
    assert readiness["claude"]["state"] == "executable-discovered"
    assert readiness["gemini"]["state"] == "executable-discovered"
    assert readiness["openrouter"]["state"] == "provider-unavailable"
    assert readiness["local"] == {
        "location": "local-http:ollama",
        "state": "endpoint-available",
        "evidence": "bounded local Ollama model catalog",
        "execution_authority": "requires graph request, approval, and one-use grant",
        "models": ["qwen3:8b"],
    }
    assert host.get_calls == [{
        "url": "http://127.0.0.1:11434/api/tags", "timeout_seconds": 3.0,
    }]
    assert not host.process_calls
    assert not host.http_calls


def test_local_host_stops_a_child_when_stdout_exceeds_its_memory_ceiling(monkeypatch, tmp_path):
    class _Process:
        def __init__(self):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(
                b"x" * (broker_module._MAX_OUTPUT_BYTES + 1)
            )
            self.returncode = 0
            self.terminated = False

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

    process = _Process()
    monkeypatch.setattr(broker_module.subprocess, "Popen", lambda *args, **kwargs: process)

    result = LocalModelExecutionHost().run_process(
        ("provider.exe", "--read-only"),
        prompt=b"sealed task",
        cwd=tmp_path,
        timeout_seconds=10.0,
    )

    assert result.ok is False
    assert result.error_code == "output_too_large"
    assert len(result.stdout) == broker_module._MAX_OUTPUT_BYTES
    assert process.terminated is True
