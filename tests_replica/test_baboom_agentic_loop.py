import json

from nodelang import agent_composer
from nodelang import existing_workshop_native_host
from nodelang import native_agentic_loop


def test_fake_model_runs_two_tools_then_final_answer():
    calls = []

    def model(messages, tools):
        calls.append([row["role"] for row in messages])
        if len(calls) == 1:
            return {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {"x": 1}}]}
        if len(calls) == 2:
            return {"tool_calls": [{"id": "b", "name": "read.second", "arguments": {"y": 2}}]}
        return {"text": "final answer"}

    executed = []

    def run(name, arguments):
        executed.append((name, arguments))
        return {"ok": True, "value": name}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"read.first": native_agentic_loop.ToolSpec("read.first", run),
         "read.second": native_agentic_loop.ToolSpec("read.second", run)},
        [{"role": "user", "content": "go"}],
        max_steps=12,
    )

    assert result["answer"] == "final answer"
    assert result["model_turns"] == 3
    assert executed == [("read.first", {"x": 1}), ("read.second", {"y": 2})]
    assert [step["tool"] for step in result["steps"]] == ["read.first", "read.second"]


def test_cap_stops_with_plain_line():
    def model(_messages, _tools):
        return {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {}}]}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"read.first": native_agentic_loop.ToolSpec("read.first", lambda *_: {"ok": True})},
        [{"role": "user", "content": "loop"}],
        max_steps=2,
    )

    assert result["answer"] == "stopped after 2 steps"
    assert result["stopped"] is True


def test_write_without_grant_is_refused_and_fed_back():
    executed = []

    def model(messages, _tools):
        if any(row["role"] == "tool" for row in messages):
            tool_rows = [row for row in messages if row["role"] == "tool"]
            return {"text": json.loads(tool_rows[-1]["content"])["status"]}
        return {"tool_calls": [{"id": "w", "name": "write.state", "arguments": {"value": 3}}]}

    def write(name, arguments):
        executed.append((name, arguments))
        return {"ok": True}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"write.state": native_agentic_loop.ToolSpec("write.state", write, mutates=True)},
        [{"role": "user", "content": "change it"}],
        max_steps=12,
        grant_checker=lambda _name, _args: False,
    )

    assert result["answer"] == "refused"
    assert executed == []
    assert result["steps"][0]["status"] == "refused"


def test_no_tools_model_gives_plain_message():
    result = native_agentic_loop.run_agentic_tool_loop(
        lambda _messages, _tools: {"text": "never called"},
        {"read.first": native_agentic_loop.ToolSpec("read.first", lambda *_: {})},
        [{"role": "user", "content": "go"}],
        max_steps=12,
        model_supports_tools=False,
    )

    assert result["answer"] == "this model can't use tools; pick one marked tools"


def test_workshop_and_baboom_import_the_same_loop_entry():
    assert agent_composer.run_agentic_tool_loop is native_agentic_loop.run_agentic_tool_loop
    assert existing_workshop_native_host.run_agentic_tool_loop is native_agentic_loop.run_agentic_tool_loop
