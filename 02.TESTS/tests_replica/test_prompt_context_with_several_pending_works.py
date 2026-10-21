"""Court: the prompt hook answers for a session with several pending Works (live 717, 2026-09-30).

The UserPromptSubmit hook (native.hook_user_prompt_submit) read "the current
assignment" for the whole session and raised "Agent Session owns multiple
active governed-work assignments" for any session holding two or more pending
Works: 717 (nine submitted, one claimed) and the founder's desktop (four). Those
sessions got no Work context on any prompt.

Now, with a Work attached, the hook shows that Work. With none attached, it
lists the session's pending Works by root and state, bounded, instead of
raising.

Real application server, real native owners; nothing is faked.
"""
import json

from nodelang.native_agent_mcp import attach_workshop_tools
from tests_replica.test_attached_work_reaches_its_own_court import _call, _claim, _native, _works, app  # noqa: F401


def _context(result):
    return json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])


def test_several_pending_works_are_listed_not_refused(app, tmp_path):
    _server, owner = app
    submitted, other, held = _works(owner, "a.flag", "a.flag", "a.flag")
    native, server = _native(tmp_path, "prompt-context-several")
    _claim(native, submitted, submit=True)
    _claim(native, other, submit=True)
    _claim(native, held)

    context = _context(_call(server, "native.hook_user_prompt_submit"))
    assert context["current_work"] is None
    pending = context["pending_works"]
    assert {(row["root"], row["state"]) for row in pending["works"]} == {
        (submitted, "review"), (other, "review"), (held, "claimed")}
    assert (pending["total"], pending["truncated"]) == (3, False)

    _call(server, "native.work_task_attach", work_root=other)
    context = _context(_call(server, "native.hook_user_prompt_submit"))
    assert (context["current_work"]["root"], context["current_work_state"]) == (other, "review")
    assert context["pending_works"] is None


def test_the_attached_task_surface_hook_shows_its_own_work(app, tmp_path):
    _server, owner = app
    submitted, held = _works(owner, "a.flag", "a.flag")
    native, _server_tools = _native(tmp_path, "prompt-context-task")
    _claim(native, submitted, submit=True)
    _claim(native, held)
    task = attach_workshop_tools(native, submitted)      # the embedded clients' task surface
    context = _context(_call(task, "native.hook_user_prompt_submit"))
    assert (context["current_work"]["root"], context["current_work_state"]) == (submitted, "review")


def test_the_pending_list_is_bounded(app, tmp_path):
    _server, owner = app
    roots = _works(owner, *(["a.flag"] * 22))
    native, server = _native(tmp_path, "prompt-context-bounded")
    for root in roots:
        _claim(native, root, submit=True)
    pending = _context(_call(server, "native.hook_user_prompt_submit"))["pending_works"]
    assert (len(pending["works"]), pending["total"], pending["truncated"]) == (20, 22, True)
