"""Protocol double for pinned Goose, never an LLM/provider or a host app."""
import base64
import json
import sys
import urllib.request


def send(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def post(server, method, params, request_id=1):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": "2025-03-26"}
    headers.update({row["name"]: row["value"] for row in server["headers"]})
    request = urllib.request.Request(server["url"], data=json.dumps({"jsonrpc": "2.0", "id": request_id,
        "method": method, "params": params}).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)["result"]


def answer_read(prompt_id, server):
    post(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "fake-goose", "version": "1"}})
    tools = post(server, "tools/list", {})
    assert [row["name"] for row in tools["tools"]] == ["hosts_state"]
    result = post(server, "tools/call", {"name": "hosts_state", "arguments": {}})
    assert not result.get("isError"), result
    text = " ".join(row["text"] for row in result["content"] if row["type"] == "text")
    send({"method": "session/update", "params": {"sessionId": "fake-session", "update": {
        "sessionUpdate": "tool_call_update", "toolCallId": "one", "status": "completed",
        "content": [{"type": "content", "content": {"type": "text", "text": text}}]}}})
    send({"method": "session/update", "params": {"sessionId": "fake-session", "update": {
        "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Host state: " + text}}}})
    send({"id": prompt_id, "result": {"stopReason": "end_turn"}})

mode = sys.argv[1] if len(sys.argv) > 1 else "read"
extension = None
for line in sys.stdin.buffer:
    message = json.loads(line)
    method, params = message.get("method"), message.get("params", {})
    if not method:
        if message.get("id") == "permission":
            if mode in {"permission", "spoof"}:
                assert message["result"] == {"outcome": {"outcome": "cancelled"}}
                send({"id": prompt_id, "result": {"stopReason": "refusal"}})
            else:
                assert message["result"] == {"outcome": {"outcome": "selected", "optionId": "read-once"}}
                answer_read(prompt_id, extension["server"])
        continue
    if method == "initialize":
        assert params["clientCapabilities"]["terminal"] is False
        assert not params["clientCapabilities"]["fs"]["writeTextFile"]
        send({"id": message["id"], "result": {"protocolVersion": 1, "agentCapabilities": {"mcpCapabilities": {"http": True}}}})
    elif method == "session/new":
        meta = params["_meta"]
        assert "provider" not in meta
        recipe = json.loads(base64.urlsafe_b64decode(meta["recipeDeeplink"] + "=" * (-len(meta["recipeDeeplink"]) % 4)))
        assert "extensions" not in recipe
        assert recipe["settings"]["goose_provider"] in {"openrouter", "ollama"}
        assert recipe["settings"]["goose_provider"] == "ollama" or recipe["settings"]["goose_model"] == "openrouter/free" or recipe["settings"]["goose_model"].endswith(":free")
        assert params["mcpServers"] == []
        assert len(meta["enabledExtensions"]) == 1
        extension = meta["enabledExtensions"][0]
        assert extension["type"] == "mcp" and extension["available_tools"] == ["hosts_state"]
        assert extension["server"]["name"] == "archhub-hosts"
        send({"id": message["id"], "result": {"sessionId": "fake-session"}})
    elif method == "session/prompt":
        prompt_id = message["id"]
        if mode == "permission":
            send({"id": "permission", "method": "session/request_permission", "params": {
                "sessionId": "fake-session", "toolCall": {"toolCallId": "write", "title": "Write file"},
                "options": [{"optionId": "yes", "name": "Allow", "kind": "allow_once"}]}})
            continue
        if mode == "error":
            send({"id": prompt_id, "error": {"code": -32000, "message": "secret=do-not-display"}})
            continue
        send({"method": "session/update", "params": {"sessionId": "fake-session", "update": {
            "sessionUpdate": "tool_call", "toolCallId": "one", "title": "archhub-hosts: hosts state", "status": "in_progress",
            "_meta": {"goose": {"toolCall": {"extensionName": "archhub-hosts",
                       "toolName": "archhub-hosts__execute" if mode == "spoof" else "archhub-hosts__hosts_state"}}}}}})
        send({"id": "permission", "method": "session/request_permission", "params": {
            "sessionId": "fake-session", "toolCall": {"toolCallId": "one", "title": "archhub-hosts: hosts state", "rawInput": {}},
            "options": [{"optionId": "read-once", "name": "Allow once", "kind": "allow_once"}]}})
