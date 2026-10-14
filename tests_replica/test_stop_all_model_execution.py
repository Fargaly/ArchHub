import threading
import time

import pytest

from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_model_execution import read_model_execution_receipt

from tests_replica.test_workshop_model_turn_guarantees import (
    ENDPOINT,
    EXECUTE,
    _Broker,
    _approved,
    _request,
)


class _BlockingBroker(_Broker):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, *, free_only, reasoning_effort, max_output_tokens, **request):
        self.started.set()
        assert self.release.wait(10), "provider double was not released"
        return super().execute(
            free_only=free_only,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
            **request,
        )


def test_stop_resume_refuses_second_model_dispatch_until_first_drains_and_fences_old_result(tmp_path):
    broker = _BlockingBroker()
    rig = _approved(tmp_path, broker, "stop-all-model-drain")
    sent = []
    original = rig.host._client.request

    def record(method, path, *args, **kwargs):
        if path == EXECUTE:
            sent.append(dict(args[0] if args else kwargs.get("body", {})))
        return original(method, path, *args, **kwargs)

    rig.host._client.request = record
    response = {}

    def execute():
        response["value"] = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})

    thread = threading.Thread(target=execute, daemon=True)
    try:
        thread.start()
        assert broker.started.wait(10)
        deadline = time.time() + 10
        while not sent and time.time() < deadline:
            time.sleep(0.01)
        assert sent

        rig.server.halt_all()
        assert rig.server.is_halted()
        rig.server.resume_all()
        assert not rig.server.is_halted()
        with pytest.raises(AuthorizationDenied, match="busy|shutting down"):
            rig.server._execute_universal_model_request(None, sent[0], False, None)

        broker.release.set()
        thread.join(10)
        assert not thread.is_alive()
        status, settled = response["value"]
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["reconciled"] is False
        assert "proposal" not in settled

        receipt = read_model_execution_receipt(
            rig.server.universal_store.snapshot(),
            rig.server.universal_registry.baboom_model_execution_protocol,
            rig.server.universal_registry.adapter_protocol,
            settled["receipt"],
        )
        assert receipt.outcome == "failed"
        assert receipt.error_code == "stopped_after_send_uncertain"
        halted = rig.server.check_halted_write(rig.prepared["delegation"])
        assert halted is not None and halted["details"]["status"] == "uncertain"

        calls = len(broker.calls)
        _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert len(broker.calls) == calls
    finally:
        broker.release.set()
        thread.join(1)
        rig.server.close()
