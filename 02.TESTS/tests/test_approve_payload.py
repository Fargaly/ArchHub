"""A held send/post/write carries what it will do onto its Approve card and onto its agent's session canvas."""
import json
import os

from nodelang import hook_decision


def _ask_first():
    folder = hook_decision._settings_dir(os.environ)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "permissions.json").write_text(json.dumps({"runMode": "Ask first", "tools": {}}), encoding="utf-8")


LOCAL_EDIT = ("cd C:/Users/someone/repo/.claude/worktrees/approve-payload/01.APP/nodelang && python - <<'PYEOF'\n"
              "from pathlib import Path\np=Path('hook_decision.py'); s=p.read_text(encoding='utf-8')\n"
              "s=s.replace(\"git push -q origin HEAD:main\", \"curl -X POST https://x.example -d @a\")\n"
              "p.write_text(s,encoding='utf-8')\nPYEOF")
LOCAL_APPEND = ("cd C:/Users/someone/repo/02.TESTS/tests && cat >> test_approve_payload.py <<'PYEOF'\n"
                "    push = hook('Bash', {'command': 'git push -q origin HEAD:main'})\n"
                "    post = {'to': 'site@example.com', 'text': 'publish this post'}\nPYEOF")
LOCAL_GREP = 'grep -rn "git push\\|gh release create\\|npm publish" 02.TESTS | head -5'


def _verdict(command, cwd="C:/Users/someone/repo"):
    return hook_decision.decide({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}}, "claude-code")


def test_local_edits_appends_and_greps_are_never_a_post_even_when_their_text_names_a_push(monkeypatch):
    monkeypatch.setattr(hook_decision, "_repo_visibility", lambda owner, repo: "PUBLIC")
    for command in (LOCAL_EDIT, LOCAL_APPEND, LOCAL_GREP, 'python -c "import os; os.system(\'git push\')"',
                    'echo "post this to the channel"'):
        action, _facts = hook_decision.classify(hook_decision.normalize({"tool_name": "Bash", "tool_input": {"command": command}}, "claude-code"), {})
        assert action != "publish", command
        decision = _verdict(command)
        assert "review-before-sharing" not in decision["rules"] and decision.get("hold") is None, (command, decision)
    assert hook_decision.ask_reviews() == []


def test_messages_between_his_own_sessions_never_ask_and_a_mail_to_a_person_does():
    own = (("mcp__ccd_session_mgmt__send_message", {"session_id": "local_123", "message": "STANDARIZE: rename the sheets"}),
           ("SendMessage", {"to": "STANDARIZE", "message": "Use the office template."}),
           ("mcp__archhub_agent_coordination__send", {"to": "*", "text": "Landed the fix."}),
           ("mcp__session_link__send", {"to": "builder-2", "text": "Your turn."}))
    for tool, data in own:
        decision = hook_decision.decide({"tool_name": tool, "tool_input": data}, "claude-code")
        assert "review-before-sharing" not in decision["rules"] and decision.get("hold") is None, (tool, decision)
    mail = hook_decision.decide({"tool_name": "send_email", "tool_input": {"to": "client@example.com", "body": "Hi"}}, "claude-code")
    assert mail["rules"] == ["review-before-sharing"] and mail["hold"], mail
    social = hook_decision.decide({"tool_name": "mcp__archhub_agent_coordination__social_work_execute",
                                   "tool_input": {"platform": "linkedin", "text": "x"}}, "claude-code")
    assert hook_decision._own_workspace("mcp__archhub_agent_coordination__social_work_execute", {"text": "x"}) is False, social


def test_a_push_to_his_own_private_repo_stays_in_his_account_and_a_public_one_is_held(monkeypatch):
    seen = {}
    monkeypatch.setattr(hook_decision, "_git", lambda folder, *args: "https://github.com/someone/ArchHub-private.git" if "get-url" in args else "")
    monkeypatch.setattr(hook_decision, "_repo_visibility", lambda owner, repo: seen.setdefault(owner + "/" + repo, "PRIVATE"))
    hook_decision._private_pushes.cache_clear()
    own = _verdict("git push origin HEAD:main")
    assert own["action"] == "publish" and "review-before-sharing" not in own["rules"] and own.get("hold") is None, own
    assert seen == {"someone/ArchHub-private": "PRIVATE"}
    monkeypatch.setattr(hook_decision, "_repo_visibility", lambda owner, repo: "PUBLIC")
    hook_decision._private_pushes.cache_clear()
    for command in ("git push origin HEAD:main", "cd C:/w && git -C C:/w push -q origin HEAD:main 2>&1 | tail -1",
                    'bash -c "git push origin main"', "gh release create v1.2 dist/app.zip",
                    "curl -X POST https://api.example.com/post -d @note.json"):
        held = _verdict(command)
        assert held["action"] == "publish" and held["rules"] == ["review-before-sharing"] and held["hold"], (command, held)
    monkeypatch.setattr(hook_decision, "_repo_visibility", lambda owner, repo: "")  # GitHub unreadable: the card stays
    hook_decision._private_pushes.cache_clear()
    assert _verdict("git push origin feature")["rules"] == ["review-before-sharing"]


def _session(native, agent):
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create, open_session
    with application_history() as history:
        task = create(history, "Release notes " + native, "founder")["id"]
        path = open_session(history, task)["path"]
        record = {"root": "root-" + native, "session": "identity-" + native, "native_session_id": native,
                  "runtime": "claude", "work": task, "status": "working", "display_name": agent, "agent": agent,
                  "request_id": "r1", "pid": 999999, "created_at": 0}
        with history._transaction(write=True):
            history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                                "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
            history._db.execute("INSERT INTO workshop_declarations VALUES(?,?)", (record["root"], json.dumps(record)))
    return task, path


def _card(hold):
    return next(card for card in hook_decision.ask_reviews() if card["id"] == hold)


def test_a_held_post_shows_where_it_goes_the_words_and_the_files_never_a_secret():
    payload = hook_decision.ask_payload({"tool": "social_post"}, "publish", {"connector": "social", "arguments": {
        "platform": "LinkedIn", "account": "ArchHub", "text": "Door schedule is out. token=sk-abcdefghijklmnop",
        "media": [{"name": "plan.png"}, "C:/out/section.pdf"]}})
    assert payload["to"] == "LinkedIn · ArchHub"
    assert payload["text"].startswith("Door schedule is out.") and "sk-abcdefghijklmnop" not in payload["text"]
    assert payload["files"] == ["plan.png", "C:/out/section.pdf"]
    assert "missing" not in payload
    send = hook_decision.ask_payload({"tool": "send"}, "send", {"to": ["site@example.com"], "body": "Fixed."})
    assert (send["to"], send["text"], send["undo"]) == ("site@example.com", "Fixed.", "No. A sent message stays sent.")
    edit = hook_decision.ask_payload({"tool": "Edit"}, "write", {"file_path": "C:/w/a.txt", "old_string": "x", "new_string": "y"})
    assert (edit["target"], edit["change"]) == ("C:/w/a.txt", "- x\n+ y")
    empty = hook_decision.ask_payload({"tool": "social_post"}, "publish", {"platform": "LinkedIn"})
    assert empty["missing"] == hook_decision.NOTHING_TO_REVIEW


def _public_repo(monkeypatch):
    """A repository whose remote is a public GitHub repo (no network, no real git)."""
    monkeypatch.setattr(hook_decision, "_git", lambda folder, *args: "https://github.com/someone/ArchHub-site.git" if "get-url" in args else "")
    monkeypatch.setattr(hook_decision, "_repo_visibility", lambda owner, repo: "PUBLIC")
    hook_decision._private_pushes.cache_clear()


def test_a_held_git_push_is_a_card_with_its_destination_and_a_node_on_the_agents_canvas(tmp_path, monkeypatch):
    from nodelang.session_files import read_document
    _public_repo(monkeypatch)
    _ask_first()
    task, path = _session("native-push", "Claude")
    held = hook_decision.decide({"tool_name": "Bash", "session_id": "native-push", "cwd": str(tmp_path),
                                 "tool_input": {"command": "git push -q origin HEAD:main"}}, "claude-code")
    assert held["verdict"] == "ask" and held["hold"], held
    card = _card(held["hold"])
    assert card["title"] == "Post" and card["who"] == "Claude"
    assert card["payload"]["to"] == "ArchHub-site, branch main"
    assert card["payload"]["run"] == "git push -q origin HEAD:main"
    assert "missing" not in card["payload"]
    assert card["path"] == path and card["taskId"] == task and card["nodeId"].startswith("held-")
    node = next(n for n in read_document(path)["nodes"] if n["id"] == card["nodeId"])
    assert node["title"] == "Push to ArchHub-site main" and node["params"]["destination"] == "ArchHub-site, branch main"
    assert node["params"]["status"] == "Waiting for your approval" and node["params"]["approval"] == card["id"]

    hook_decision.ask_apply(card["id"], card["input_digest"], "deny", decided_by="founder")
    node = next(n for n in read_document(path)["nodes"] if n["id"] == card["nodeId"])
    assert node["params"]["status"] == "Rejected"


def test_a_card_held_before_payloads_were_kept_still_shows_its_command(monkeypatch):
    _public_repo(monkeypatch)
    _ask_first()
    held = hook_decision.decide({"tool_name": "Bash", "session_id": "no-such-agent",
                                 "tool_input": {"command": "git push origin HEAD:main"}}, "claude-code")
    store = hook_decision._ask_path(os.environ)
    data = json.loads(store.read_text(encoding="utf-8"))
    data["holds"][held["hold"]].pop("payload")
    store.write_text(json.dumps(data), encoding="utf-8")
    card = _card(held["hold"])
    assert card["payload"]["run"] == "git push origin HEAD:main"
    assert card["payload"]["to"] == "origin, branch main"  # its folder was not kept: the remote's name
    assert "path" not in card  # no session file: no node, and no Review on the node


def test_approve_card_payload_rendered(tmp_path, monkeypatch):
    """Compiled Studio on a seeded isolated Workshop: three held actions raised through the real hook decision."""
    import subprocess
    from pathlib import Path
    from test_task_session_roundtrip import _isolate, _Studio
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '') or subprocess.check_output(
        ['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"],
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import record_step
    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        _public_repo(monkeypatch)
        _ask_first()
        task = client.workshop('createTask', 'Door schedule release')['taskId']
        client.workshop('openTaskGraph', task)
        record = {'root': 'root-proof', 'session': 'identity-proof', 'native_session_id': 'native-proof', 'runtime': 'claude',
                  'work': task, 'status': 'working', 'display_name': 'Claude', 'agent': 'Claude', 'request_id': task,
                  'pid': 999999, 'created_at': 0}
        with application_history() as history:
            with history._transaction(write=True):
                history._db.execute("CREATE TABLE IF NOT EXISTS workshop_declarations("
                                    "root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT")
                history._db.execute("INSERT INTO workshop_declarations VALUES(?,?)", (record['root'], json.dumps(record)))
            record_step(history, task, 'identity-proof', 'Claude', 'Write the release note', 'working')
        hook = lambda tool, data: hook_decision.decide({'tool_name': tool, 'session_id': 'native-proof', 'cwd': str(tmp_path),
                                                        'tool_input': data}, 'claude-code')
        post = hook('connector.call', {'connector': 'linkedin', 'action': 'post', 'arguments': {
            'platform': 'LinkedIn', 'account': 'ArchHub page', 'api_key': 'sk-proofproofproof',
            'text': 'Door schedule is out for review. Level 2 doors now match the fire strategy; comments by Friday.',
            'media': ['C:/Work/out/plan-level-2.png', 'C:/Work/out/issue-sheet.pdf']}})
        push = hook('Bash', {'command': 'git push -q origin HEAD:main'})
        empty = hook('connector.call', {'connector': 'linkedin', 'action': 'post', 'arguments': {'platform': 'LinkedIn'}})
        assert post['verdict'] == push['verdict'] == empty['verdict'] == 'ask', (post, push, empty)
        node = _card(post['hold'])['nodeId']
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/approve_card_payload_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_APPROVE_PAYLOAD_SHOTS', ''), 'post': post['hold'], 'repository': 'ArchHub-site',
                              'push': push['hold'], 'empty': empty['hold'], 'node': node}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=300,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0 and 'APPROVEPAYLOAD OK' in result.stdout, result.stdout + result.stderr
        approved = _card(push['hold'])
        assert approved['status'] == 'approved', approved
        # The waiting agent's identical call now runs once: the permit is taken, then the next ask holds again.
        assert hook_decision._take_permit(approved['input_digest'], os.environ) is True
        assert hook_decision._take_permit(approved['input_digest'], os.environ) is False
    finally:
        client.close()
        server.close()
