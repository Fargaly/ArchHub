from __future__ import annotations

from pathlib import Path

from personal_brain import server


class _Socket:
    def __enter__(self) -> "_Socket":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_http_runtime_services_start_only_after_listener_binds(monkeypatch) -> None:
    attempts = 0
    starts: list[tuple[object, str | None]] = []
    bound_server = object()

    def connect(address, timeout):
        nonlocal attempts
        attempts += 1
        assert address == ("127.0.0.1", 8473)
        assert timeout == 0.2
        if attempts == 1:
            raise OSError("not bound")
        return _Socket()

    monkeypatch.setattr(server.socket, "create_connection", connect)
    monkeypatch.setattr(
        server,
        "_start_http_runtime_services",
        lambda instance, owner: starts.append((instance, owner)),
    )

    thread = server._start_http_runtime_services_after_bind(
        bound_server,
        owner="founder",
        host="127.0.0.1",
        port=8473,
        wait_timeout_s=0.2,
        poll_interval_s=0.01,
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert attempts == 2
    assert starts == [(bound_server, "founder")]


def test_http_runtime_services_stay_off_when_listener_never_binds(
    monkeypatch,
) -> None:
    starts: list[tuple[object, str | None]] = []

    def connect(address, timeout):
        raise OSError("not bound")

    monkeypatch.setattr(server.socket, "create_connection", connect)
    monkeypatch.setattr(
        server,
        "_start_http_runtime_services",
        lambda instance, owner: starts.append((instance, owner)),
    )

    thread = server._start_http_runtime_services_after_bind(
        object(),
        owner="founder",
        host="127.0.0.1",
        port=8473,
        wait_timeout_s=0.03,
        poll_interval_s=0.01,
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert starts == []


def test_http_runtime_services_can_be_suspended_by_operator_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("BRAIN_HTTP_RUNTIME_SERVICES", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    marker = tmp_path / "ArchHub" / "brain" / "ambient-runtime.suspended"
    marker.parent.mkdir(parents=True)
    marker.write_text("protected CAD production", encoding="utf-8")

    assert server._http_runtime_services_suspended() == (True, str(marker))


def test_http_runtime_services_explicit_enable_overrides_marker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BRAIN_HTTP_RUNTIME_SERVICES", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    marker = tmp_path / "ArchHub" / "brain" / "ambient-runtime.suspended"
    marker.parent.mkdir(parents=True)
    marker.write_text("protected CAD production", encoding="utf-8")

    assert server._http_runtime_services_suspended() == (False, "")
