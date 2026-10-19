"""Design contract exercised through the real isolated HTTP/Work/content owners."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest


@pytest.fixture
def api_owner(tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    for name in tuple(os.environ):
        if name.startswith(("ARCHHUB_", "CODEX_", "CLAUDE_", "SESSION_LINK_", "OPENCODE_", "GEMINI_")):
            monkeypatch.delenv(name)
    for name in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "USERPROFILE", "HOME"):
        monkeypatch.setenv(name, str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    owner = ApplicationServer(universal_workspace_root=workspace,
        universal_state_path=tmp_path / "graph.sqlite3", enable_machine_transport=False,
        enable_universal_cloud_gateway=False, enable_brain_cloud_sync=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    try:
        yield owner
    finally:
        owner.close()


def call(owner, function, args=(), *, request_id=None, **overrides):
    from nodelang.universal_application import _view_session_for_context, _read_view_scope_trail_structure
    browser = owner._resolve_browser_session(owner.browser_session_token)
    view, _ = _view_session_for_context(owner.universal_registry, browser.context)
    scope = _read_view_scope_trail_structure(owner.universal_store.snapshot(), owner.universal_registry, view)[-1]
    body = {"action":"data-api", "function":function, "args":list(args),
        "root":owner.universal_registry.workshop_root, "scope":scope,
        "request_id":request_id or function + "-" + str(owner.universal_store.revision), **overrides}
    request = Request(owner.url + "/api/universal/workshop", data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json", "X-ArchHub-Session":owner.browser_session_token,
                 "X-ArchHub-CSRF":browser.csrf_token})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)["result"]
    except HTTPError as exc:
        print("API refusal:", exc.read().decode())
        raise


def test_data_functions_are_real_work_and_one_thread(api_owner):
    app = api_owner
    assert call(app, "listAgentsWorking") == []
    assert call(app, "listTasks") == []
    task = call(app, "sendToBaboom", ["Review the lane fixture", {"provider":"codex"}], request_id="create-one")
    assert task["status"] == "PLANNED" and task["owner"] == "codex"
    assert task["id"] in app.universal_store.snapshot().cells
    assert len(task["messages"]) == 1
    repeated = call(app, "sendToBaboom", ["Review the lane fixture", {"provider":"codex"}], request_id="create-one")
    assert repeated["id"] == task["id"] and len(repeated["messages"]) == 1
    reply = call(app, "sendToBaboom", ["Check the actual bytes", {"taskId":task["id"]}])
    assert reply["id"] == task["id"] and len(reply["messages"]) == 2
    with pytest.raises(HTTPError) as rejected:
        call(app, "setTaskStatus", [task["id"], "DONE"])
    assert rejected.value.code == 400
    assert call(app, "setTaskStatus", [task["id"], "PLANNED"])["status"] == "PLANNED"
    queued = call(app, "queueTaskMessage", [task["id"], "Pending instruction"], request_id="queue-one")
    assert queued["state"] == "queued"
    assert len(call(app, "listTasks")[0]["messages"]) == 2
    sent = call(app, "settleQueuedMessage", [task["id"], queued["id"], True])
    again = call(app, "settleQueuedMessage", [task["id"], queued["id"], True])
    assert sent == again and sent["state"] == "sent"
    assert len(call(app, "listTasks")[0]["messages"]) == 3
    review = call(app, "addTaskReview", [task["id"], "fixture", "Exact bytes checked"])
    assert len(review["reviews"]) == 1
    assert call(app, "resolveTaskReview", [task["id"], 0, True])["resolved"] is True
    assert call(app, "steerTask", [task["id"], "Continue with the existing owner"])["messages"][-1]["text"].endswith("Continue with the existing owner")
    assert len(call(app, "listTasks")) == 1
    assert call(app, "setTaskStatus", [task["id"], "ARCHIVED"])["status"] == "ARCHIVED"
    assert call(app, "setTaskStatus", [task["id"], "PLANNED"])["status"] == "PLANNED"
    delegated = call(app, "sendToBaboom", ["Use Goose explicitly", {"provider":"goose"}], request_id="goose-only")
    assert delegated["owner"] == "goose"
    assert delegated["delivery"] == {"state":"not_sent", "reason":"selected_provider_requires_its_existing_builtin_workflow"}
    browser=app._resolve_browser_session(app.browser_session_token)
    registry=app.universal_registry
    for index in range(10):
        app.conversation_content.append_authenticated(space_root=registry.workshop_root,
            actor_root=browser.subject_root,category_root=registry.workshop_category_roots['note'],
            content='Large sibling '+str(index)+' '+('x'*30000),idempotency_key='large-sibling-'+str(index),
            reply_to_root=task['messages'][0]['id'],authentication_context=browser.context,
            expected_revision=app.universal_store.revision)
    bounded=next(row for row in call(app,'listTasks') if row['id']==task['id'])
    assert bounded['messagesTruncated'] is True
    assert bounded['messagesContinuation']=={'tool':'read','arguments':{'since':0},'work_root':task['id']}


def test_data_functions_enforce_existing_browser_scope(api_owner):
    for override in ({"scope":"foreign-scope"}, {"root":"foreign-room"}):
        with pytest.raises(HTTPError) as rejected:
            call(api_owner, "listTasks", **override)
        assert rejected.value.code in (400, 403)
    with pytest.raises(HTTPError):
        call(api_owner, "__dict__")


def test_real_api_retries_only_a_durable_non_dispatch(api_owner):
    import time
    class Native:
        calls=0
        status='not_sent'
        endpoint={'app':'claude','id':'fixture-api-retry','title':'Fixture Claude','pid':os.getpid()}
        def discover(self,**kwargs):
            return {'status':'ok','recipients':[self.endpoint]}
        def request(self,*args,**kwargs):
            self.calls+=1
            return {'status':self.status,'reason':'fixture_confirmed_no_dispatch'}
        def cancel_pending(self,**kwargs):
            return {'local_call_joined':True,'worker_stopped':True}
        def close(self):
            pass
    native=Native()
    app=api_owner
    app._cloud_relay_transport=app.native_work_delivery._transport=native
    def send():
        result=call(app,'sendToBaboom',['Retry the same fixture',{'provider':'claude'}],request_id='durable-retry')
        deadline=time.monotonic()+5
        while app.native_work_delivery._pending_jobs and time.monotonic()<deadline:
            time.sleep(.01)
        return result
    first=send()
    assert native.calls==1, first
    assert next(row for row in call(app,'listTasks') if row['id']==first['id'])['delivery']['state']=='unavailable'
    native.status='held'
    assert send()['id']==first['id']
    assert native.calls==2
    send()
    assert native.calls==2


def test_baboom_reads_all_declaration_pages():
    from nodelang.baboom_agent_link import list_agents
    pages = iter([{"declarations":[{"agent":"one", "session":"a"}],
                   "declarations_more":True,"next_since":5,"declarations_after":"cursor"},
                  {"declarations":[{"agent":"two", "session":"b"}],"declarations_more":False}])
    calls = []
    def mailbox(method, body):
        calls.append((method, body))
        return next(pages)
    assert [row["session"] for row in list_agents(mailbox=mailbox)] == ["a", "b"]
    assert calls[1][1] == {"since":5, "declarations_after":"cursor"}
