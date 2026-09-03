"""Physical, non-authoritative host bridge for released BABOOM model adapters.

The broker deliberately has no CellStore, Work queue, session ledger, or policy
state.  The Universal Cell graph owns request, approval, grant, proposal, and
receipt.  This module receives one already-authorized, bounded invocation and
returns transient provider output for the caller to reconcile through that
existing graph path.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence


_MAX_TASK_BYTES = 64 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024
_PROCESS_READ_CHUNK_BYTES = 4 * 1024
_MAX_MODEL_BYTES = 160
_MAX_READY_MODELS = 32
_ALLOWED_DATA_CLASSES = frozenset({
    "public-text", "internal-text", "confidential-text",
})
_LOCAL_ONLY_DATA_CLASS = "confidential-text"
_REVIEW_FIELDS = frozenset({"summary", "next_actions", "risks", "uncertainty"})


@dataclass(frozen=True, slots=True)
class HostProcessResult:
    """Transient result from one child process or HTTP operation."""

    ok: bool
    stdout: bytes = b""
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class ModelExecutionResult:
    """Transient, bounded result to settle through the graph receipt path."""

    outcome: str
    output_digest: str
    output_bytes: int
    error_code: str
    proposal_payload: dict[str, object] | None = None


class ModelExecutionHost(Protocol):
    """Physical host operations; implementations must not persist semantic state."""

    def run_process(
        self,
        command: Sequence[str],
        *,
        prompt: bytes,
        cwd: Path,
        timeout_seconds: float,
    ) -> HostProcessResult:
        ...

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> HostProcessResult:
        ...

    def get_json(
        self,
        url: str,
        *,
        timeout_seconds: float,
    ) -> HostProcessResult:
        ...


class OpenRouterCredentialResolver(Protocol):
    """Resolve a live key outside the graph and never serialize it."""

    def openrouter_api_key(self) -> str | None:
        ...


class EnvironmentOpenRouterCredentialResolver:
    """Read the caller-provisioned key only at the physical boundary."""

    def openrouter_api_key(self) -> str | None:
        value = os.environ.get("OPENROUTER_API_KEY")
        return value if value else None


class LocalModelExecutionHost:
    """Default subprocess and HTTP implementation for one broker invocation."""

    @staticmethod
    def _close_stream(stream: object) -> None:
        try:
            close = getattr(stream, "close")
            close()
        except (AttributeError, OSError, ValueError):
            pass

    @classmethod
    def _stop_process(cls, process: subprocess.Popen[bytes]) -> None:
        """Stop only the child started for this exact broker invocation."""
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, OSError):
            try:
                process.kill()
            except OSError:
                pass
        cls._close_stream(process.stdin)
        cls._close_stream(process.stdout)

    def run_process(
        self,
        command: Sequence[str],
        *,
        prompt: bytes,
        cwd: Path,
        timeout_seconds: float,
    ) -> HostProcessResult:
        try:
            process = subprocess.Popen(
                tuple(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=str(cwd),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return HostProcessResult(False, error_code="provider_unavailable")
        stdout = bytearray()
        output_too_large = threading.Event()
        stream_error = threading.Event()

        def write_prompt() -> None:
            stream = process.stdin
            if stream is None:
                stream_error.set()
                return
            try:
                stream.write(prompt)
                stream.close()
            except (BrokenPipeError, OSError, ValueError):
                # A provider may finish before consuming all stdin. Its return
                # code decides the outcome; the task never leaves this process.
                pass

        def read_stdout() -> None:
            stream = process.stdout
            if stream is None:
                stream_error.set()
                return
            try:
                while True:
                    chunk = stream.read(_PROCESS_READ_CHUNK_BYTES)
                    if not chunk:
                        return
                    remaining = _MAX_OUTPUT_BYTES - len(stdout)
                    if remaining > 0:
                        stdout.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        output_too_large.set()
                        self._stop_process(process)
                        return
            except (OSError, ValueError):
                stream_error.set()

        writer = threading.Thread(target=write_prompt, daemon=True)
        reader = threading.Thread(target=read_stdout, daemon=True)
        writer.start()
        reader.start()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self._stop_process(process)
            writer.join(timeout=1.0)
            reader.join(timeout=1.0)
            return HostProcessResult(False, bytes(stdout), "provider_timeout")
        writer.join(timeout=1.0)
        reader.join(timeout=1.0)
        if output_too_large.is_set():
            return HostProcessResult(False, bytes(stdout), "output_too_large")
        if stream_error.is_set():
            return HostProcessResult(False, bytes(stdout), "provider_failed")
        if process.returncode != 0:
            return HostProcessResult(False, bytes(stdout), "provider_failed")
        return HostProcessResult(True, bytes(stdout))

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> HostProcessResult:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded,
            method="POST",
            headers=dict(headers),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(_MAX_OUTPUT_BYTES + 1)
        except Exception:
            return HostProcessResult(False, error_code="provider_unavailable")
        if len(body) > _MAX_OUTPUT_BYTES:
            return HostProcessResult(False, body[:_MAX_OUTPUT_BYTES], "output_too_large")
        return HostProcessResult(True, body)

    def get_json(
        self,
        url: str,
        *,
        timeout_seconds: float,
    ) -> HostProcessResult:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(_MAX_OUTPUT_BYTES + 1)
        except Exception:
            return HostProcessResult(False, error_code="provider_unavailable")
        if len(body) > _MAX_OUTPUT_BYTES:
            return HostProcessResult(False, body[:_MAX_OUTPUT_BYTES], "output_too_large")
        return HostProcessResult(True, body)


def _bounded_text(value: object, label: str, limit: int) -> str:
    if type(value) is not str:
        raise ValueError("%s is invalid" % label)
    normalized = value.strip()
    if not normalized or len(normalized.encode("utf-8")) > limit:
        raise ValueError("%s exceeds its bound" % label)
    return normalized


def _failed(raw: bytes, error_code: str) -> ModelExecutionResult:
    return ModelExecutionResult(
        "failed",
        hashlib.sha256(raw).hexdigest(),
        len(raw),
        error_code,
    )


def _extract_provider_text(provider: str, raw: bytes) -> str | None:
    if len(raw) > _MAX_OUTPUT_BYTES:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip()
    if not text:
        return None
    if provider not in {"claude", "gemini", "openrouter", "local"}:
        return text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(payload, Mapping):
        return text
    if provider == "openrouter":
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
            content = message.get("content") if isinstance(message, Mapping) else None
            if type(content) is str:
                return content.strip() or None
    if provider == "local":
        response = payload.get("response")
        if type(response) is str:
            return response.strip() or None
    for key in ("result", "text", "response"):
        value = payload.get(key)
        if type(value) is str:
            return value.strip() or None
    return text


def _parse_review_payload(provider: str, raw: bytes) -> dict[str, object] | None:
    text = _extract_provider_text(provider, raw)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or set(payload) != _REVIEW_FIELDS:
        return None
    summary = payload.get("summary")
    actions = payload.get("next_actions")
    risks = payload.get("risks")
    uncertainty = payload.get("uncertainty")
    if (
        type(summary) is not str
        or not summary.strip()
        or len(summary.strip().encode("utf-8")) > 1_200
        or not isinstance(actions, list)
        or not 1 <= len(actions) <= 8
        or not isinstance(risks, list)
        or len(risks) > 4
        or type(uncertainty) not in (int, float)
        or not math.isfinite(float(uncertainty))
        or not 0.0 <= float(uncertainty) <= 1.0
    ):
        return None
    normalized_actions: list[str] = []
    normalized_risks: list[str] = []
    for values, output in ((actions, normalized_actions), (risks, normalized_risks)):
        for value in values:
            if type(value) is not str or not value.strip():
                return None
            text_value = value.strip()
            if len(text_value.encode("utf-8")) > 280:
                return None
            output.append(text_value)
    return {
        "summary": summary.strip(),
        "next_actions": normalized_actions,
        "risks": normalized_risks,
        "uncertainty": float(uncertainty),
    }


class ModelExecutionBroker:
    """Translate a graph-released adapter location into one bounded host call."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        host: ModelExecutionHost | None = None,
        credential_resolver: OpenRouterCredentialResolver | None = None,
        executables: Mapping[str, str] | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise ValueError("model broker workspace root is unavailable")
        if type(timeout_seconds) not in (int, float) or not 1.0 <= float(timeout_seconds) <= 900.0:
            raise ValueError("model broker timeout is invalid")
        self._workspace_root = root
        self._host = host or LocalModelExecutionHost()
        self._credential_resolver = (
            credential_resolver or EnvironmentOpenRouterCredentialResolver()
        )
        self._executables = dict(executables or {})
        self._timeout_seconds = float(timeout_seconds)

    def _executable(self, location: str) -> str | None:
        configured = self._executables.get(location)
        if configured:
            return configured
        candidates = {
            "local-cli:codex": (str(Path.home() / ".codex" / ".sandbox-bin" / "codex.exe"), "codex.exe", "codex"),
            "local-cli:claude": (str(Path.home() / ".local" / "bin" / "claude.exe"), "claude.exe", "claude"),
            "local-cli:gemini": (str(Path(os.environ.get("APPDATA", "")) / "npm" / "gemini.cmd"), "gemini.exe", "gemini.cmd", "gemini"),
        }.get(location, ())
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file():
                return str(path)
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return None

    def model_provider_readiness(self) -> dict[str, dict[str, object]]:
        """Return transient host readiness without invoking a model or persisting state."""

        readiness: dict[str, dict[str, object]] = {}
        for provider, location in (
            ("gpt", "local-cli:codex"),
            ("claude", "local-cli:claude"),
            ("gemini", "local-cli:gemini"),
        ):
            executable = self._executable(location)
            readiness[provider] = {
                "location": location,
                "state": "executable-discovered" if executable else "provider-unavailable",
                "evidence": "local executable discovery only",
                "execution_authority": "requires graph request, approval, and one-use grant",
            }

        readiness["openrouter"] = {
            "location": "network:openrouter",
            "state": (
                "credential-configured"
                if self._credential_resolver.openrouter_api_key()
                else "provider-unavailable"
            ),
            "evidence": "credential presence only; no credential material or network request exposed",
            "execution_authority": "requires graph request, approval, and one-use grant",
        }

        local = self._host.get_json(
            "http://127.0.0.1:11434/api/tags",
            timeout_seconds=min(self._timeout_seconds, 3.0),
        )
        local_entry: dict[str, object] = {
            "location": "local-http:ollama",
            "state": "provider-unavailable",
            "evidence": "local model endpoint did not return a bounded catalog",
            "execution_authority": "requires graph request, approval, and one-use grant",
        }
        if local.ok:
            try:
                payload = json.loads(local.stdout.decode("utf-8"))
                models = payload.get("models") if isinstance(payload, Mapping) else None
                names = [
                    item["name"].strip()
                    for item in models if isinstance(item, Mapping)
                    and type(item.get("name")) is str and item["name"].strip()
                ] if isinstance(models, list) else []
            except (UnicodeDecodeError, json.JSONDecodeError):
                names = []
            if len(names) <= _MAX_READY_MODELS:
                local_entry.update({
                    "state": "endpoint-available",
                    "evidence": "bounded local Ollama model catalog",
                    "models": names,
                })
        readiness["local"] = local_entry
        return readiness

    def execute(
        self,
        *,
        provider: str,
        location: str,
        model: str,
        data_class: str,
        task: str,
    ) -> ModelExecutionResult:
        """Run one graph-authorized provider attempt without storing its output."""
        try:
            provider = _bounded_text(provider, "provider", 80)
            location = _bounded_text(location, "provider location", 160)
            model = _bounded_text(model, "model", _MAX_MODEL_BYTES)
            task = _bounded_text(task, "model task", _MAX_TASK_BYTES)
        except ValueError:
            return _failed(b"", "invalid_invocation")
        if data_class not in _ALLOWED_DATA_CLASSES:
            return _failed(b"", "data_class_denied")
        if data_class == _LOCAL_ONLY_DATA_CLASS and location != "local-http:ollama":
            return _failed(b"", "data_class_denied")
        prompt = (
            task
            + "\n\nReturn only one JSON object with summary, next_actions, risks, and uncertainty."
        ).encode("utf-8")
        result: HostProcessResult
        if location == "local-cli:codex" and provider == "gpt":
            executable = self._executable(location)
            if not executable:
                return _failed(b"", "provider_unavailable")
            result = self._host.run_process(
                (
                    executable, "exec", "--ephemeral", "--ignore-user-config",
                    "--sandbox", "read-only", "--color", "never", "-m", model,
                    "-C", str(self._workspace_root), "-",
                ),
                prompt=prompt,
                cwd=self._workspace_root,
                timeout_seconds=self._timeout_seconds,
            )
        elif location == "local-cli:claude" and provider == "claude":
            executable = self._executable(location)
            if not executable:
                return _failed(b"", "provider_unavailable")
            result = self._host.run_process(
                (
                    executable, "--bare", "-p", "--output-format", "json",
                    "--permission-mode", "plan", "--allowed-tools", "Read,Grep,Glob",
                    "--no-session-persistence", "--model", model,
                ),
                prompt=prompt,
                cwd=self._workspace_root,
                timeout_seconds=self._timeout_seconds,
            )
        elif location == "local-cli:gemini" and provider == "gemini":
            executable = self._executable(location)
            if not executable:
                return _failed(b"", "provider_unavailable")
            result = self._host.run_process(
                (
                    executable, "--prompt", "", "--output-format", "json",
                    "--approval-mode", "plan", "--model", model,
                ),
                prompt=prompt,
                cwd=self._workspace_root,
                timeout_seconds=self._timeout_seconds,
            )
        elif location == "network:openrouter" and provider == "openrouter":
            key = self._credential_resolver.openrouter_api_key()
            if not key:
                return _failed(b"", "provider_unavailable")
            result = self._host.post_json(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
                payload={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt.decode("utf-8")}],
                    "temperature": 0.0,
                    "max_tokens": 1200,
                },
                timeout_seconds=self._timeout_seconds,
            )
        elif location == "local-http:ollama" and provider == "local":
            result = self._host.post_json(
                "http://127.0.0.1:11434/api/generate",
                headers={"Content-Type": "application/json"},
                payload={
                    "model": model,
                    "prompt": prompt.decode("utf-8"),
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 1200},
                },
                timeout_seconds=self._timeout_seconds,
            )
        else:
            return _failed(b"", "provider_binding_denied")
        raw = result.stdout[:_MAX_OUTPUT_BYTES]
        if not result.ok:
            return _failed(raw, result.error_code or "provider_failed")
        proposal = _parse_review_payload(provider, raw)
        if proposal is None:
            return _failed(raw, "invalid_model_output")
        return ModelExecutionResult(
            "succeeded",
            hashlib.sha256(raw).hexdigest(),
            len(raw),
            "",
            proposal,
        )


__all__ = [
    "EnvironmentOpenRouterCredentialResolver",
    "HostProcessResult",
    "LocalModelExecutionHost",
    "ModelExecutionBroker",
    "ModelExecutionHost",
    "ModelExecutionResult",
    "OpenRouterCredentialResolver",
]
