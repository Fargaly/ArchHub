"""Process-boundary courts for the sealed Universal Cell cloud runtime."""
from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import threading


_RELATIONSHIP_ARN = (
    "arn:aws:kms:me-central-1:111122223333:"
    "key/11111111-1111-1111-1111-111111111111"
)
_COURT_ARN = (
    "arn:aws:kms:me-central-1:111122223333:"
    "key/22222222-2222-2222-2222-222222222222"
)
_SECRET_DSN = "postgresql://fixture.invalid/archhub?marker=never-log"


def _environment() -> dict[str, str]:
    return {
        "ARCHHUB_UNIVERSAL_POSTGRES_DSN": _SECRET_DSN,
        "ARCHHUB_UNIVERSAL_POSTGRES_AUTHORITY_ID": "archhub-production",
        "ARCHHUB_AWS_KMS_HMAC_KEYS": json.dumps(
            {
                "archhub.local.relationship-authority": {
                    "1": _RELATIONSHIP_ARN,
                },
                "archhub.local.court-attestation": {
                    "1": _COURT_ARN,
                },
            }
        ),
        "ARCHHUB_DYNAMODB_REVISION_WITNESS_TABLE": (
            "archhub-production-revision-witness"
        ),
        "HOST": "0.0.0.0",
        "PORT": "8482",
    }


class _AliveThread:
    def is_alive(self) -> bool:
        return True


def test_cloud_entrypoint_uses_one_public_cell_authority_and_drains_once():
    from nodelang import cloud_application_entrypoint as module
    from nodelang.map_import import PUBLIC_MAP_PATH

    events: list[object] = []
    stop = threading.Event()

    class Server:
        thread = _AliveThread()

        def start(self):
            events.append("start")
            stop.set()
            return self

        def close(self):
            events.append("close")

    def server_factory(configuration, **kwargs):
        events.append(("factory", configuration, kwargs))
        return Server()

    output = StringIO()
    result = module.run_cloud_application(
        _environment(),
        server_factory=server_factory,
        stop_event=stop,
        install_signal_handlers=False,
        output=output,
    )

    assert result == 0
    assert events[1:] == ["start", "close"]
    _, configuration, kwargs = events[0]
    assert configuration.authority_id == "archhub-production"
    assert kwargs == {
        "map_path": PUBLIC_MAP_PATH,
        "court_workspace_root": Path(module.__file__).resolve().parents[1],
    }
    rendered = output.getvalue()
    assert "started" in rendered
    assert "stopped" in rendered
    assert _SECRET_DSN not in rendered
    assert _RELATIONSHIP_ARN not in rendered


def test_cloud_entrypoint_fails_closed_without_rendering_error_or_secrets():
    from nodelang import cloud_application_entrypoint as module

    output = StringIO()

    def server_factory(configuration, **kwargs):
        del configuration, kwargs
        raise RuntimeError(f"provider rejected {_SECRET_DSN}")

    result = module.run_cloud_application(
        _environment(),
        server_factory=server_factory,
        install_signal_handlers=False,
        output=output,
    )

    assert result == 1
    assert output.getvalue() == "ARCHHUB_CLOUD_RUNTIME failed\n"
    assert _SECRET_DSN not in output.getvalue()


def test_cloud_entrypoint_closes_constructed_server_when_start_fails():
    from nodelang import cloud_application_entrypoint as module

    events: list[str] = []

    class Server:
        thread = None

        def start(self):
            events.append("start")
            raise RuntimeError(f"startup leaked {_COURT_ARN}")

        def close(self):
            events.append("close")

    result = module.run_cloud_application(
        _environment(),
        server_factory=lambda configuration, **kwargs: Server(),
        install_signal_handlers=False,
        output=StringIO(),
    )

    assert result == 1
    assert events == ["start", "close"]


def test_cloud_entrypoint_installs_and_restores_term_and_interrupt_handlers():
    from nodelang import cloud_application_entrypoint as module

    stop = threading.Event()

    class Signals:
        SIGTERM = 15
        SIGINT = 2

        def __init__(self):
            self.handlers = {
                self.SIGTERM: "previous-term",
                self.SIGINT: "previous-int",
            }
            self.calls = []

        def getsignal(self, number):
            return self.handlers[number]

        def signal(self, number, handler):
            self.calls.append((number, handler))
            self.handlers[number] = handler

    signals = Signals()

    class Server:
        thread = _AliveThread()

        def start(self):
            signals.handlers[signals.SIGTERM](signals.SIGTERM, None)
            return self

        def close(self):
            pass

    result = module.run_cloud_application(
        _environment(),
        server_factory=lambda configuration, **kwargs: Server(),
        stop_event=stop,
        signal_module=signals,
        output=StringIO(),
    )

    assert result == 0
    assert stop.is_set()
    assert signals.calls[-2:] == [
        (signals.SIGTERM, "previous-term"),
        (signals.SIGINT, "previous-int"),
    ]


def test_cloud_entrypoint_does_not_delegate_to_the_legacy_local_launcher():
    source = (
        Path(__file__).resolve().parents[1]
        / "nodelang"
        / "cloud_application_entrypoint.py"
    ).read_text(encoding="utf-8")

    assert "application_server.main" not in source
    assert "server.py" not in source
    assert "browser_session_token" not in source
    assert "ARCHHUB_STATE_PATH" not in source
