import json
import io
import threading
from types import SimpleNamespace as NS

from nodelang import agent_composer
from nodelang import existing_workshop_native_host
from nodelang import model_router
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


def _two_turns():
    calls = []
    executed = []

    def model(messages, tools):
        calls.append((messages, tools))
        if len(calls) == 1:
            return {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {"x": 1}}]}
        if len(calls) == 2:
            return {"tool_calls": [{"id": "b", "name": "read.second", "arguments": {"y": 2}}]}
        return {"text": "done"}

    def run(name, arguments):
        executed.append((name, arguments))
        return {"ok": True, "name": name}

    tools = {
        "read.first": native_agentic_loop.ToolSpec("read.first", run),
        "read.second": native_agentic_loop.ToolSpec("read.second", run),
    }
    return model, tools, calls, executed


def test_workshop_and_baboom_run_two_turns_through_the_same_shared_loop():
    model, tools, baboom_calls, baboom_executed = _two_turns()
    baboom = agent_composer.run_baboom_tool_loop(
        model, tools, [{"role": "user", "content": "go"}], max_steps=12)

    model, tools, workshop_calls, workshop_executed = _two_turns()
    host = object.__new__(existing_workshop_native_host.ExistingWorkshopNativeHost)
    host.server = NS(is_halted=lambda: False)
    host._native = None
    workshop = host.run_shared_tool_loop(
        model, tools, [{"role": "user", "content": "go"}], max_steps=12)

    assert agent_composer.run_agentic_tool_loop is native_agentic_loop.run_agentic_tool_loop
    assert existing_workshop_native_host.run_agentic_tool_loop is native_agentic_loop.run_agentic_tool_loop
    assert baboom["answer"] == workshop["answer"] == "done"
    assert baboom["model_turns"] == workshop["model_turns"] == 3
    assert [step["tool"] for step in baboom["steps"]] == ["read.first", "read.second"]
    assert [step["tool"] for step in workshop["steps"]] == ["read.first", "read.second"]
    assert baboom_executed == workshop_executed == [
        ("read.first", {"x": 1}),
        ("read.second", {"y": 2}),
    ]
    assert len(baboom_calls) == len(workshop_calls) == 3


def test_text_json_tool_call_runs_and_strips_visible_json():
    seen = []

    def model(messages, _tools):
        seen.append(messages)
        if not any(row["role"] == "tool" for row in messages):
            return {"text": 'I will check.\n\n{"tool":"host.ping","arguments":{"probe":"programs"}}'}
        return {"text": "ArchHub can see the host probe."}

    result = agent_composer.run_baboom_tool_loop(
        model,
        {"host.ping": native_agentic_loop.ToolSpec(
            "host.ping", lambda name, args: {"ok": True, "name": name, "args": args})},
        [{"role": "user", "content": "what programs can ArchHub see"}],
        max_steps=4,
    )

    assert result["answer"] == "ArchHub can see the host probe."
    assert [step["tool"] for step in result["steps"]] == ["host.ping"]
    assert result["steps"][0]["status"] == "ok"
    assert "{" not in seen[1][-2]["content"]
    assert seen[1][-2]["tool_calls"][0]["arguments"] == {"probe": "programs"}


def test_name_parameters_check_programs_alias_never_leaks_raw_json():
    seen = []

    def model(messages, _tools):
        seen.append(messages)
        if not any(row["role"] == "tool" for row in messages):
            return {"text": '{"name":"check_programs","parameters":{}}'}
        return {"text": "Program visibility was checked."}

    result = agent_composer.run_baboom_tool_loop(
        model,
        {"host.ping": native_agentic_loop.ToolSpec(
            "host.ping", lambda _name, _args: {"ok": True, "programs": []})},
        [{"role": "user", "content": "what programs can ArchHub see"}],
        max_steps=4,
    )

    assert result["answer"] == "Program visibility was checked."
    assert [step["tool"] for step in result["steps"]] == ["host.ping"]
    assert "check_programs" not in result["answer"]
    assert "{" not in result["answer"]
    assert seen[1][-2]["content"] == ""


def test_special_token_tool_call_runs_and_strips_raw_tokens():
    seen = []

    def model(messages, _tools):
        seen.append(messages)
        if not any(row["role"] == "tool" for row in messages):
            return {"text": "<|tool_call_start|>[host.ping()]<|tool_call_end|>"}
        return {"text": "Host ping ran."}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"host.ping": native_agentic_loop.ToolSpec(
            "host.ping", lambda name, args: {"ok": True, "name": name, "args": args})},
        [{"role": "user", "content": "ping the host"}],
        max_steps=4,
    )

    assert result["answer"] == "Host ping ran."
    assert [step["tool"] for step in result["steps"]] == ["host.ping"]
    assert result["steps"][0]["args"] == {}
    assert "<|tool_call_start|>" not in seen[1][-2]["content"]
    assert seen[1][-2]["content"] == ""


def test_unknown_text_tool_is_retried_once_without_raw_json():
    seen = []

    def model(messages, _tools):
        seen.append(messages)
        if len(seen) == 1:
            return {"text": '{"tool":"invented.tool","arguments":{}}'}
        if len(seen) == 2:
            return {"text": '{"tool":"invented.tool","arguments":{}}'}
        return {"text": "I cannot use that tool here."}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"host.ping": native_agentic_loop.ToolSpec("host.ping", lambda *_: {"ok": True})},
        [{"role": "user", "content": "check programs"}],
        max_steps=4,
    )

    assert result["answer"] == "I cannot use that tool here."
    assert result["steps"] == []
    assert seen[1][-1]["role"] == "system"
    assert seen[1][-1]["content"] == "unknown tool invented.tool; available: host.ping"
    assert seen[2][-1]["content"] == "answer in plain words; do not print a JSON tool call"


def test_native_tool_calls_still_work_with_text_call_support():
    result = native_agentic_loop.run_agentic_tool_loop(
        lambda _messages, _tools: (
            {"tool_calls": [{"id": "a", "name": "host.ping", "arguments": {}}]}
        ),
        {"host.ping": native_agentic_loop.ToolSpec("host.ping", lambda *_: {"ok": True})},
        [{"role": "user", "content": "check programs"}],
        max_steps=1,
    )

    assert result["steps"][0]["tool"] == "host.ping"
    assert result["steps"][0]["status"] == "ok"


def test_plain_question_stays_plain_without_tool_step():
    result = native_agentic_loop.run_agentic_tool_loop(
        lambda _messages, _tools: {"text": "Plain answer."},
        {"host.ping": native_agentic_loop.ToolSpec("host.ping", lambda *_: {"ok": True})},
        [{"role": "user", "content": "say hello"}],
        max_steps=4,
    )

    assert result["answer"] == "Plain answer."
    assert result["steps"] == []


def test_agentic_loop_stops_before_next_model_turn_when_halted():
    halted = [False]

    def model(_messages, _tools):
        return {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {}}]}

    def run(_name, _args):
        halted[0] = True
        return {}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"read.first": native_agentic_loop.ToolSpec("read.first", run)},
        [{"role": "user", "content": "go"}],
        is_halted=lambda: halted[0],
    )

    assert result["answer"] == "Stopped by you"
    assert result["model_turns"] == 1
    assert len(result["steps"]) == 1


def test_agentic_loop_stops_before_tool_call_when_halted():
    called = []
    halted = [False]

    def model(_messages, _tools):
        halted[0] = True
        return {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {}}]}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"read.first": native_agentic_loop.ToolSpec("read.first", lambda *_: called.append(True))},
        [{"role": "user", "content": "go"}],
        is_halted=lambda: halted[0],
    )

    assert called == []
    assert result == {"answer": "Stopped by you", "steps": [], "model_turns": 1, "stopped": True}


def test_agentic_loop_reports_admitted_tool_failure():
    def model(_messages, _tools):
        return {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {}}]}

    result = native_agentic_loop.run_agentic_tool_loop(
        model,
        {"read.first": native_agentic_loop.ToolSpec(
            "read.first", lambda *_: {"ok": False, "error": "tool refused"})},
        [{"role": "user", "content": "go"}],
        max_steps=1,
    )

    assert result["steps"][0]["ok"] is False
    assert result["steps"][0]["summary"] == "tool refused"


def test_agentic_loop_reports_uncertain_tool_result_as_failure():
    result = native_agentic_loop.run_agentic_tool_loop(
        lambda _messages, _tools: {"tool_calls": [{"id": "a", "name": "read.first", "arguments": {}}]},
        {"read.first": native_agentic_loop.ToolSpec(
            "read.first", lambda *_: {"ok": True, "status": "uncertain", "error": "unknown outcome"})},
        [{"role": "user", "content": "go"}],
        max_steps=1,
    )

    assert result["steps"][0]["ok"] is False
    assert result["steps"][0]["status"] == "uncertain"


def test_baboom_hides_unimplemented_tools_and_reads_real_context():
    context = "CANVAS CONTEXT\n" + json.dumps({"revision": 7, "nodes": [{"id": "n"}]})
    host_calls = []
    tools = agent_composer._baboom_tool_specs(
        context_block=context,
        host_reader=lambda name, args: host_calls.append((name, args)) or {"ok": True, "pong": True},
    )

    assert set(agent_composer._baboom_tool_specs(context_block=context)) == {"graph.read", "host.ping"}
    assert set(tools) == {"graph.read", "host.ping", "brain.context", "brain.write"}
    assert tools["brain.context"].mutates is False
    assert tools["brain.write"].mutates is True
    assert "host.read" not in tools
    assert "native.work_submit" in agent_composer.baboom_hidden_tool_names()
    assert tools["graph.read"].mutates is False
    assert tools["host.ping"].run("host.ping", {"probe": "now"}) == {"ok": True, "pong": True}
    assert host_calls == [("ping", {"probe": "now"})]
    assert tools["graph.read"].run("graph.read", {})["graph"]["revision"] == 7


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class _Wire:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.sent = []

    def __call__(self, request, timeout=None):
        self.sent.append(request)
        return _Answer(json.dumps(self.payloads.pop(0)).encode("utf-8"))

    def body(self, index):
        return json.loads(self.sent[index].data.decode("utf-8"))


def test_router_turn_two_sends_provider_compatible_tool_envelope():
    wire = _Wire([
        {"choices": [{"message": {"content": "", "tool_calls": [{
            "id": "call-a", "type": "function",
            "function": {"name": "read.first", "arguments": "{\"x\":1}"},
        }]}, "finish_reason": "tool_calls"}], "model": "test-model"},
        {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
         "model": "test-model"},
    ])

    def turn(rows, tool_schemas):
        return model_router.route_chat(
            "openrouter/test-model",
            rows,
            opener=wire,
            environ={"OPENROUTER_API_KEY": "fixture"},
            secrets_loader=lambda _: "",
            tools=tool_schemas,
        )

    result = native_agentic_loop.run_agentic_tool_loop(
        turn,
        {"read.first": native_agentic_loop.ToolSpec("read.first", lambda *_: {"ok": True})},
        [{"role": "user", "content": "go"}],
        max_steps=4,
    )

    second = wire.body(1)["messages"]
    assert result["answer"] == "done"
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"] == [{
        "id": "call-a",
        "type": "function",
        "function": {"name": "read.first", "arguments": "{\"x\":1}"},
    }]
    assert second[-1]["role"] == "tool"
    assert second[-1]["tool_call_id"] == "call-a"


def test_real_router_final_answer_after_stop_resume_is_discarded():
    generation = [0]
    halted = [False]
    started = threading.Event()
    release = threading.Event()
    sent = []

    class BlockingProvider:
        def __call__(self, request, timeout=None):
            sent.append(request)
            started.set()
            assert release.wait(10), "provider double was not released"
            return _Answer(json.dumps({
                "choices": [{"message": {"content": "late final"}, "finish_reason": "stop"}],
                "model": "test-model",
            }).encode("utf-8"))

    def turn(rows, tool_schemas):
        return model_router.route_chat(
            "openrouter/test-model",
            rows,
            opener=BlockingProvider(),
            environ={"OPENROUTER_API_KEY": "fixture"},
            secrets_loader=lambda _: "",
            tools=tool_schemas,
        )

    result = {}
    thread = threading.Thread(target=lambda: result.update(native_agentic_loop.run_agentic_tool_loop(
        turn,
        {"read.first": native_agentic_loop.ToolSpec(
            "read.first", lambda *_: {"ok": True})},
        [{"role": "user", "content": "go"}],
        max_steps=4,
        is_halted=lambda: halted[0],
        halt_generation=lambda: generation[0],
    )), daemon=True)
    thread.start()
    assert started.wait(10)
    halted[0] = True
    generation[0] += 1
    halted[0] = False
    release.set()
    thread.join(10)

    assert result == {"answer": "Stopped by you", "steps": [], "model_turns": 1, "stopped": True}
    assert len(sent) == 1
