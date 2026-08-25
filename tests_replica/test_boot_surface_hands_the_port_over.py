"""The boot surface must stop answering once it hands the port over.

Courting the absence. Every part behaved correctly on its own: the page
polled, the endpoint answered, the handover closed the listening socket.
What nobody could see in review is that an HTTP/1.1 connection opened
BEFORE the handover survives it, so the boot page kept being served by a
server that no longer owned the port -- and, seeing done=true forever,
reloaded itself into a spin instead of reaching the canvas.
"""
from __future__ import annotations

import http.client
import threading

from nodelang.clean_boot_surface import BootSurface


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_boot_response_does_not_keep_the_connection_alive() -> None:
    port = _free_port()
    surface = BootSurface("127.0.0.1", port).start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/api/universal/boot")
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        assert response.getheader("Connection", "").lower() == "close", (
            "a kept-alive boot connection outlives the handover"
        )
        connection.close()
    finally:
        surface.hand_over()


def test_a_connection_opened_before_handover_cannot_be_reused_after() -> None:
    port = _free_port()
    surface = BootSurface("127.0.0.1", port).start()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/api/universal/boot")
    connection.getresponse().read()

    done = threading.Event()

    def hand_over() -> None:
        surface.hand_over()
        done.set()

    worker = threading.Thread(target=hand_over)
    worker.start()
    worker.join(timeout=20)
    assert done.is_set(), "the handover never completed"

    # The port is free: nothing is left answering on it.
    raised = False
    try:
        probe = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        probe.request("GET", "/api/universal/boot")
        probe.getresponse().read()
    except OSError:
        raised = True
    assert raised, "the boot surface still answers after handing the port over"
