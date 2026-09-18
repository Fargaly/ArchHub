"""Discovery answers while the canvas holds the lock, and says what it could not read.

2026-09-18: the founder's Studio picker sat on "Discovering models from connected
providers..." and "Discovering open agent sessions..." and never filled in. Measured
on his machine: the catalogue read itself takes 2.71s, and /api/universal/models took
the graph mutation lock before it started -- a lock one canvas projection on his graph
holds for 4.3s. His cloud sign-in had expired since 2026-09-13 and the cloud group drew
nothing at all, so the one thing he could do about it was never on screen.

The production handler runs here over a real socket. No graph, provider, or network.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
from types import SimpleNamespace as NS
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from nodelang import cloud_relay, model_catalogue as catalogue, model_router
from nodelang.application_server import _CleanAuthorityHttpServer
from nodelang.http_server import QuietThreadingHTTPServer
from nodelang.runtime_activity import RuntimeActivity

# Split literals: the public-repo commit gate reads "token = <long string>" as a leaked credential.
SESSION = {"token": "fixture-" + "cloud-session", "base_url": "https://cloud.example"}
OTHER = {"token": "fixture-" + "other-session", "base_url": "https://cloud.example"}
ROWS = [{"name": "Model A", "route": "vendor/model-a", "vendor": "vendor", "tag": "BYO",
         "ctx": "8k", "cost": "free", "col": "#3a6acc"}]
REFUSED = ("The cloud refused this machine's sign-in: it expired or was revoked. "
           "Sign in again under Settings, Account.")
CLOUD = "CLOUD · subscription"
# The projection stands in for the founder's measured 4.3s, and the bar is what the
# picker is allowed to wait for it. His graph is not on this machine.
PROJECTION_SECONDS = 3.0
ANSWER_BAR_SECONDS = 1.0


def _raise(error):
    def source(*args, **kwargs):
        raise error
    return source


@pytest.fixture
def sources(monkeypatch):
    """Three named sources under the court's hand, and a cloud session that exists."""
    monkeypatch.setattr(model_router, "default_cloud_session", lambda: SESSION)
    monkeypatch.setattr(catalogue, "cloud_models", lambda *args, **kwargs: [])
    monkeypatch.setattr(catalogue, "openrouter_models", lambda **kwargs: [dict(row) for row in ROWS])
    monkeypatch.setattr(catalogue, "local_models", lambda **kwargs: [])
    catalogue.reset_cache()
    yield monkeypatch
    catalogue.reset_cache()


@pytest.fixture
def served():
    """The shipped /api/universal/models route, answered over a real socket."""
    owner = object.__new__(_CleanAuthorityHttpServer)
    owner._mutation_lock = threading.RLock()
    owner.activity = RuntimeActivity()
    owner._resolve_binding = lambda token, **kwargs: NS(session_root="session-a", view_root="view-a")
    owner._standing_scope = lambda binding, **kwargs: "scope-a"
    httpd = QuietThreadingHTTPServer(("127.0.0.1", 0), owner._make_handler())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    origin = "http://127.0.0.1:%d" % httpd.server_address[1]

    def get(path="/api/universal/models", timeout=30.0):
        request = Request(origin + path,
                          headers={"Origin": origin, "X-ArchHub-Session": "browser-token-a"})
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout) as answer:
                return time.perf_counter() - started, answer.status, json.loads(answer.read())
        except HTTPError as refusal:
            return time.perf_counter() - started, refusal.code, json.loads(refusal.read())

    try:
        yield NS(owner=owner, get=get)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_discovery_answers_while_a_long_projection_holds_the_mutation_lock(served, sources):
    projecting, finished = threading.Event(), threading.Event()

    def projection():
        with served.owner._mutation_lock:
            projecting.set()
            time.sleep(PROJECTION_SECONDS)
        finished.set()

    worker = threading.Thread(target=projection, daemon=True)
    worker.start()
    assert projecting.wait(5.0), "the projection never took the lock"
    elapsed, status, payload = served.get()
    still_projecting = not finished.is_set()
    worker.join(timeout=10)
    assert (status, payload["ok"], payload["count"]) == (200, True, 1)
    assert elapsed < ANSWER_BAR_SECONDS, (
        "the picker queued %.2fs behind a canvas projection holding the graph lock" % elapsed)
    assert still_projecting, "the projection was already over; the lock was not held during the read"


def test_the_recheck_still_refuses_a_scope_that_moved_during_discovery(served, sources):
    scopes = iter(["scope-a", "scope-b"])
    served.owner._standing_scope = lambda binding, **kwargs: next(scopes, "scope-b")
    _, status, payload = served.get()
    assert (status, payload) == (403, {
        "ok": False, "error": "Model discovery is unavailable for this session."})


def test_a_source_that_gave_nothing_says_so_where_its_rows_would_have_been(served, sources):
    sources.setattr(catalogue, "cloud_models",
                    _raise(OSError("getaddrinfo failed for cloud.example")))
    _, status, payload = served.get()
    assert status == 200 and payload["count"] == 1
    assert payload["source_notes"] == {CLOUD: CLOUD + " did not answer. Refresh to ask again."}
    # Exception text can carry an authenticated URL, so none of it is forwarded.
    assert payload["source_errors"] == {CLOUD: "Provider catalogue unavailable"}


def test_an_expired_cloud_session_produces_the_sign_in_line(served, sources):
    sources.setattr(catalogue, "cloud_models", _raise(urllib.error.HTTPError(
        SESSION["base_url"] + "/v1/models", 401, "Unauthorized", {}, None)))
    _, status, payload = served.get()
    assert status == 200
    assert payload["source_notes"][CLOUD] == REFUSED
    assert cloud_relay.SIGN_IN_AGAIN in payload["source_notes"][CLOUD]


def test_a_machine_with_no_cloud_session_is_told_the_same_thing(sources):
    groups = catalogue.live_model_groups(None, now=0.0)
    assert groups["source_notes"][CLOUD] == (
        "No ArchHub cloud session on this machine. " + cloud_relay.SIGN_IN_AGAIN)


def test_the_held_answer_is_served_at_once_and_refreshed_behind_it(sources):
    reads = []

    def openrouter(**kwargs):
        reads.append(time.time())
        time.sleep(0.5)
        return [dict(row) for row in ROWS]

    sources.setattr(catalogue, "openrouter_models", openrouter)
    cold = catalogue.live_model_groups(SESSION, now=0.0)
    assert len(reads) == 1 and cold["stale"] is False and cold["count"] == 1

    started = time.perf_counter()
    fresh = catalogue.held_model_groups(SESSION, now=10.0)
    assert time.perf_counter() - started < 0.1 and fresh["stale"] is False and len(reads) == 1

    started = time.perf_counter()
    stale = catalogue.held_model_groups(SESSION, now=100.0)
    assert time.perf_counter() - started < 0.1, "a stale answer waited for the sources"
    assert (stale["stale"], stale["age_seconds"], stale["refreshing"]) == (True, 100.0, True)
    assert stale["count"] == 1, "the stale answer still carries its rows"

    deadline = time.time() + 15.0
    while catalogue.held_model_groups(SESSION, now=100.0)["stale"] and time.time() < deadline:
        time.sleep(0.05)
    assert len(reads) == 2, "nothing was refreshed behind the stale answer"
    assert catalogue.held_model_groups(SESSION, now=100.0)["stale"] is False


def test_another_account_is_never_answered_from_this_one(sources):
    catalogue.live_model_groups(SESSION, now=0.0)
    assert catalogue.held_model_groups(SESSION, now=1.0) is not None
    assert catalogue.held_model_groups(OTHER, now=1.0) is None
    assert catalogue.held_model_groups(None, now=1.0) is None
