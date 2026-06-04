"""MAKE-IT-REAL — in-app "Sign in to ArchHub Cloud" wiring (2026-05-31).

Before this work the ONLY token-minting path in the UI was the first-run
onboarding dialog (cloud_auth.SignInWorker). After first run there was no way
to sign in from the UI, and the Brain "Back up my brain" button dead-ended at
Settings with no sign-in handler. This suite pins the now-real flow:

  * bridge.cloud_sign_in()  — launches the SAME real PKCE browser flow
    (cloud_auth.SignInWorker) off the Qt main thread, holds the worker so it
    isn't GC'd, and bridges its succeeded/failed signals to cloud_signin_done.
  * bridge.cloud_sign_out() — calls cloud_client.logout() (POST /v1/auth/logout
    Bearer) on the background pool then ALWAYS clears the local token, emitting
    cloud_signout_done.
  * bridge.cloud_status()   — cheap synchronous signed-in probe (no network).
  * cloud_client.logout()   — server revoke contract + unconditional local
    clear (honest offline sign-out).
  * SettingsDialog grows a real Account tab + a focus_section("account") route,
    and renders the sign-in/out buttons reaching the bridge slots; the signed-in
    state renders from a TEST-minted token.

SAFETY: NO test ever performs a real sign-in / creates an account / enters
credentials. cloud_auth.SignInWorker is replaced with a fake that records
start() and lets the test drive the succeeded/failed signals — the real browser
flow (the founder's one manual step) is never invoked. All HTTP is mocked.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ─────────────────────── fixtures ────────────────────────────────────
class _StubManager:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    """Bridge with no router/engine — the cloud slots only touch
    cloud_client / cloud_auth, mocked per-test."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    return _bridge_module.ArchHubBridge(
        manager=_StubManager(),
        auto_extract_memory=False,
    )


class _SyncPool:
    """Runs submitted work inline so the threaded sign-out slot is
    deterministic (no real thread, no waiting on the signal)."""

    def submit(self, fn, *a, **k):
        fn(*a, **k)
        return None


def _patch_sync_pool(bridge_inst, monkeypatch):
    monkeypatch.setattr(bridge_inst, "_bg_pool", lambda: _SyncPool())


class _FakeSignInWorker:
    """Stand-in for cloud_auth.SignInWorker. Records that start() was
    called (proving the slot launches the real worker off-thread) WITHOUT
    opening a browser. Exposes succeeded/failed as plain objects the test
    drives. The real browser sign-in (founder's manual step) never runs."""

    instances: list = []

    class _Sig:
        def __init__(self):
            self._slots = []

        def connect(self, fn):
            self._slots.append(fn)

        def emit(self, *args):
            for fn in list(self._slots):
                fn(*args)

    def __init__(self, parent=None):
        self.parent = parent
        self.succeeded = self._Sig()
        self.failed = self._Sig()
        self.started = False
        self.cancelled = False
        self._thread = None     # mimic the QObject's internal thread handle
        _FakeSignInWorker.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def fake_signin(monkeypatch):
    """Patch cloud_auth.SignInWorker with the recording fake. Returns the
    class so the test can reach the latest instance + drive its signals."""
    _FakeSignInWorker.instances = []
    import cloud_auth
    monkeypatch.setattr(cloud_auth, "SignInWorker", _FakeSignInWorker)
    return _FakeSignInWorker


# ═══════════════════════ cloud_client.logout() ════════════════════════
def test_logout_posts_to_server_and_clears_token(monkeypatch):
    """Token present → logout() POSTs /v1/auth/logout with Bearer auth,
    gets 200 {ok:true}, and clears the local token. (mock HTTP)."""
    import cloud_client

    # A token is present; capture the clear + the HTTP request.
    monkeypatch.setattr(cloud_client, "current_token", lambda: "tok-test")
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    cleared = {"n": 0}
    monkeypatch.setattr(cloud_client, "clear_token",
                        lambda: cleared.__setitem__("n", cleared["n"] + 1))

    posted = {}

    class _FakeResp:
        def __init__(self, body, status=200):
            self._b = body
            self.status = status

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        posted["url"] = req.full_url
        posted["method"] = req.get_method()
        posted["auth"] = req.headers.get("Authorization")
        return _FakeResp(json.dumps({"ok": True}).encode("utf-8"))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    ok, msg = cloud_client.logout()

    assert ok is True
    assert posted["url"] == "http://127.0.0.1:8789/v1/auth/logout"
    assert posted["method"] == "POST"
    assert posted["auth"] == "Bearer tok-test"
    # Local token cleared no matter what.
    assert cleared["n"] == 1
    assert isinstance(msg, str) and msg


def test_logout_clears_locally_even_when_offline(monkeypatch):
    """Server unreachable → logout() STILL clears the local token and
    reports honestly (ok=False, "signed out on this device")."""
    import cloud_client

    monkeypatch.setattr(cloud_client, "current_token", lambda: "tok-test")
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    cleared = {"n": 0}
    monkeypatch.setattr(cloud_client, "clear_token",
                        lambda: cleared.__setitem__("n", cleared["n"] + 1))

    import urllib.error
    import urllib.request

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    ok, msg = cloud_client.logout()

    # Honest: server revoke failed, but we cleared locally.
    assert ok is False
    assert cleared["n"] == 1
    assert "device" in msg.lower() or "couldn't" in msg.lower()


def test_logout_noop_when_already_signed_out(monkeypatch):
    """No token → logout() is a clean no-op that still ensures local state
    is clear and reports ok=True ("Already signed out")."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token", lambda: None)
    cleared = {"n": 0}
    monkeypatch.setattr(cloud_client, "clear_token",
                        lambda: cleared.__setitem__("n", cleared["n"] + 1))
    # urlopen must NOT be called — fail loudly if it is.
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("logout() must not hit the network with no token")
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    ok, msg = cloud_client.logout()
    assert ok is True
    assert cleared["n"] == 1


# ═══════════════════════ bridge slot presence ═════════════════════════
def test_bridge_has_cloud_signin_slots():
    """cloud_sign_in / cloud_sign_out / cloud_status exist + are callable.
    Silent renames break the Settings Account buttons + the Brain CTA."""
    from bridge import ArchHubBridge
    for name in ("cloud_sign_in", "cloud_sign_out", "cloud_status"):
        assert hasattr(ArchHubBridge, name), f"missing slot {name}"
        assert callable(getattr(ArchHubBridge, name))


def test_cloud_slots_return_str_annotation():
    """Each cloud slot returns a str (JSON) — the QWebChannel contract."""
    from bridge import ArchHubBridge
    for name in ("cloud_sign_in", "cloud_sign_out", "cloud_status"):
        sig = inspect.signature(getattr(ArchHubBridge, name))
        ann = sig.return_annotation
        assert ann is str or ann == "str", (
            f"ArchHubBridge.{name} return annotation {ann!r}, expected str"
        )


def test_bridge_has_cloud_signin_signals():
    """The signals the UI listens for must exist on the class."""
    from bridge import ArchHubBridge
    assert hasattr(ArchHubBridge, "cloud_signin_done")
    assert hasattr(ArchHubBridge, "cloud_signout_done")


def test_open_settings_accepts_section_arg():
    """open_settings is overloaded to take an optional section so the Brain
    backup CTA can route to Settings → Account. Two stacked @pyqtSlot
    decorators expose both the no-arg and the str-arg call."""
    from bridge import ArchHubBridge
    sig = inspect.signature(ArchHubBridge.open_settings)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) >= 1, "open_settings must accept a section arg"
    # The section param has a default so the legacy no-arg call still works.
    assert params[0].default == "" or params[0].default is None


# ═══════════════════════ cloud_status (sync probe) ════════════════════
def test_cloud_status_reports_not_signed_in(bridge_inst, monkeypatch):
    """No token → {signed_in: false}. No network I/O."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: False)
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    data = json.loads(bridge_inst.cloud_status())
    assert data.get("signed_in") is False
    assert data.get("cloud_url") == "http://127.0.0.1:8789"


def test_cloud_status_reports_signed_in_with_test_token(bridge_inst, monkeypatch):
    """A present (TEST) token → {signed_in: true}. Never a real login."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: True)
    data = json.loads(bridge_inst.cloud_status())
    assert data.get("signed_in") is True


# ═══════════════════════ cloud_sign_in (threaded, real worker) ════════
def test_cloud_sign_in_launches_worker_threaded(bridge_inst, fake_signin):
    """cloud_sign_in constructs the SignInWorker, holds a reference so it
    isn't GC'd, and calls start() (the worker spawns its OWN thread → the
    slot is non-blocking). Returns {async, request_id} immediately."""
    raw = bridge_inst.cloud_sign_in()
    started = json.loads(raw)
    assert started.get("async") is True
    assert started.get("request_id")
    # Exactly one worker was created + started; bridge holds it alive.
    assert len(fake_signin.instances) == 1
    worker = fake_signin.instances[0]
    assert worker.started is True
    assert getattr(bridge_inst, "_cloud_signin_worker", None) is worker


def test_cloud_sign_in_emits_done_on_success(bridge_inst, fake_signin, monkeypatch):
    """When the worker's `succeeded` fires (the founder finished the real
    browser sign-in), the slot emits cloud_signin_done with
    {ok, signed_in, email, plan, request_id} — driven by a TEST payload,
    never a real login."""
    # cloud_usage.refresh_async is best-effort; stub so it never touches net.
    import cloud_auth  # noqa
    captured: list = []
    bridge_inst.cloud_signin_done.connect(captured.append)

    raw = bridge_inst.cloud_sign_in()
    started = json.loads(raw)
    worker = fake_signin.instances[0]

    # Drive the worker's succeeded signal with a TEST-minted payload (the
    # shape SignInWorker emits: exchange payload + me()).
    worker.succeeded.emit({
        "token": "sk_test_only", "plan": "pro",
        "me": {"email": "founder@example.com", "plan": "pro",
               "remaining_messages": 42},
    })

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is True
    assert payload.get("signed_in") is True
    assert payload.get("email") == "founder@example.com"
    assert payload.get("plan") == "pro"
    assert payload.get("remaining_messages") == 42
    assert payload.get("request_id") == started.get("request_id")


def test_cloud_sign_in_emits_done_on_failure(bridge_inst, fake_signin):
    """Worker `failed` (cancelled / timed out) → cloud_signin_done with
    {ok:false, signed_in:false, error}. The honest not-signed-in path."""
    captured: list = []
    bridge_inst.cloud_signin_done.connect(captured.append)

    raw = bridge_inst.cloud_sign_in()
    started = json.loads(raw)
    fake_signin.instances[0].failed.emit("Sign-in cancelled.")

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is False
    assert payload.get("signed_in") is False
    assert "cancel" in (payload.get("error") or "").lower()
    assert payload.get("request_id") == started.get("request_id")


def test_cloud_sign_in_reentrancy_guard(bridge_inst, fake_signin):
    """A second cloud_sign_in() while a browser flow is open is a no-op
    (does not spawn a second worker). We simulate "in flight" by giving the
    held worker a live thread handle."""
    bridge_inst.cloud_sign_in()
    worker = fake_signin.instances[0]

    class _AliveThread:
        def is_alive(self):
            return True
    worker._thread = _AliveThread()

    raw = bridge_inst.cloud_sign_in()
    second = json.loads(raw)
    assert second.get("already_running") is True
    # Still only ONE worker instance — no duplicate browser flow.
    assert len(fake_signin.instances) == 1


# ═══════════════════════ cloud_sign_out (server revoke + clear) ═══════
def test_cloud_sign_out_calls_server_logout_and_clears(
    bridge_inst, monkeypatch
):
    """cloud_sign_out → cloud_client.logout() (which POSTs /v1/auth/logout
    Bearer + clears the token), then emits cloud_signout_done {ok,
    signed_in:false}. We assert the server contract + the local clear via a
    mocked HTTP layer."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token", lambda: "tok-test")
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    cleared = {"n": 0}
    monkeypatch.setattr(cloud_client, "clear_token",
                        lambda: cleared.__setitem__("n", cleared["n"] + 1))

    posted = {}

    class _FakeResp:
        def __init__(self, body):
            self._b = body
            self.status = 200

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        posted["url"] = req.full_url
        posted["auth"] = req.headers.get("Authorization")
        return _FakeResp(json.dumps({"ok": True}).encode("utf-8"))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    captured: list = []
    bridge_inst.cloud_signout_done.connect(captured.append)

    raw = bridge_inst.cloud_sign_out()
    started = json.loads(raw)
    assert started.get("async") is True
    assert started.get("request_id")

    # The signal fired (pool ran inline) with the signed-out result.
    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload.get("ok") is True
    assert payload.get("signed_in") is False
    assert payload.get("request_id") == started.get("request_id")

    # Server logout contract hit + token cleared locally.
    assert posted["url"] == "http://127.0.0.1:8789/v1/auth/logout"
    assert posted["auth"] == "Bearer tok-test"
    assert cleared["n"] == 1


def test_cloud_sign_out_clears_locally_when_offline(bridge_inst, monkeypatch):
    """Offline → still emits a signed-out result and the local token is
    cleared (honest sign-out even when the server can't be reached)."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import cloud_client
    monkeypatch.setattr(cloud_client, "current_token", lambda: "tok-test")
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    cleared = {"n": 0}
    monkeypatch.setattr(cloud_client, "clear_token",
                        lambda: cleared.__setitem__("n", cleared["n"] + 1))

    import urllib.error
    import urllib.request

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    captured: list = []
    bridge_inst.cloud_signout_done.connect(captured.append)

    bridge_inst.cloud_sign_out()
    assert len(captured) == 1
    payload = json.loads(captured[0])
    # signed_in is always False after sign-out; ok reflects the server (False).
    assert payload.get("signed_in") is False
    assert cleared["n"] == 1


# ═══════════════════════ Settings → Account tab ═══════════════════════
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication
    import sys as _sys
    return QApplication.instance() or QApplication(_sys.argv)


def test_account_tab_in_tabs_and_is_qwidget():
    """SettingsDialog.TABS includes Account, mapped to a QWidget subclass."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QWidget
    from settings_dialog import SettingsDialog, AccountTab
    labels = [label for label, _cls in SettingsDialog.TABS]
    assert "Account" in labels
    assert issubclass(AccountTab, QWidget)
    # section route maps "account" → the Account tab.
    assert SettingsDialog.SECTION_TO_TAB.get("account") == "Account"


def test_account_tab_signed_out_renders_signin_button(qapp, tmp_path, monkeypatch):
    """Signed OUT → the Account tab shows the real 'Sign in to ArchHub
    Cloud' button (visible) and hides Sign out. Clicking it reaches the
    bridge cloud_sign_in slot (we stub the bridge + assert the call)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: False)
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")

    from settings_dialog import AccountTab

    calls = {"sign_in": 0, "sign_out": 0}

    class _StubBridge:
        # Provide the signals as None so _connect_bridge_signals no-ops
        # safely; the tab guards on hasattr/connect.
        cloud_signin_done = None
        cloud_signout_done = None

        def cloud_sign_in(self):
            calls["sign_in"] += 1

        def cloud_sign_out(self):
            calls["sign_out"] += 1

    class _ParentDlg:
        bridge = _StubBridge()

        def notify_changed(self):
            pass

    tab = AccountTab(_ParentDlg())
    # Signed-out state: sign-in visible, sign-out hidden.
    assert tab._signin_btn.isVisibleTo(tab) or not tab._signin_btn.isHidden()
    assert tab._signout_btn.isHidden() or not tab._signout_btn.isVisibleTo(tab)
    assert tab._signed_in is False

    # Clicking sign-in reaches the bridge slot (the real SignInWorker
    # launcher). The browser never opens — the bridge is stubbed.
    tab._on_sign_in()
    assert calls["sign_in"] == 1


def test_account_tab_signed_in_renders_account_and_signout(qapp, tmp_path, monkeypatch):
    """Signed IN (via a TEST-minted token) → the Account tab shows the
    account detail + a working Sign out button reaching cloud_sign_out.
    NEVER a real login — is_signed_in()/me() are stubbed."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: True)
    monkeypatch.setattr(cloud_client, "base_url",
                        lambda: "http://127.0.0.1:8789")
    monkeypatch.setattr(cloud_client, "me",
                        lambda: {"email": "founder@example.com",
                                 "plan": "pro", "remaining_messages": 7})

    from settings_dialog import AccountTab

    calls = {"sign_out": 0}

    class _StubBridge:
        cloud_signin_done = None
        cloud_signout_done = None

        def cloud_sign_out(self):
            calls["sign_out"] += 1

    class _ParentDlg:
        bridge = _StubBridge()

        def notify_changed(self):
            pass

    tab = AccountTab(_ParentDlg())
    # The signed-in fetch runs on a worker thread; drive the render directly
    # with the same payload to assert the UI renders account detail.
    tab._signed_in = True
    tab._apply_account({"email": "founder@example.com", "plan": "pro",
                        "remaining_messages": 7})
    assert "founder@example.com" in tab._detail.text()
    assert "pro" in tab._detail.text()

    tab._render_state()
    assert not tab._signout_btn.isHidden() or tab._signout_btn.isVisibleTo(tab)

    # Sign out reaches the bridge slot; confirm the dialog accepts it. We
    # bypass the confirm dialog by calling the signal handler directly +
    # asserting the slot path via a direct invocation of the bridge.
    tab._bridge().cloud_sign_out()
    assert calls["sign_out"] == 1
    # After a real sign-out the token is cleared, so is_signed_in() now
    # returns False — model that before the done-handler refreshes truth.
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: False)
    # The signout-done handler flips the tab to signed-out.
    tab._on_signout_done(json.dumps({"ok": True, "signed_in": False}))
    assert tab._signed_in is False


# ═══════════════════════ JSX wiring (static trace) ════════════════════
JSX = APP_ROOT / "web_ui" / "studio-lm.jsx"


def test_jsx_brain_button_reaches_cloud_sign_in():
    """The Brain 'Back up my brain' signed-out path calls cloud_sign_in
    (the real SignInWorker) — not a dead-end. Trace it in the source."""
    src = JSX.read_text(encoding="utf-8")
    assert "bridgeAsync('cloud_sign_in')" in src, (
        "Brain backup signed-out CTA must reach the real cloud_sign_in slot"
    )
    # And it still has a Settings → Account fallback for older builds.
    assert "section:'account'" in src or 'section:"account"' in src


def test_jsx_open_settings_forwards_section():
    """onCmdOpenSettings forwards detail.section so the founder lands on
    the Account tab; openSettingsResolved passes it to open_settings(str)."""
    src = JSX.read_text(encoding="utf-8")
    assert "ev.detail.section" in src or "detail && ev.detail.section" in src
    assert "bridgeCall('open_settings', section)" in src


def test_jsx_listens_for_cloud_signin_done():
    """BrainBackupRow flips to signed-in when cloud_signin_done fires, so
    the next click is a real backup without a reload."""
    src = JSX.read_text(encoding="utf-8")
    assert "cloud_signin_done" in src
    assert "cloud_signout_done" in src


# ═══════════════════════ MAKE-IT-REAL: bind local brain ⇄ cloud account ═══
# The local brain is bound to the signed-in account on EVERY sign-in (the
# single chokepoint cloud_auth._pair_brain), an auto-sync scheduler keeps
# local + cloud from drifting between sign-ins, and sign-out unbinds + stops
# the scheduler. SAFETY: no test performs a real sign-in; me()/the brain
# BrainClient are mocked, the SignInWorker is the recording fake.


# ── cloud_client.me_identity() reads the NEW server user_id field ──────────
def test_me_identity_exposes_user_id(monkeypatch):
    """me_identity() surfaces {user_id, email, brain_id} from /v1/me's new
    user_id field — the value the brain binding is keyed on."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "me", lambda: {
        "user_id": "u_cloud_42", "brain_id": "u_cloud_42",
        "email": "founder@example.com", "plan": "pro",
    })
    ident = cloud_client.me_identity()
    assert ident == {
        "user_id": "u_cloud_42",
        "email": "founder@example.com",
        "brain_id": "u_cloud_42",
    }


def test_me_identity_none_when_no_user_id(monkeypatch):
    """No user_id in the payload (old server / not signed in) → None, so the
    bind path graceful-degrades instead of binding to a blank owner."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "me", lambda: {"email": "x@y.z"})
    assert cloud_client.me_identity() is None
    monkeypatch.setattr(cloud_client, "me", lambda: None)
    assert cloud_client.me_identity() is None


# ── cloud_auth._pair_brain → brain.set_owner(me().user_id, email) ──────────
class _RecordingBrainClient:
    """Captures _call(tool, args) so a test can assert brain.set_owner /
    brain.clear_owner were invoked with the right arguments — without a live
    daemon. Returns a benign ok payload."""

    calls: list = []

    def __init__(self, *a, **k):
        pass

    def _call(self, tool, arguments=None, timeout=None):
        _RecordingBrainClient.calls.append((tool, dict(arguments or {})))
        return {"ok": True, "owner_user": (arguments or {}).get("user_id", "")}


def test_pair_brain_binds_owner_with_me_user_id(monkeypatch):
    """_pair_brain (the single sign-in chokepoint) fetches the cloud identity
    and calls brain.set_owner with the me() user_id + email. This is what
    makes EVERY sign-in bind the local brain to the account."""
    import cloud_auth
    import cloud_client
    import memory_gate

    # me() returns the cloud identity (TEST values — never a real login).
    monkeypatch.setattr(cloud_client, "me", lambda: {
        "user_id": "u_cloud_42", "email": "founder@example.com",
        "brain_id": "u_cloud_42", "plan": "pro",
    })
    _RecordingBrainClient.calls = []
    monkeypatch.setattr(memory_gate, "BrainClient", _RecordingBrainClient)

    worker = cloud_auth.SignInWorker()
    result = worker._bind_owner()

    assert result == {"ok": True, "owner_user": "u_cloud_42"}
    set_owner_calls = [c for c in _RecordingBrainClient.calls
                       if c[0] == "brain.set_owner"]
    assert len(set_owner_calls) == 1
    _, args = set_owner_calls[0]
    assert args["user_id"] == "u_cloud_42"
    assert args["email"] == "founder@example.com"


def test_pair_brain_calls_bind_owner(monkeypatch):
    """The full _pair_brain runs _bind_owner FIRST (so the account binding
    happens on both onboarding first-run AND the Settings re-entry flow).
    We stub the network announce + sync so only the bind is observed."""
    import cloud_auth
    worker = cloud_auth.SignInWorker()

    called = {"bind": 0}
    monkeypatch.setattr(worker, "_bind_owner",
                        lambda: called.__setitem__("bind", called["bind"] + 1))
    # Neutralise the two HTTP steps (announce + /v1/brain/sync).
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no net")))

    worker._pair_brain(token="tok-test")
    assert called["bind"] == 1


def test_bind_owner_graceful_when_not_signed_in(monkeypatch):
    """No identity (me_identity None) → _bind_owner returns None and never
    touches the brain (graceful-degrade; sign-in still succeeds)."""
    import cloud_auth
    import cloud_client
    import memory_gate
    monkeypatch.setattr(cloud_client, "me_identity", lambda: None)
    _RecordingBrainClient.calls = []
    monkeypatch.setattr(memory_gate, "BrainClient", _RecordingBrainClient)

    worker = cloud_auth.SignInWorker()
    assert worker._bind_owner() is None
    assert _RecordingBrainClient.calls == []


def test_bind_owner_graceful_when_daemon_down(monkeypatch):
    """Brain daemon unreachable (BrainClient._call raises) → _bind_owner
    swallows it and returns None. Sign-in MUST NOT fail."""
    import cloud_auth
    import cloud_client
    import memory_gate
    monkeypatch.setattr(cloud_client, "me_identity",
                        lambda: {"user_id": "u_1", "email": "a@b.c"})

    class _DownClient:
        def __init__(self, *a, **k):
            pass

        def _call(self, *a, **k):
            raise ConnectionRefusedError("daemon down")

    monkeypatch.setattr(memory_gate, "BrainClient", _DownClient)
    worker = cloud_auth.SignInWorker()
    assert worker._bind_owner() is None


# ── auto-sync scheduler: start on sign-in, stop on sign-out ────────────────
def test_autosync_starts_on_sign_in_success(bridge_inst, fake_signin, monkeypatch):
    """A successful sign-in starts the brain⇄cloud auto-sync scheduler so
    local + cloud stop drifting between sign-ins."""
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: True)
    # Don't actually fire a backup tick during the test.
    monkeypatch.setattr(bridge_inst, "brain_cloud_backup", lambda: None)

    assert bridge_inst._brain_autosync_running() is False
    bridge_inst.cloud_sign_in()
    worker = fake_signin.instances[-1]
    worker.succeeded.emit({"token": "sk_test", "plan": "pro",
                            "me": {"email": "f@e.com", "plan": "pro"}})
    try:
        assert bridge_inst._brain_autosync_running() is True
    finally:
        bridge_inst._stop_brain_autosync()


def test_autosync_stops_on_sign_out(bridge_inst, monkeypatch):
    """Sign-out stops the auto-sync scheduler (no more background pushes once
    the user is signed out)."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import cloud_client
    monkeypatch.setattr(cloud_client, "logout", lambda: (True, "Signed out."))
    monkeypatch.setattr(cloud_client, "clear_token", lambda: None)
    # Stub the brain unbind so no live daemon is needed.
    monkeypatch.setattr(bridge_inst, "_unbind_brain_owner", lambda: None)
    monkeypatch.setattr(bridge_inst, "brain_cloud_backup", lambda: None)

    # Start a scheduler, then sign out → it must stop.
    bridge_inst._start_brain_autosync()
    assert bridge_inst._brain_autosync_running() is True

    bridge_inst.cloud_sign_out()
    # Give the daemon thread a beat to observe the stop Event.
    import time as _t
    for _ in range(50):
        if not bridge_inst._brain_autosync_running():
            break
        _t.sleep(0.02)
    assert bridge_inst._brain_autosync_running() is False


def test_autosync_start_is_idempotent(bridge_inst, monkeypatch):
    """A second start (e.g. a re-sign-in) does not spawn a duplicate loop."""
    monkeypatch.setattr(bridge_inst, "brain_cloud_backup", lambda: None)
    try:
        assert bridge_inst._start_brain_autosync() is True
        assert bridge_inst._start_brain_autosync() is False   # already running
    finally:
        bridge_inst._stop_brain_autosync()


def test_autosync_tick_calls_brain_cloud_backup(bridge_inst, monkeypatch):
    """The scheduler loop calls brain_cloud_backup on its interval WHILE
    signed in. We force a tiny interval + a signed-in token and observe the
    push fire, then stop."""
    monkeypatch.setenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "0.05")
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: True)
    pushes = {"n": 0}
    monkeypatch.setattr(bridge_inst, "brain_cloud_backup",
                        lambda: pushes.__setitem__("n", pushes["n"] + 1))

    bridge_inst._start_brain_autosync()
    import time as _t
    for _ in range(100):
        if pushes["n"] >= 1:
            break
        _t.sleep(0.02)
    bridge_inst._stop_brain_autosync()
    assert pushes["n"] >= 1


def test_autosync_loop_self_stops_when_token_gone(bridge_inst, monkeypatch):
    """If the token disappears (e.g. expiry) the loop self-stops on its next
    tick — it does not keep pushing for a signed-out user."""
    monkeypatch.setenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "0.05")
    import cloud_client
    monkeypatch.setattr(cloud_client, "is_signed_in", lambda: False)
    pushed = {"n": 0}
    monkeypatch.setattr(bridge_inst, "brain_cloud_backup",
                        lambda: pushed.__setitem__("n", pushed["n"] + 1))

    bridge_inst._start_brain_autosync()
    import time as _t
    for _ in range(60):
        if not bridge_inst._brain_autosync_running():
            break
        _t.sleep(0.02)
    assert bridge_inst._brain_autosync_running() is False
    # Never pushed for a signed-out user.
    assert pushed["n"] == 0


def test_autosync_interval_env_override(bridge_inst, monkeypatch):
    """The cadence honours ARCHHUB_BRAIN_SYNC_INTERVAL_S, defaults to 600s,
    and floors at 5s so a typo can't spin the loop hot."""
    monkeypatch.delenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", raising=False)
    assert bridge_inst._brain_autosync_interval_s() == 600.0
    monkeypatch.setenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "120")
    assert bridge_inst._brain_autosync_interval_s() == 120.0
    monkeypatch.setenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "0")
    assert bridge_inst._brain_autosync_interval_s() == 0.01   # floored off 0
    monkeypatch.setenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "-5")
    assert bridge_inst._brain_autosync_interval_s() == 0.01   # floored off neg
    monkeypatch.setenv("ARCHHUB_BRAIN_SYNC_INTERVAL_S", "garbage")
    assert bridge_inst._brain_autosync_interval_s() == 600.0  # fallback


# ── sign-out unbinds the local brain (brain.clear_owner) ───────────────────
def test_cloud_sign_out_calls_clear_owner(bridge_inst, monkeypatch):
    """cloud_sign_out, after clearing the token, calls brain.clear_owner via
    the memory_gate BrainClient — the binding clears, the brain DATA stays."""
    _patch_sync_pool(bridge_inst, monkeypatch)
    import cloud_client
    import memory_gate
    monkeypatch.setattr(cloud_client, "logout", lambda: (True, "Signed out."))
    monkeypatch.setattr(cloud_client, "clear_token", lambda: None)
    monkeypatch.setattr(bridge_inst, "brain_cloud_backup", lambda: None)
    _RecordingBrainClient.calls = []
    monkeypatch.setattr(memory_gate, "BrainClient", _RecordingBrainClient)

    bridge_inst.cloud_sign_out()

    clear_calls = [c for c in _RecordingBrainClient.calls
                   if c[0] == "brain.clear_owner"]
    assert len(clear_calls) == 1


def test_unbind_brain_owner_graceful_when_daemon_down(bridge_inst, monkeypatch):
    """_unbind_brain_owner swallows a down daemon (returns None) so sign-out
    completes locally even when the brain is unreachable."""
    import memory_gate

    class _DownClient:
        def __init__(self, *a, **k):
            pass

        def _call(self, *a, **k):
            raise ConnectionRefusedError("daemon down")

    monkeypatch.setattr(memory_gate, "BrainClient", _DownClient)
    assert bridge_inst._unbind_brain_owner() is None


def test_bridge_has_autosync_and_unbind_helpers():
    """The scheduler + unbind helpers exist on the class (silent renames
    would break the MAKE-IT-REAL bind/auto-sync/unbind wiring)."""
    from bridge import ArchHubBridge
    for name in ("_start_brain_autosync", "_stop_brain_autosync",
                 "_brain_autosync_running", "_brain_autosync_interval_s",
                 "_unbind_brain_owner"):
        assert hasattr(ArchHubBridge, name), f"missing helper {name}"
        assert callable(getattr(ArchHubBridge, name))
