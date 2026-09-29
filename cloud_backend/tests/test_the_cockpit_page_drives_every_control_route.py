"""The founder SEES and clicks every Cockpit control (Cockpit UI, 2026-09-29).

/founder/admin carries a Control section with seven tabs, and every button in
it calls one audited /founder/api route; the page holds no logic of its own.
These hold the page to the router: each control route is driven from the page,
each API path the page calls exists, and nothing the server returns is put on
the page unescaped.
"""
from __future__ import annotations

import re

import pytest

FOUNDER = "founder.desktop@example.test"

# (method, route on the router, the fragment of the page that calls it)
CONTROLS = [
    ("GET", "/founder/api/users/find", "api('users/find?q="),
    ("GET", "/founder/api/users/{key}", "api('users/' + enc(key))"),
    ("POST", "/founder/api/users/{key}/plan", "'/plan'"),
    ("POST", "/founder/api/users/{key}/suspend", "'/suspend'"),
    ("POST", "/founder/api/users/{key}/restore", "'/restore'"),
    ("GET", "/founder/api/stripe", "api('stripe')"),
    ("POST", "/founder/api/stripe/refund", "post('stripe/refund'"),
    ("GET", "/founder/api/community/pending", "api('community/pending')"),
    ("POST", "/founder/api/community/judge", "post('community/judge'"),
    ("GET", "/founder/api/community/facts", "api('community/facts')"),
    ("GET", "/founder/api/community/members", "api('community/members')"),
    ("GET", "/founder/api/relay", "api('relay')"),
    ("POST", "/founder/api/relay/tasks/{task_id}/retry", "'/retry'"),
    ("POST", "/founder/api/relay/drain", "post('relay/drain'"),
    ("GET", "/founder/api/devices", "api('devices'"),
    ("POST", "/founder/api/devices/{user_key}/{device_id}/disconnect", "'/disconnect'"),
    ("GET", "/founder/api/system", "api('system')"),
    ("GET", "/founder/api/errors", "api('errors')"),
    ("POST", "/founder/api/db/query", "post('db/query'"),
]
TABS = ("Users", "Payments", "Community", "Relay", "Devices", "Health", "Database")


@pytest.fixture
def page():
    import founder_cockpit
    return founder_cockpit._PAGE_HTML


def _control(page: str) -> str:
    """The Control markup and the Control script block, nothing older."""
    markup = page[page.index('<section class="control"'):page.index('</section>') + len('</section>')]
    return markup + page[page.index('/* ---- Control'):]


def _routes():
    import main
    return {(method, route.path) for route in main.app.routes
            for method in (getattr(route, "methods", None) or ())}


@pytest.mark.parametrize("method,path,fragment", CONTROLS, ids=[c[1] for c in CONTROLS])
def test_every_control_route_is_driven_from_the_page(page, method, path, fragment):
    assert (method, path) in _routes(), (method, path)
    assert fragment in _control(page), fragment


def test_every_api_path_the_page_calls_exists(page):
    called = set(re.findall(r"(?:api|post)\('([a-z][a-z/_-]*)", _control(page)))
    served = {path for _method, path in _routes() if path.startswith("/founder/api/")}
    for literal in called:
        assert any(path.startswith("/founder/api/" + literal) for path in served), literal


def test_the_page_escapes_what_the_server_returns_and_has_no_inline_handlers(page):
    control = _control(page)
    assert "onclick" not in control and "onchange" not in control
    # Every value placed in a cell or a button goes through esc(); the helpers
    # that build cells (ink, minor, when, pillFor, btn) escape too.
    for helper in ("const ink = (s) => '<span class=\"ink\">' + esc(s)",
                   "esc(good ? yes : no)", "' data-' + k + '=\"' + esc(data[k])"):
        assert helper in control, helper


def test_the_founder_sees_the_seven_tabs_and_destructive_clicks_ask_first(page):
    from fastapi.testclient import TestClient
    import db
    import main
    user = db.get_or_create_user(FOUNDER)
    served = TestClient(main.app).get(
        "/founder/admin", headers={"Authorization": "Bearer " + db.issue_token(user["id"])})
    assert served.status_code == 200
    for tab in TABS:
        assert '>%s</button>' % tab in served.text, tab
    control = _control(page)
    for question in ("Suspend ' + key", "Send this refund to Stripe now?",
                     "Close every queued relay task?", "Disconnect ' + d.device"):
        assert "confirm('" + question in control, question
    assert "const PLANS = [" in served.text and '"trial"' in served.text